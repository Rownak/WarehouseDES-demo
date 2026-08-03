# Architecture — Outbound Cell Throughput Simulator

This document defines the components, data flow, technology choices, and design principles for the simulator described in `project_summary.md`. A coding agent implementing this project should follow this document to keep the codebase small, consistent, and extensible.

---

## 1. Scope and Constraints

- **Single-day build.** Target ~100–150 lines of core simulation code plus a small plotting/sweep script. Prefer simplicity over generality.
- **Single process, single file is acceptable** for the core model; a two-file layout (model + experiment runner) is the maximum for v1.
- **No external services, databases, or config files.** All parameters are Python constants or dataclass fields at the top of the code.
- **Deterministic reproducibility.** Every run accepts a random seed; identical seed + parameters must produce identical results.

---

## 2. Major Components

### 2.1 `Config` (dataclass)
Central parameter object passed to everything. Fields:

| Field | Type | Default | Meaning |
|---|---|---|---|
| `cell_rate_cases_per_hr` | float | 1350 | Fixed palletizing rate of the outbound cell |
| `service_time_s` | float | derived | `3600 / cell_rate_cases_per_hr` (~2.667 s) |
| `mean_interarrival_s` | float | 2.667 | Average case arrival interval (matched to capacity by default) |
| `arrival_cv` | float | 1.0 | Coefficient of variation of inter-arrival times |
| `arrival_dist` | str | `"lognormal"` | `"exponential"` or `"lognormal"` |
| `buffer_capacity` | int | 20 | Max cases staged in front of the cell |
| `policy` | str | `"fifo"` | `"fifo"` or `"sequence"` |
| `sim_duration_s` | float | 4 * 3600 | Simulated time (4 hours default) |
| `warmup_s` | float | 1800 | Metrics before this time are discarded |
| `seed` | int | 42 | RNG seed |

Derived values are computed in `__post_init__`. Never hardcode numbers elsewhere.

### 2.2 `Case` (dataclass)
The entity flowing through the system. Fields: `seq_id: int` (pallet sequence order, assigned at creation in increasing order), `created_t: float`, `arrived_t: float`, `service_start_t: float`, `service_end_t: float`. Timestamps are filled in as events occur; wait time and flow time are computed from them, not stored.

### 2.3 `CaseGenerator` (SimPy process)
- Creates cases with `seq_id = 0, 1, 2, ...` in order.
- For each case, samples a travel delay from the configured inter-arrival distribution, then delivers the case to the buffer.
- Model arrivals as a renewal process: sample the gap between arrivals directly. (Do not model pick + route separately in v1 — that is a future enhancement.)
- If the buffer is full on arrival, record a `buffer_reject` event and drop the case. Dropping is a simplification; count it so the result is visible.

### 2.4 `Buffer`
- For **FIFO**: a `simpy.Store` with `capacity = buffer_capacity`.
- For **sequence** policy: a plain dict `{seq_id: Case}` guarded by capacity checks, because the cell must retrieve a *specific* case, not the oldest. Do not force `simpy.Store` here — retrieval by key is the natural structure.
- Expose one interface used by the cell: `get_next(expected_seq_id) -> Case | None` (sequence mode) and `get_any() -> Case` (FIFO mode, blocking via Store).

### 2.5 `OutboundCell` (SimPy process)
The single server. Loop:

1. Determine the case to serve:
   - **FIFO:** block on `store.get()`.
   - **Sequence:** if `buffer[next_seq_id]` exists, take it; otherwise wait until it arrives. Implement the wait as a per-seq-id `simpy.Event` that the buffer triggers on insertion — do **not** poll with `env.timeout` loops.
2. Record `service_start_t`; if the cell was idle waiting, record the blocked/starved interval and its cause (`empty` vs `waiting_for_sequence`).
3. `yield env.timeout(service_time_s)` — service time is deterministic.
4. Record `service_end_t`, hand the case to `Metrics`, increment `next_seq_id` (sequence mode).

### 2.6 `Metrics`
Plain Python class with lists; no pandas inside the sim loop.

- `completed: list[Case]`
- `blocked_intervals: list[(start, end, cause)]`
- `buffer_level_trace: list[(t, level)]` — appended on every insert/remove
- `rejected_count: int`

Post-run, a `summary()` method computes (excluding warm-up): effective throughput (cases/hr), utilization (busy time / observed time), mean and p95 wait time, mean buffer level, starved fraction of time split by cause, and reject count. Returns a flat dict so the sweep runner can build a DataFrame from it.

