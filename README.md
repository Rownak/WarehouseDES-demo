# WarehouseDES — Outbound Cell Throughput Simulator

## Project Description

A discrete-event simulation of a robotic warehouse outbound palletizing cell. Robots deliver cases to a single cell that palletizes at a fixed rate (1,350 cases/hr, ~2.67 s/case). The model measures how **arrival variability** and **pallet sequencing constraints** erode effective throughput below nominal capacity — showing that delay is often a *sequencing failure*, not a speed problem.

Built with Python + SimPy, intentionally small (~150 lines of core model) and fully reproducible from a seed.

> **Status:** Phase 1 (core model) complete. FIFO service works end to end; metrics reporting, CLI, sequence policy, and comparison charts are in progress. See `tasks.md` for the build plan.

## Features

Working today:

- Discrete-event model of an outbound cell with deterministic service time
- Stochastic case generation — exponential or lognormal inter-arrivals with configurable coefficient of variation
- Finite staging buffer with rejection counting when full
- FIFO service policy, with starved ("blocked") intervals recorded by cause
- Raw metrics collection: completed cases, blocked intervals, buffer level trace, reject count
- Deterministic reproducibility — same seed and config always produce identical results

Planned (see `tasks.md`): summary statistics + console report, CLI flags, strict pallet-sequence policy, CV sweep and comparison chart.

## Tech Stack

| Concern | Choice |
|---|---|
| Simulation engine | SimPy 4 |
| Language | Python 3.10+ |
| Randomness | `numpy.random.Generator` (one per run, passed explicitly) |
| Post-processing | pandas |
| Plotting | matplotlib |

## Installation

```bash
cd outbound-cell-sim
pip install -r requirements.txt
```

## Usage

Run the script directly to confirm the setup and print the default configuration:

```bash
python sim.py
```

The model's entry point is `run_once(config)`. Since `Metrics.summary()` is still a stub returning `{}` (Phase 2 work), inspect the `Metrics` object directly for now — run this from inside `outbound-cell-sim/`:

```python
import numpy as np, simpy
from sim import Config, Metrics, case_generator, outbound_cell

cfg = Config(arrival_cv=1.0, seed=42)      # try cv=0.25 (steady) vs cv=2.0 (bursty)
rng = np.random.default_rng(cfg.seed)
env = simpy.Environment()
buffer = simpy.Store(env, capacity=cfg.buffer_capacity)
metrics = Metrics()

env.process(case_generator(env, cfg, rng, buffer, metrics))
env.process(outbound_cell(env, cfg, buffer, metrics))
env.run(until=cfg.sim_duration_s)

print("completed:", len(metrics.completed))          # 5307 at defaults
print("rejected: ", metrics.rejected_count)          # 154 — buffer was full
print("starved:  ", len(metrics.blocked_intervals))  # 77 idle intervals
```

All parameters live in `Config` (`sim.py`) — cell rate, arrival distribution and CV, buffer capacity, policy, duration, warm-up, and seed. Raising `arrival_cv` increases both rejections and starved time even though average supply still matches cell capacity: the core effect this project exists to demonstrate.
