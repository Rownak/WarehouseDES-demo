# WarehouseDES — Outbound Cell Throughput Simulator

## Project Description

A discrete-event simulation of a robotic warehouse outbound palletizing cell. Robots deliver cases to a single cell that palletizes at a fixed rate (1,350 cases/hr, ~2.67 s/case). The model measures how **arrival variability** and **pallet sequencing constraints** erode effective throughput below nominal capacity — showing that delay is often a *sequencing failure*, not a speed problem.

Built with Python + SimPy, intentionally small (~150 lines of core model) and fully reproducible from a seed.

> **Status:** Phase 2 (metrics & CLI) complete. FIFO service, post-warm-up summary statistics, console report, and CLI flags all work end to end. Strict pallet-sequence policy and the comparison sweep/chart are still in progress. See `tasks.md` for the build plan.

## Features

Working today:

- Discrete-event model of an outbound cell with deterministic service time
- Stochastic case generation — exponential or lognormal inter-arrivals with configurable coefficient of variation
- Finite staging buffer with rejection counting when full
- FIFO service policy, with starved ("blocked") intervals recorded by cause
- Raw metrics collection: completed cases, blocked intervals, buffer level trace, reject count
- Post-warm-up summary statistics — throughput vs. nominal, utilization, mean/p95 wait, starved % by cause, mean buffer level, reject count, and generated/completed/in-system conservation
- One-screen console report (`print_summary`)
- CLI flags (`--policy`, `--cv`, `--seed`, `--duration`) mapping straight onto `Config`
- Deterministic reproducibility — same seed and config always produce identical results

Planned (see `tasks.md`): strict pallet-sequence policy, CV sweep and comparison chart.

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

Run the script directly for a default run (FIFO, CV=1.0, seed=42, 4 simulated hours) — it prints a one-screen summary:

```bash
cd outbound-cell-sim
python sim.py
```

```
=== Outbound Cell Simulation Summary (post warm-up) ===
Throughput:        1324.0 cases/hr  (nominal 1350 cases/hr)
Utilization:       98.1 %
Mean wait:         29.15 s
P95 wait:          51.75 s
Mean buffer level: 10.90 cases
Starved time:
  - empty                1.93 %
Reject count:      154
Generated:         5467
Completed:         5307
In-system (end):   6
```

CLI flags map straight onto `Config` fields:

```bash
python sim.py --policy fifo --cv 0.5 --seed 7 --duration 14400
```

| Flag | Meaning | Default |
|---|---|---|
| `--policy` | `fifo` or `sequence` | `fifo` |
| `--cv` | arrival coefficient of variation | `1.0` |
| `--seed` | RNG seed | `42` |
| `--duration` | simulated duration, s | `14400` (4 hr) |

Compare policies at one setting by running the same seed twice with different `--policy` values and diffing the summaries — same arrivals, different service discipline (sequence policy is Phase 3 work; the flag is accepted today but currently still runs FIFO behavior under the hood).

The model's entry point for programmatic use is `run_once(config) -> dict`:

```python
from sim import Config, run_once, print_summary

cfg = Config(arrival_cv=1.0, seed=42)  # try cv=0.25 (steady) vs cv=2.0 (bursty)
summary = run_once(cfg)
print_summary(summary)
```

All parameters live in `Config` (`sim.py`) — cell rate, arrival distribution and CV, buffer capacity, policy, duration, warm-up, and seed. Raising `arrival_cv` increases both rejections and starved time even though average supply still matches cell capacity: the core effect this project exists to demonstrate.
