# Tasks — Outbound Cell Throughput Simulator

Incremental build plan. Execute tasks **in order, one at a time**; each task should leave the project in a runnable state. Check off (`[x]`) as completed. References: `features.md` (F1–F7), `architecture.md` (§ numbers).

Rules for the agent:
- After every task, run the listed **Verify** step before moving on.
- Do not implement anything from `features.md` §3 (Non-Features).
- Keep `sim.py` and `experiment.py` as the only source files.

---

## Phase 0 — Project Setup

- [ ] **T0.1 — Scaffold the project**
  Create `outbound-cell-sim/` with empty `sim.py`, `experiment.py`, `requirements.txt` (`simpy`, `numpy`, `pandas`, `matplotlib`), `results/` directory, and a `.gitignore` ignoring `results/`.
  **Verify:** `pip install -r requirements.txt` succeeds; `python sim.py` runs (does nothing).

---

## Phase 1 — Core Model (F1, F2)

- [ ] **T1.1 — `Config` dataclass** (arch §2.1)
  All fields with defaults; `__post_init__` derives `service_time_s = 3600 / cell_rate_cases_per_hr`. Units commented on every time/rate field.
  **Verify:** instantiate `Config()` and print it; `service_time_s ≈ 2.667`.

- [ ] **T1.2 — `Case` dataclass** (arch §2.2)
  `seq_id` + four timestamp fields (default `None`).
  **Verify:** create a `Case(seq_id=0, created_t=0.0)`; fields accessible.

- [ ] **T1.3 — Interarrival sampler**
  Function `make_interarrival_sampler(config, rng) -> Callable[[], float]` supporting `"exponential"` and `"lognormal"` (lognormal parameterized from mean + CV). Uses the passed `numpy` Generator only (arch §5.2).
  **Verify:** draw 10,000 samples for CV=0.5 and CV=1.5; empirical mean ≈ `mean_interarrival_s` and empirical CV ≈ configured CV (within ~5%).

- [ ] **T1.4 — `Metrics` class** (arch §2.6)
  Lists for completed cases, blocked intervals `(start, end, cause)`, buffer level trace; `rejected_count`. Add `summary()` stub returning an empty dict for now.
  **Verify:** instantiate; append to each list; no errors.

- [ ] **T1.5 — `CaseGenerator` process** (arch §2.3)
  SimPy process creating cases with increasing `seq_id`, sampled gaps, delivering into a `simpy.Store` (FIFO buffer, capacity from config). Full buffer → increment `rejected_count`, record event, drop case.
  **Verify:** run generator alone for 1 simulated hour; case count ≈ `3600 / mean_interarrival_s` (±10%).

- [ ] **T1.6 — `OutboundCell` process, FIFO only** (arch §2.5)
  Loop: `store.get()` → record wait/blocked-empty interval if idle → deterministic `timeout(service_time_s)` → record completion into `Metrics`.
  **Verify:** a full run completes without exceptions.

- [ ] **T1.7 — `run_once(config) -> dict`** (arch §5.1)
  Wire env + rng + generator + buffer + cell + metrics; run for `sim_duration_s`; return `metrics.summary()` (still stub).
  **Verify:** `run_once(Config())` returns without error; identical results object across two calls with the same seed.

---

## Phase 2 — Metrics & CLI (F4, part of F1)

- [ ] **T2.1 — Implement `summary()`** (arch §2.6)
  Post-warm-up: throughput (cases/hr), utilization, mean & p95 wait (s), starved % by cause, mean buffer level, reject count, generated/completed/in-system counts. Flat dict of floats/ints.
  **Verify:** conservation holds: generated = completed + rejected + in-system (arch §6).

- [ ] **T2.2 — Console report**
  `print_summary(summary: dict)` — one-screen, labeled, units shown, nominal 1,350 printed next to effective throughput.
  **Verify:** output is readable and complete for a default run.

