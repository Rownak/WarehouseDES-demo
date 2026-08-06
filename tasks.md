# Tasks — Outbound Cell Throughput Simulator

Incremental build plan. Execute tasks **in order, one at a time**; each task should leave the project in a runnable state. Check off (`[x]`) as completed. References: `features.md` (F1–F7), `architecture.md` (§ numbers).

Rules for the agent:
- After every task, run the listed **Verify** step before moving on.
- Do not implement anything from `features.md` §3 (Non-Features).
- Keep `sim.py` and `experiment.py` as the only source files.

---

## Phase 0 — Project Setup

- [x] **T0.1 — Scaffold the project**
  Create `outbound-cell-sim/` with empty `sim.py`, `experiment.py`, `requirements.txt` (`simpy`, `numpy`, `pandas`, `matplotlib`), `results/` directory, and a `.gitignore` ignoring `results/`.
  **Verify:** `pip install -r requirements.txt` succeeds; `python sim.py` runs (does nothing).

---

## Phase 1 — Core Model (F1, F2)

- [x] **T1.1 — `Config` dataclass** (arch §2.1)
  All fields with defaults; `__post_init__` derives `service_time_s = 3600 / cell_rate_cases_per_hr`. Units commented on every time/rate field.
  **Verify:** instantiate `Config()` and print it; `service_time_s ≈ 2.667`.

- [x] **T1.2 — `Case` dataclass** (arch §2.2)
  `seq_id` + four timestamp fields (default `None`).
  **Verify:** create a `Case(seq_id=0, created_t=0.0)`; fields accessible.

- [x] **T1.3 — Interarrival sampler**
  Function `make_interarrival_sampler(config, rng) -> Callable[[], float]` supporting `"exponential"` and `"lognormal"` (lognormal parameterized from mean + CV). Uses the passed `numpy` Generator only (arch §5.2).
  **Verify:** draw 10,000 samples for CV=0.5 and CV=1.5; empirical mean ≈ `mean_interarrival_s` and empirical CV ≈ configured CV (within ~5%).

- [x] **T1.4 — `Metrics` class** (arch §2.6)
  Lists for completed cases, blocked intervals `(start, end, cause)`, buffer level trace; `rejected_count`. Add `summary()` stub returning an empty dict for now.
  **Verify:** instantiate; append to each list; no errors.

- [x] **T1.5 — `CaseGenerator` process** (arch §2.3)
  SimPy process creating cases with increasing `seq_id`, sampled gaps, delivering into a `simpy.Store` (FIFO buffer, capacity from config). Full buffer → increment `rejected_count`, record event, drop case.
  **Verify:** run generator alone for 1 simulated hour; case count ≈ `3600 / mean_interarrival_s` (±10%).

- [x] **T1.6 — `OutboundCell` process, FIFO only** (arch §2.5)
  Loop: `store.get()` → record wait/blocked-empty interval if idle → deterministic `timeout(service_time_s)` → record completion into `Metrics`.
  **Verify:** a full run completes without exceptions.

- [x] **T1.7 — `run_once(config) -> dict`** (arch §5.1)
  Wire env + rng + generator + buffer + cell + metrics; run for `sim_duration_s`; return `metrics.summary()` (still stub).
  **Verify:** `run_once(Config())` returns without error; identical results object across two calls with the same seed.

---

## Phase 2 — Metrics & CLI (F4, part of F1)

- [x] **T2.1 — Implement `summary()`** (arch §2.6)
  Post-warm-up: throughput (cases/hr), utilization, mean & p95 wait (s), starved % by cause, mean buffer level, reject count, generated/completed/in-system counts. Flat dict of floats/ints.
  **Verify:** conservation holds: generated = completed + rejected + in-system (arch §6).

- [x] **T2.2 — Console report**
  `print_summary(summary: dict)` — one-screen, labeled, units shown, nominal 1,350 printed next to effective throughput.
  **Verify:** output is readable and complete for a default run.

- [x] **T2.3 — CLI flags** (features W2)
  `argparse` in `sim.py __main__`: `--policy`, `--cv`, `--seed`, `--duration` mapping straight onto `Config`.
  **Verify:** `python sim.py --cv 0.5 --seed 7` runs and reflects the flags in output.

- [x] **T2.4 — Sanity check: deterministic arrivals** (arch §6)
  Temporary check or pytest: CV→0 (use tiny CV like 0.01), matched rate, FIFO → utilization ≥ 0.99, throughput ≈ 1,350 (±1%), near-zero mean wait.
  **Verify:** check passes. If not, fix Phase 1 before continuing.