### 2.7 `ExperimentRunner` (separate script or `__main__` section)
- `run_once(config) -> dict`: builds env, wires components, runs, returns `Metrics.summary()`.
- `sweep()`: iterates over `arrival_cv ∈ {0.25, 0.5, 1.0, 1.5, 2.0}` × `policy ∈ {fifo, sequence}`, N=5 replications per point with different seeds, collects results into a pandas DataFrame.
- Plotting: matplotlib, two panels — (a) effective throughput vs. arrival CV, one line per policy, with the 1,350 nominal rate as a dashed reference line; (b) mean wait time vs. arrival CV. Save to `results/comparison.png` and print the summary table.

---

## 3. Data Flow

```
Config
  │
  ▼
CaseGenerator ──(Case, stochastic interarrival)──► Buffer ──► OutboundCell
      │                                              │              │
      │  reject if full ──────► Metrics ◄── level trace             │
      │                            ▲                                │
      └────────────────────────────┴──── completed cases, blocked ──┘
                                   │
                                   ▼
                            summary() dict
                                   │
                                   ▼
                  ExperimentRunner → DataFrame → plot + console table
```

One-directional flow: cases move generator → buffer → cell; all components write to a single shared `Metrics` instance; nothing reads metrics during the run. The sweep layer treats `run_once` as a pure function of `Config`.

---

## 4. Technology Choices

| Concern | Choice | Rationale |
|---|---|---|
| Simulation engine | **SimPy** (>=4) | Standard, lightweight DES; matches job description |
| Language | Python 3.10+ | Dataclasses, type hints, match statements optional |
| Randomness | `numpy.random.Generator` via `default_rng(seed)` | One generator per run, passed explicitly — never use global `np.random` or `random` |
| Post-processing | pandas | Only outside the sim loop, for sweep aggregation |
| Plotting | matplotlib | No seaborn/plotly; keep dependencies minimal |
| Testing | A few asserts / one pytest file (optional) | Sanity checks: zero-variance arrivals at matched rate → ~100% utilization, ~1350 throughput |
| Packaging | None — flat scripts + `requirements.txt` | `simpy`, `numpy`, `pandas`, `matplotlib` |

Suggested layout:

```
outbound-cell-sim/
├── sim.py            # Config, Case, generator, buffer, cell, metrics, run_once
├── experiment.py     # sweep, plotting, console report
├── requirements.txt
├── project_summary.md
├── architecture.md
└── results/          # generated, gitignored
```

---

## 5. Design Principles

1. **Config in, dict out.** `run_once(Config) -> dict` is the only entry point to the model. No globals, no module-level state; this keeps replications and sweeps trivially parallel-safe and testable.
2. **Deterministic given a seed.** All stochasticity flows from one `numpy` Generator created from `config.seed`. This is non-negotiable for validation and debugging.
3. **Events, not polling.** Waiting for a specific sequence ID uses SimPy events triggered on buffer insertion. Busy-wait loops with small timeouts are forbidden — they distort timing and waste events.
4. **Record raw, compute late.** The sim records timestamps and intervals; all statistics (waits, utilization, percentiles) are derived afterward in `summary()`. Never accumulate running averages inside processes.
5. **Warm-up exclusion.** All reported statistics exclude the warm-up window so results reflect steady-state behavior, not the empty-system transient.
6. **Policy as a switch, not a hierarchy.** FIFO vs. sequence is an `if` on `config.policy` inside the cell/buffer. Do not build an abstract policy class framework for two policies — that's future work if more policies appear.
7. **Name blocked time by cause.** Distinguish "buffer empty" from "waiting for the next sequence ID while other cases sit in the buffer." The second cause is the headline insight of the project; the metrics must make it directly visible.
8. **Units are seconds and cases.** All simulation time in seconds; convert to hours only in reporting. Comment units on every rate/time field.
9. **Extensibility through the same seams.** Future enhancements (multiple cells, lift resources, travel models) plug in by replacing `CaseGenerator` with a richer upstream process or adding resources between generator and buffer — the `Buffer → Cell → Metrics` chain and `run_once` contract stay stable.
10. **Small over clever.** If a feature adds more than ~20 lines to v1, it belongs in Future Enhancements.

---

## 6. Validation Checks (build these first)

- **Deterministic sanity:** `arrival_cv → 0` at matched rate, FIFO → utilization ≈ 1.0, throughput ≈ 1350, near-zero waits.
- **M/D/1 comparison:** exponential arrivals (CV=1), FIFO → mean wait should be close to the analytic M/D/1 formula `Wq = ρ·s / (2(1−ρ))`. Report both in the console.
- **Sequence dominance:** for any CV > 0, sequence-policy throughput ≤ FIFO throughput, and `waiting_for_sequence` starved time > 0. If not, there is a bug.
- **Conservation:** cases generated = completed + rejected + in-system at end.
