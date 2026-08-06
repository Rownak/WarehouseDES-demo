"""Outbound Cell Throughput Simulator — core model."""

import argparse
import math
from dataclasses import dataclass, field
from typing import Callable, Optional

import numpy as np
import simpy


@dataclass
class Config:
    cell_rate_cases_per_hr: float = 1350  # fixed palletizing rate, cases/hr
    service_time_s: float = field(init=False)  # derived: 3600 / cell_rate_cases_per_hr, s
    mean_interarrival_s: float = 2.667  # average case arrival interval, s
    arrival_cv: float = 1.0  # coefficient of variation of inter-arrival times
    arrival_dist: str = "lognormal"  # "exponential" or "lognormal"
    buffer_capacity: int = 20  # max cases staged in front of the cell
    shuffle_window: int = 5  # max look-ahead used to scramble seq_id vs. arrival order (1 = strict order)
    policy: str = "fifo"  # "fifo" or "sequence"
    sim_duration_s: float = 4 * 3600  # simulated time, s (4 hours default)
    warmup_s: float = 1800  # metrics before this time are discarded, s
    seed: int = 42  # RNG seed

    def __post_init__(self) -> None:
        self.service_time_s = 3600 / self.cell_rate_cases_per_hr


@dataclass
class Case:
    seq_id: int  # required pallet-build order; may differ from arrival order (see shuffle_window)
    created_t: float  # sim time the case was created, s
    arrived_t: Optional[float] = None  # sim time the case arrived at the buffer, s
    service_start_t: Optional[float] = None  # sim time service began, s
    service_end_t: Optional[float] = None  # sim time service completed, s


def make_interarrival_sampler(config: Config, rng: np.random.Generator) -> Callable[[], float]:
    """Return a zero-arg callable sampling one inter-arrival gap (s)."""
    mean = config.mean_interarrival_s
    cv = config.arrival_cv

    if config.arrival_dist == "exponential":
        return lambda: rng.exponential(mean)

    if config.arrival_dist == "lognormal":
        sigma = math.sqrt(math.log(1 + cv ** 2))
        mu = math.log(mean) - sigma ** 2 / 2
        return lambda: rng.lognormal(mu, sigma)

    raise ValueError(f"Unknown arrival_dist: {config.arrival_dist!r}")


class Metrics:
    """Plain-list recorder; statistics are computed post-run in summary()."""

    def __init__(self) -> None:
        self.completed: list[Case] = []
        self.blocked_intervals: list[tuple[float, float, str]] = []  # (start, end, cause)
        self.buffer_level_trace: list[tuple[float, int]] = []  # (t, level), appended on insert/remove
        self.rejected_count: int = 0
        self.generated_count: int = 0

    def summary(self, config: "Config") -> dict:
        """Post-warm-up statistics. Excludes anything before config.warmup_s."""
        warmup_s = config.warmup_s
        observed_s = config.sim_duration_s - warmup_s

        completed = [c for c in self.completed if c.service_end_t >= warmup_s]
        n_completed = len(completed)

        throughput_cases_per_hr = n_completed / observed_s * 3600 if observed_s > 0 else 0.0

        busy_s = sum(
            min(c.service_end_t, config.sim_duration_s) - max(c.service_start_t, warmup_s)
            for c in completed
        )
        utilization = busy_s / observed_s if observed_s > 0 else 0.0

        wait_times_s = [c.service_start_t - c.arrived_t for c in completed]
        mean_wait_s = float(np.mean(wait_times_s)) if wait_times_s else 0.0
        p95_wait_s = float(np.percentile(wait_times_s, 95)) if wait_times_s else 0.0

        # Clip blocked intervals to the post-warm-up observation window and sum by cause.
        starved_s_by_cause: dict[str, float] = {}
        for start, end, cause in self.blocked_intervals:
            clipped_start = max(start, warmup_s)
            clipped_end = min(end, config.sim_duration_s)
            if clipped_end > clipped_start:
                starved_s_by_cause[cause] = starved_s_by_cause.get(cause, 0.0) + (clipped_end - clipped_start)
        starved_pct_by_cause = {
            f"starved_pct_{cause}": (duration / observed_s * 100 if observed_s > 0 else 0.0)
            for cause, duration in starved_s_by_cause.items()
        }

        post_warmup_levels = [level for t, level in self.buffer_level_trace if t >= warmup_s]
        mean_buffer_level = float(np.mean(post_warmup_levels)) if post_warmup_levels else 0.0

        in_system_count = self.generated_count - len(self.completed) - self.rejected_count

        result = {
            "throughput_cases_per_hr": throughput_cases_per_hr,
            "nominal_cases_per_hr": config.cell_rate_cases_per_hr,
            "utilization": utilization,
            "mean_wait_s": mean_wait_s,
            "p95_wait_s": p95_wait_s,
            "mean_buffer_level": mean_buffer_level,
            "rejected_count": self.rejected_count,
            "generated_count": self.generated_count,
            "completed_count": len(self.completed),
            "in_system_count": in_system_count,
            **starved_pct_by_cause,
        }

        # M/D/1 analytic reference (arch §6): valid only for exponential arrivals,
        # FIFO service, and a stable system (rho < 1) — the textbook formula
        # assumes an unbounded queue and would misstate blocked/rejected time otherwise.
        if config.arrival_dist == "exponential" and config.policy == "fifo" and utilization < 1:
            rho = utilization
            s = config.service_time_s
            result["mdl_wait_s"] = rho * s / (2 * (1 - rho))

        return result