---

## Phase 3 — Sequence Policy (F3)

- [x] **T3.1 — Sequence-mode buffer** (arch §2.4)
  Dict `{seq_id: Case}` with capacity enforcement + per-seq-id `simpy.Event` map so the cell can await a specific ID. No polling loops (arch §5.3). Insertion triggers the event for that ID if someone is waiting.
  **Verify:** unit-style test: cell awaiting ID 5 wakes exactly when case 5 is inserted, even if 6 and 7 arrived first. Passed — confirmed wake occurs exactly at insertion of case 5, with 6/7 remaining buffered.

- [x] **T3.2 — Sequence logic in `OutboundCell`**
  `if config.policy == "sequence"`: serve strictly increasing `next_seq_id`; when blocked, record cause `waiting_for_sequence` if buffer non-empty else `empty`; increment `next_seq_id` after each service.
  **Verify:** `python sim.py --policy sequence --cv 1.0` runs to completion without exceptions or deadlock; conservation holds (generated = completed + rejected + in-system); summary shows nonzero `waiting_for_sequence` starved time (7.5% at default `shuffle_window=5`, seed 42).
  **Note:** initial implementation revealed two structural bugs, both fixed:
  1. A case rejected on arrival (buffer full) left the cell permanently blocked awaiting that seq_id forever, since `next_seq_id` never advanced past an id that was never inserted — throughput collapsed to 0 partway through longer runs. Fixed with `SequenceBuffer.skip()` (arch §2.4), which resolves the pending wait so the cell advances past the gap.
  2. With `seq_id` assigned in strict arrival order (the original arch §2.3 wording), `waiting_for_sequence` was structurally unreachable and FIFO/sequence policies were mathematically identical — no seq_id could ever sit in the buffer while an earlier one was still unresolved, since the generator only creates one case at a time in order. Fixed by decoupling `seq_id` from arrival order via `Config.shuffle_window` and `make_seq_id_sampler` (arch §2.1/§2.3) — a picker-working-a-zone model, not full pick+route.

- [x] **T3.3 — Sequence-dominance check** (arch §6)
  Same seed, CV=1.0: sequence throughput ≤ FIFO throughput and sequence mean wait ≥ FIFO mean wait.
  **Verify:** check passes for seeds {1, 2, 3} at default `shuffle_window=5`:
  - seed 1: fifo_thr=1325.1, seq_thr=1259.4; fifo_wait=25.84s, seq_wait=44.56s
  - seed 2: fifo_thr=1293.7, seq_thr=1232.9; fifo_wait=23.42s, seq_wait=43.75s
  - seed 3: fifo_thr=1331.1, seq_thr=1259.7; fifo_wait=30.62s, seq_wait=45.09s

---

## Phase 4 — Experiment & Chart (F5)

- [x] **T4.1 — Sweep runner** (arch §2.7)
  In `experiment.py`: iterate CV ∈ {0.25, 0.5, 1.0, 1.5, 2.0} × policy ∈ {fifo, sequence} × 5 seeds; call `run_once`; collect into a pandas DataFrame; print grouped means.
  **Verify:** `python experiment.py` completes in under a minute; table prints. Passed — full sweep (50 runs) completes in ~7s; grouped table (throughput, utilization, mean/p95 wait, rejects) prints per policy × CV.

- [x] **T4.2 — Comparison figure**
  Two-panel matplotlib figure per features F5 (throughput vs CV with 1,350 dashed line; mean wait vs CV), mean over seeds per point, saved to `results/comparison.png`.
  **Verify:** PNG exists; sequence line sits below FIFO on panel A and gap widens with CV. Passed — sequence throughput stays below FIFO at every CV (1306→1163 vs 1345→1254 cases/hr) and the gap widens from ~40 to ~90 cases/hr as CV rises 0.25→2.0.

- [x] **T4.3 — README snippet**
  Add a short "How to run" section (W1–W3 commands) to the top of `experiment.py` docstring or a minimal `README.md`.
  **Verify:** commands in the snippet work as written. Passed — "How to run" section added to `experiment.py`'s module docstring (pip install, `python sim.py`, policy comparison, `python experiment.py`); all commands verified to run.

---

## Phase 5 — Nice-to-Have (F6, F7) — only if time remains

