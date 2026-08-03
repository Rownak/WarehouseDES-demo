# Features — Outbound Cell Throughput Simulator

This document lists what to implement, in priority order, and the workflows a user runs. It complements `project_summary.md` (why) and `architecture.md` (how). Keep everything minimal — this is a one-day demo.

---

## 1. Feature List

Features are ordered by build priority. F1–F5 are required; F6–F7 are nice-to-have if time remains. Anything not listed here is out of scope (see Future Enhancements in `project_summary.md`).

### F1 — Core simulation run (required)
A single simulation of one outbound cell fed by stochastic case arrivals.

- Fixed cell service rate: 1,350 cases/hr (deterministic service time ~2.667 s).
- Stochastic case arrivals: exponential or lognormal inter-arrival times with configurable mean and coefficient of variation (CV).
- Finite staging buffer (default capacity 20); arrivals to a full buffer are counted as rejects.
- Configurable simulation duration (default 4 simulated hours) and warm-up window (default 30 min, excluded from stats).
- Seeded RNG: same seed + same config → identical results.

**Done when:** `python sim.py` runs a default simulation and prints a summary in under a few seconds.

### F2 — FIFO service policy (required)
The cell serves whichever case has waited longest.

**Done when:** with CV→0 and matched arrival rate, utilization ≈ 100% and throughput ≈ 1,350 cases/hr.

### F3 — Strict-sequence service policy (required)
Each case carries a pallet sequence ID (0, 1, 2, …). The cell may only serve the next ID in order; if that case hasn't arrived, the cell blocks — even if other cases are waiting in the buffer.

- Blocked time is recorded with its cause: `empty` (no cases at all) vs `waiting_for_sequence` (cases present, but not the right one).
- Policy is selected by a single config field: `policy = "fifo" | "sequence"`.

**Done when:** for any CV > 0, sequence throughput ≤ FIFO throughput and `waiting_for_sequence` time > 0.

### F4 — Metrics summary (required)
After each run, print a console summary (post-warm-up):

- Effective throughput (cases/hr) vs the nominal 1,350
- Cell utilization (%)
- Mean and p95 case wait time (s)
- Starved time split by cause (% of observed time)
- Mean buffer level and reject count
- Cases generated / completed / in-system (conservation check)

**Done when:** the summary reads clearly in one screen and the conservation check balances.

### F5 — Policy comparison sweep + chart (required)
One command that sweeps arrival CV ∈ {0.25, 0.5, 1.0, 1.5, 2.0} for both policies (5 seeds each), then produces:

- A two-panel matplotlib figure saved to `results/comparison.png`:
  - Panel A: effective throughput vs CV, one line per policy, dashed line at 1,350.
  - Panel B: mean wait time vs CV, one line per policy.
- A console table of the sweep results (pandas DataFrame print).

**Done when:** the chart visibly shows the sequence policy falling below FIFO as CV grows — this is the headline result of the demo.

### F6 — M/D/1 validation printout (nice-to-have)
For the exponential/FIFO case, print the analytic M/D/1 mean wait alongside the simulated mean wait so a reviewer can see the model is calibrated.

**Done when:** simulated and analytic waits agree within a few percent at moderate utilization.

### F7 — Buffer occupancy trace plot (nice-to-have)
A simple line plot of buffer level over time for a single run, saved to `results/buffer_trace.png`. Useful for eyeballing congestion dynamics.

---

## 2. User Workflows

The "user" is someone reviewing or experimenting with the demo (interviewer, teammate, or the author). All workflows are command-line only — no UI.

### W1 — Quick run (default settings)
1. `pip install -r requirements.txt`
2. `python sim.py`
3. Read the console summary for the default config (FIFO, CV=1.0).

Expected time: under 10 seconds. This is the smoke test.

### W2 — Compare policies at one setting
1. `python sim.py --policy fifo --cv 1.0 --seed 42`
2. `python sim.py --policy sequence --cv 1.0 --seed 42`
3. Compare the two summaries side by side — same arrivals, different policy, visible throughput gap and `waiting_for_sequence` time.

CLI flags map 1:1 to `Config` fields; only `--policy`, `--cv`, `--seed`, and `--duration` need flags. Everything else is edited in code.

### W3 — Full experiment (the demo's main artifact)
1. `python experiment.py`
2. Wait for the sweep (~10 runs × 5 seeds; should finish in well under a minute).
3. Open `results/comparison.png` and read the console table.
4. Talking point: "At matched average capacity, sequencing turns arrival variability into blocked-cell time — delay is a sequencing failure, not just slowness."

### W4 — Reproduce / verify
1. Re-run any command with the same `--seed` and confirm identical output.
2. Run the validation checks (architecture.md §6): zero-variance sanity, M/D/1 comparison, sequence-dominance, conservation.

### W5 — Tweak and explore (optional)
1. Edit `Config` defaults in `sim.py` (e.g., buffer capacity 5 vs 50, or arrival mean 5% above capacity).
2. Re-run W1/W3 and observe the effect.

---

## 3. Explicit Non-Features (do not build)

To protect the one-day scope, the agent must **not** implement:

- Multiple outbound cells, dispatchers, or load balancing
- Robot travel/routing models, lifts, or any spatial structure
- Slotting/placement logic
- Animation, dashboards, or any GUI
- Config files (YAML/JSON), logging frameworks, databases
- Abstract policy class hierarchies or plugin systems
- Parallel/distributed execution of replications

These are documented as Future Enhancements in `project_summary.md` and are talking points, not code.