class SequenceBuffer:
    """Sequence-mode buffer: {seq_id: Case} with capacity + per-seq-id wait events.

    The cell must retrieve a *specific* case (the next seq_id), not the oldest,
    so this is a dict guarded by capacity checks rather than a simpy.Store.
    Insertion triggers the waiting event for that seq_id, if any (arch §2.4/§5.3).
    """

    def __init__(self, env: simpy.Environment, capacity: int) -> None:
        self.env = env
        self.capacity = capacity
        self.items: dict[int, Case] = {}
        self._wait_events: dict[int, simpy.Event] = {}
        self._skipped: set[int] = set()  # seq_ids rejected on arrival (dropped, never inserted)

    def __len__(self) -> int:
        return len(self.items)

    def put(self, case: Case) -> None:
        self.items[case.seq_id] = case
        event = self._wait_events.pop(case.seq_id, None)
        if event is not None:
            event.succeed()

    def skip(self, seq_id: int) -> None:
        """Mark seq_id as dropped so a waiting cell does not block on it forever."""
        self._skipped.add(seq_id)
        event = self._wait_events.pop(seq_id, None)
        if event is not None:
            event.succeed()

    def get_next(self, expected_seq_id: int):
        """Generator: yields until seq_id is inserted or skipped, then returns the
        case (or None if it was dropped) so the cell can advance past the gap."""
        if expected_seq_id not in self.items and expected_seq_id not in self._skipped:
            event = self._wait_events.setdefault(expected_seq_id, self.env.event())
            yield event
        self._skipped.discard(expected_seq_id)
        return self.items.pop(expected_seq_id, None)


def buffer_len(buffer) -> int:
    """Level of either buffer type: simpy.Store (FIFO) or SequenceBuffer."""
    return len(buffer.items)


def make_seq_id_sampler(config: Config, rng: np.random.Generator) -> Callable[[], int]:
    """Return a zero-arg callable yielding the seq_id for the next created case.

    Every non-negative integer is returned exactly once, but not necessarily in
    increasing order: ids are drawn from a sliding look-ahead window of size
    shuffle_window, shuffled with the run's rng, so a case's build-sequence
    position (seq_id) can lead or lag its arrival order by up to
    shuffle_window - 1 places — modeling a picker working a local zone rather
    than a strict single-file line. shuffle_window=1 reproduces strict order.
    """
    next_unpooled = 0
    pool: list[int] = []

    def sample() -> int:
        nonlocal next_unpooled, pool
        while len(pool) < config.shuffle_window:
            pool.append(next_unpooled)
            next_unpooled += 1
        rng.shuffle(pool)
        return pool.pop()

    return sample


def case_generator(env: simpy.Environment, config: Config, rng: np.random.Generator,
                    buffer, metrics: Metrics):
    """SimPy process: create cases (renewal-process arrivals), deliver into the buffer.

    seq_id (the required pallet-build order) is assigned per make_seq_id_sampler,
    decoupled from arrival order by up to shuffle_window - 1 places.
    """
    sample_gap = make_interarrival_sampler(config, rng)
    sample_seq_id = make_seq_id_sampler(config, rng)
    while True:
        yield env.timeout(sample_gap())
        case = Case(seq_id=sample_seq_id(), created_t=env.now)
        metrics.generated_count += 1
        if buffer_len(buffer) >= config.buffer_capacity:
            metrics.rejected_count += 1
            if config.policy == "sequence":
                buffer.skip(case.seq_id)
            continue
        case.arrived_t = env.now
        if config.policy == "sequence":
            buffer.put(case)
        else:
            yield buffer.put(case)
        metrics.buffer_level_trace.append((env.now, buffer_len(buffer)))


