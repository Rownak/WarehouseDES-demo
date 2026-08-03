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
    policy: str = "fifo"  # "fifo" or "sequence"
    sim_duration_s: float = 4 * 3600  # simulated time, s (4 hours default)
    warmup_s: float = 1800  # metrics before this time are discarded, s
    seed: int = 42  # RNG seed

    def __post_init__(self) -> None:
        self.service_time_s = 3600 / self.cell_rate_cases_per_hr


@dataclass
class Case:
    seq_id: int  # pallet sequence order, assigned at creation in increasing order
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

        return {
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


def case_generator(env: simpy.Environment, config: Config, rng: np.random.Generator,
                    buffer: simpy.Store, metrics: Metrics):
    """SimPy process: create cases with increasing seq_id, deliver into the FIFO buffer."""
    sample_gap = make_interarrival_sampler(config, rng)
    seq_id = 0
    while True:
        yield env.timeout(sample_gap())
        case = Case(seq_id=seq_id, created_t=env.now)
        seq_id += 1
        metrics.generated_count += 1
        if len(buffer.items) >= config.buffer_capacity:
            metrics.rejected_count += 1
            continue
        case.arrived_t = env.now
        yield buffer.put(case)
        metrics.buffer_level_trace.append((env.now, len(buffer.items)))


def outbound_cell(env: simpy.Environment, config: Config,
                   buffer: simpy.Store, metrics: Metrics):
    """SimPy process: the single server. FIFO only — blocks on store.get()."""
    while True:
        idle_start = env.now
        case = yield buffer.get()
        metrics.buffer_level_trace.append((env.now, len(buffer.items)))
        if env.now > idle_start:
            metrics.blocked_intervals.append((idle_start, env.now, "empty"))

        case.service_start_t = env.now
        yield env.timeout(config.service_time_s)
        case.service_end_t = env.now
        metrics.completed.append(case)


def run_once(config: Config) -> dict:
    """Build env, wire components, run for sim_duration_s, return metrics.summary()."""
    rng = np.random.default_rng(config.seed)
    env = simpy.Environment()
    buffer = simpy.Store(env, capacity=config.buffer_capacity)
    metrics = Metrics()

    env.process(case_generator(env, config, rng, buffer, metrics))
    env.process(outbound_cell(env, config, buffer, metrics))

    env.run(until=config.sim_duration_s)
    return metrics.summary(config)


def print_summary(summary: dict) -> None:
    """One-screen labeled console report, units shown."""
    starved_keys = sorted(k for k in summary if k.startswith("starved_pct_"))

    print("=== Outbound Cell Simulation Summary (post warm-up) ===")
    print(f"Throughput:        {summary['throughput_cases_per_hr']:.1f} cases/hr"
          f"  (nominal {summary['nominal_cases_per_hr']:.0f} cases/hr)")
    print(f"Utilization:       {summary['utilization'] * 100:.1f} %")
    print(f"Mean wait:         {summary['mean_wait_s']:.2f} s")
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
    parser.add_argument("--seed", type=int, default=Config.seed,
                         help="RNG seed (default: %(default)s)")
    parser.add_argument("--duration", type=float, default=Config.sim_duration_s,
                         help="simulated duration, s (default: %(default)s)")
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    cfg = Config(policy=args.policy, arrival_cv=args.cv, seed=args.seed, sim_duration_s=args.duration)
    result = run_once(cfg)
    print_summary(result)
