"""Outbound Cell Throughput Simulator — core model."""

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

    def summary(self) -> dict:
        return {}


def case_generator(env: simpy.Environment, config: Config, rng: np.random.Generator,
                    buffer: simpy.Store, metrics: Metrics):
    """SimPy process: create cases with increasing seq_id, deliver into the FIFO buffer."""
    sample_gap = make_interarrival_sampler(config, rng)
    seq_id = 0
    while True:
        yield env.timeout(sample_gap())
        case = Case(seq_id=seq_id, created_t=env.now)
        seq_id += 1
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
    return metrics.summary()


if __name__ == "__main__":
    cfg = Config()
    print(cfg)