def outbound_cell(env: simpy.Environment, config: Config,
                   buffer, metrics: Metrics):
    """SimPy process: the single server. FIFO blocks on store.get(); sequence
    awaits the next seq_id in strictly increasing order."""
    next_seq_id = 0
    while True:
        idle_start = env.now
        if config.policy == "sequence":
            # "waiting_for_sequence" requires seq_id order to differ from arrival
            # order, so a later-needed id can be sitting in the buffer while the
            # next-required one hasn't arrived yet. make_seq_id_sampler's shuffle
            # window is what creates that divergence (shuffle_window=1 disables
            # it and collapses this cause to "empty", same as FIFO).
            cause = "waiting_for_sequence" if buffer_len(buffer) > 0 else "empty"
            case = yield from buffer.get_next(next_seq_id)
            next_seq_id += 1
        else:
            case = yield buffer.get()
            cause = "empty"
        metrics.buffer_level_trace.append((env.now, buffer_len(buffer)))
        if env.now > idle_start:
            metrics.blocked_intervals.append((idle_start, env.now, cause))

        if case is None:
            continue  # seq_id was dropped (buffer was full on arrival); skip and move on

        case.service_start_t = env.now
        yield env.timeout(config.service_time_s)
        case.service_end_t = env.now
        metrics.completed.append(case)


def run_once(config: Config, return_metrics: bool = False):
    """Build env, wire components, run for sim_duration_s, return metrics.summary().

    If return_metrics is True, return (summary, metrics) instead — used by the
    buffer trace plot, which needs raw buffer_level_trace, not just the summary.
    """
    rng = np.random.default_rng(config.seed)
    env = simpy.Environment()
    if config.policy == "sequence":
        buffer = SequenceBuffer(env, capacity=config.buffer_capacity)
    else:
        buffer = simpy.Store(env, capacity=config.buffer_capacity)
    metrics = Metrics()

    env.process(case_generator(env, config, rng, buffer, metrics))
    env.process(outbound_cell(env, config, buffer, metrics))

    env.run(until=config.sim_duration_s)
    summary = metrics.summary(config)
    return (summary, metrics) if return_metrics else summary


def print_summary(summary: dict) -> None:
    """One-screen labeled console report, units shown."""
    starved_keys = sorted(k for k in summary if k.startswith("starved_pct_"))

    print("=== Outbound Cell Simulation Summary (post warm-up) ===")
    print(f"Throughput:        {summary['throughput_cases_per_hr']:.1f} cases/hr"
          f"  (nominal {summary['nominal_cases_per_hr']:.0f} cases/hr)")
    print(f"Utilization:       {summary['utilization'] * 100:.1f} %")
    print(f"Mean wait:         {summary['mean_wait_s']:.2f} s")
    if "mdl_wait_s" in summary:
        print(f"  (M/D/1 analytic: {summary['mdl_wait_s']:.2f} s)")
        if summary["utilization"] > 0.9 or summary["rejected_count"] > 0:
            print("  Note: M/D/1 assumes an unbounded queue and is most accurate at"
                  " moderate utilization; at high utilization or with rejects, expect"
                  " the analytic and simulated waits to diverge.")
    print(f"P95 wait:          {summary['p95_wait_s']:.2f} s")
    print(f"Mean buffer level: {summary['mean_buffer_level']:.2f} cases")
    print("Starved time:")
    if starved_keys:
        for k in starved_keys:
            cause = k[len("starved_pct_"):]
            print(f"  - {cause:<20} {summary[k]:.2f} %")
    else:
        print("  (none)")
    print(f"Reject count:      {summary['rejected_count']}")
    print(f"Generated:         {summary['generated_count']}")
    print(f"Completed:         {summary['completed_count']}")
    print(f"In-system (end):   {summary['in_system_count']}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Outbound Cell Throughput Simulator")
    parser.add_argument("--policy", choices=["fifo", "sequence"], default=Config.policy,
                         help="service policy (default: %(default)s)")
    parser.add_argument("--cv", type=float, default=Config.arrival_cv,
                         help="arrival coefficient of variation (default: %(default)s)")
    parser.add_argument("--dist", choices=["exponential", "lognormal"], default=Config.arrival_dist,
                         help="inter-arrival distribution (default: %(default)s)")
    parser.add_argument("--seed", type=int, default=Config.seed,
                         help="RNG seed (default: %(default)s)")
    parser.add_argument("--duration", type=float, default=Config.sim_duration_s,
                         help="simulated duration, s (default: %(default)s)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    cfg = Config(policy=args.policy, arrival_cv=args.cv, arrival_dist=args.dist,
                 seed=args.seed, sim_duration_s=args.duration)
    result = run_once(cfg)
    print_summary(result)