- [ ] **T2.3 — CLI flags** (features W2)
  `argparse` in `sim.py __main__`: `--policy`, `--cv`, `--seed`, `--duration` mapping straight onto `Config`.
  **Verify:** `python sim.py --cv 0.5 --seed 7` runs and reflects the flags in output.

- [ ] **T2.4 — Sanity check: deterministic arrivals** (arch §6)
  Temporary check or pytest: CV→0 (use tiny CV like 0.01), matched rate, FIFO → utilization ≥ 0.99, throughput ≈ 1,350 (±1%), near-zero mean wait.
  **Verify:** check passes. If not, fix Phase 1 before continuing.

---

## Phase 3 — Sequence Policy (F3)

- [ ] **T3.1 — Sequence-mode buffer** (arch §2.4)
  Dict `{seq_id: Case}` with capacity enforcement + per-seq-id `simpy.Event` map so the cell can await a specific ID. No polling loops (arch §5.3). Insertion triggers the event for that ID if someone is waiting.
  **Verify:** unit-style test: cell awaiting ID 5 wakes exactly when case 5 is inserted, even if 6 and 7 arrived first.

- [ ] **T3.2 — Sequence logic in `OutboundCell`**
  `if config.policy == "sequence"`: serve strictly increasing `next_seq_id`; when blocked, record cause `waiting_for_sequence` if buffer non-empty else `empty`; increment `next_seq_id` after each service.
  **Verify:** `python sim.py --policy sequence --cv 1.0` runs; summary shows nonzero `waiting_for_sequence` time.

- [ ] **T3.3 — Sequence-dominance check** (arch §6)
  Same seed, CV=1.0: sequence throughput ≤ FIFO throughput and sequence mean wait ≥ FIFO mean wait.
  **Verify:** check passes for seeds {1, 2, 3}.

---

## Phase 4 — Experiment & Chart (F5)

- [ ] **T4.1 — Sweep runner** (arch §2.7)
  In `experiment.py`: iterate CV ∈ {0.25, 0.5, 1.0, 1.5, 2.0} × policy ∈ {fifo, sequence} × 5 seeds; call `run_once`; collect into a pandas DataFrame; print grouped means.
  **Verify:** `python experiment.py` completes in under a minute; table prints.

- [ ] **T4.2 — Comparison figure**
  Two-panel matplotlib figure per features F5 (throughput vs CV with 1,350 dashed line; mean wait vs CV), mean over seeds per point, saved to `results/comparison.png`.
  **Verify:** PNG exists; sequence line sits below FIFO on panel A and gap widens with CV.

- [ ] **T4.3 — README snippet**
  Add a short "How to run" section (W1–W3 commands) to the top of `experiment.py` docstring or a minimal `README.md`.
  **Verify:** commands in the snippet work as written.

---

## Phase 5 — Nice-to-Have (F6, F7) — only if time remains

- [ ] **T5.1 — M/D/1 validation printout** (F6, arch §6)
  For exponential/FIFO runs, print analytic `Wq = ρ·s / (2(1−ρ))` next to simulated mean wait.
  **Verify:** agreement within a few percent at default settings.

- [ ] **T5.2 — Buffer occupancy trace plot** (F7)
  Single-run buffer level vs time → `results/buffer_trace.png`.
  **Verify:** PNG exists and looks plausible (level rises during bursts, drains after).

---

## Phase 6 — Wrap-Up

- [ ] **T6.1 — Final validation pass**
  Re-run all arch §6 checks: deterministic sanity, M/D/1 (if built), sequence dominance, conservation, and seed reproducibility (same command twice → identical output).
- [ ] **T6.2 — Code hygiene**
  Confirm: no global RNG use, no polling loops, units commented, no features from the Non-Features list, `sim.py` core ≈ 150 lines or less.
- [ ] **T6.3 — Demo dry-run**
  Execute workflows W1, W2, W3 from `features.md` start to finish and confirm the headline result is visible in `comparison.png`.