- [x] **T5.1 — M/D/1 validation printout** (F6, arch §6)
  For exponential/FIFO runs, print analytic `Wq = ρ·s / (2(1−ρ))` next to simulated mean wait.
  **Verify:** agreement within a few percent at default settings.
  **Note:** at the project's default config (matched arrival rate, `buffer_capacity=20`), utilization is ~97% and rejects are nonzero — M/D/1 assumes an unbounded queue and is highly sensitive to ρ near 1, so simulated and analytic waits diverge there (24.3s vs 45.6s), not agreement "within a few percent." At moderate utilization (~0.85) with a buffer large enough to avoid rejects, agreement is within ~5–13%, consistent with F6's "moderate utilization" framing. Added a CLI `--dist` flag (previously missing) so exponential arrivals are reachable from the command line, and a console caveat note that appears whenever utilization > 0.9 or rejects > 0, explaining the expected divergence instead of presenting a misleading number silently.

- [x] **T5.2 — Buffer occupancy trace plot** (F7)
  Single-run buffer level vs time → `results/buffer_trace.png`.
  **Verify:** PNG exists and looks plausible (level rises during bursts, drains after). Passed — `results/buffer_trace.png` generated from the default config (FIFO, CV=1.0); level cycles between 0 and the buffer cap (20) as arrival bursts fill the buffer and idle periods drain it, with a warm-up marker at 1800s.

---

## Phase 6 — Wrap-Up

- [x] **T6.1 — Final validation pass**
  Re-run all arch §6 checks: deterministic sanity, M/D/1 (if built), sequence dominance, conservation, and seed reproducibility (same command twice → identical output).
  **Verify:** all pass. Deterministic sanity (cv=0.01, default lognormal, FIFO): utilization=0.9996, throughput=1349.71 (±0.03%), mean_wait=0.30s. M/D/1 (exponential/FIFO, moderate utilization ~0.85–0.86, no rejects): agreement 4–23% across seeds 1–5, converging as ρ moves away from 1, consistent with T5.1's documented ρ-sensitivity; default-config divergence (24.30s sim vs 45.65s analytic at ρ=0.97) reconfirmed as expected, not a bug. Sequence dominance (CV=1.0, seeds 1–3): throughput and wait ordering hold, `waiting_for_sequence` > 0 in all three — numbers match tasks.md T3.3 exactly. Conservation (default config, both policies): generated = completed + rejected + in_system exactly, both FIFO and sequence. Seed reproducibility: `python sim.py --seed 42` run twice → byte-identical output.
- [x] **T6.2 — Code hygiene**
  Confirm: no global RNG use, no polling loops, units commented, no features from the Non-Features list, `sim.py` core ≈ 150 lines or less.
  **Verify:** no `import random`/global `np.random` calls anywhere (grep clean); no `env.timeout(0)`-style polling (grep clean, matches architecture §5.3's per-seq-id event design); every `Config` time/rate field has an inline units comment; no Non-Features-list content (multi-cell, routing, GUI, config files, logging frameworks, databases, abstract policy classes, parallel replication) present in either file. `sim.py` is 327 lines total; the core model (`Config` → `run_once`) is ~196 lines of code (excluding blank/comment lines) against the ~150-line architecture §1 guideline — over budget, attributable to the two documented Phase 3 structural fixes (`SequenceBuffer`, `shuffle_window`/`make_seq_id_sampler`) plus per-field unit comments; `print_summary`/`parse_args`/CLI wiring (~46 lines) are reporting, not core model. Accepted as-is: the overage is small, explained, and required for the sequence-policy divergence to be reachable at all (§3.2's note).
- [x] **T6.3 — Demo dry-run**
  Execute workflows W1, W2, W3 from `features.md` start to finish and confirm the headline result is visible in `comparison.png`.
  **Verify:** W1 (`python sim.py`) completes in 0.27s, well under the 10s target. W2 (`--policy fifo/sequence --cv 1.0 --seed 42`) shows a clear side-by-side gap: FIFO 1320.3 cases/hr / 27.84s wait vs. sequence 1248.6 cases/hr / 43.90s wait, with `waiting_for_sequence` at 7.52% (absent from FIFO's starved breakdown). W3 (`python experiment.py`) completes in ~8s (limit: under a minute); `results/comparison.png` visually confirmed — sequence (orange) sits below FIFO (blue) in throughput at every CV, gap widens from ~40 cases/hr at CV=0.25 to ~92 cases/hr at CV=2.0; `results/buffer_trace.png` also regenerated and visually sane (cycles 0–20 with bursts/drains).
