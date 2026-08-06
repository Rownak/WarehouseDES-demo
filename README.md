# Outbound Cell Throughput Simulator

A discrete-event simulation of a robotic warehouse outbound palletizing cell — showing that lost throughput is often a *sequencing failure*, not a speed problem.

## The question this project answers

If a warehouse's outbound cell can palletize 1,350 cases/hour and cases arrive at an average rate of 1,350/hour, why does effective throughput fall short — and how much worse does it get when cases must be served in strict pallet-build order instead of first-come-first-served? This model isolates arrival variability and sequencing constraints from everything else (routing, slotting, fleet size) to quantify that gap on its own.

## What it does

- Simulates a single outbound cell fed by stochastic case arrivals (exponential or lognormal, configurable coefficient of variation) against a fixed, deterministic service rate.
- Compares two service policies head-to-head — FIFO vs. strict pallet-sequence order — under identical arrival streams, quantifying the throughput and wait-time penalty sequencing adds as arrival variability increases.
- Produces reproducible, seed-controlled metrics (throughput, utilization, wait times, blocked-time by cause) and a comparison chart showing the effect at a glance.

## Status

All six build phases are complete.

| Phase | Adds |
|---|---|
| ✅ 1 — Core Model | `Config`/`Case` data model, stochastic interarrival sampler, FIFO buffer + cell as SimPy processes, `run_once(config)` entry point |
| ✅ 2 — Metrics & CLI | Post-warm-up `summary()` (throughput, utilization, wait percentiles, conservation), console report, `--policy/--cv/--seed/--duration` CLI flags |
| ✅ 3 — Sequence Policy | Strict pallet-sequence service discipline with event-driven (no polling) per-seq-id waits, and blocked-time attribution to `empty` vs. `waiting_for_sequence` |
| ✅ 4 — Experiment & Chart | CV × policy × seed sweep runner and the two-panel `results/comparison.png` — the project's headline chart |
| ✅ 5 — Validation and Buffer occupancy | M/D/1 analytic validation printout and a single-run buffer-occupancy trace plot |
| ✅ 6 — Wrap-Up | Full validation re-run, code hygiene pass, and an end-to-end demo dry-run of every documented workflow |

See `tasks.md` for the full task-by-task build log and verification notes, `architecture.md` for the component design, and `claude/executions/` for phase-by-phase execution summaries.

## Quick start

```bash
cd outbound-cell-sim
pip install -r requirements.txt
python sim.py                 # single run, console summary, <1s
python experiment.py          # full sweep + results/comparison.png, ~8s
```
