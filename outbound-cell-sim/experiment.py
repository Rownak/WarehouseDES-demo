"""Outbound Cell Throughput Simulator — sweep experiment & comparison chart.

How to run
----------
1. pip install -r requirements.txt
2. python sim.py                                   # quick single run (W1)
3. python sim.py --policy fifo --cv 1.0 --seed 42   # compare policies (W2)
   python sim.py --policy sequence --cv 1.0 --seed 42
4. python experiment.py                             # full sweep + chart (W3)
   -> prints a grouped summary table and writes results/comparison.png
      and results/buffer_trace.png
"""

import os

import matplotlib.pyplot as plt
import pandas as pd

from sim import Config, run_once

CV_VALUES = [0.25, 0.5, 1.0, 1.5, 2.0]
POLICIES = ["fifo", "sequence"]
SEEDS = [1, 2, 3, 4, 5]

RESULTS_DIR = os.path.join(os.path.dirname(__file__), "results")


def sweep() -> pd.DataFrame:
    """Run policy x CV x seed grid, return one row per run as a DataFrame."""
    rows = []
    for cv in CV_VALUES:
        for policy in POLICIES:
            for seed in SEEDS:
                config = Config(arrival_cv=cv, policy=policy, seed=seed)
                summary = run_once(config)
                rows.append({"cv": cv, "policy": policy, "seed": seed, **summary})
    return pd.DataFrame(rows)


def plot_comparison(df: pd.DataFrame, path: str) -> None:
    """Two-panel figure: throughput vs CV (A) and mean wait vs CV (B), mean over seeds."""
    grouped = df.groupby(["policy", "cv"], as_index=False).mean(numeric_only=True)
    nominal = df["nominal_cases_per_hr"].iloc[0]

    fig, (ax_throughput, ax_wait) = plt.subplots(1, 2, figsize=(11, 4.5))

    for policy in POLICIES:
        subset = grouped[grouped["policy"] == policy].sort_values("cv")
        ax_throughput.plot(subset["cv"], subset["throughput_cases_per_hr"], marker="o", label=policy)
        ax_wait.plot(subset["cv"], subset["mean_wait_s"], marker="o", label=policy)

    ax_throughput.axhline(nominal, linestyle="--", color="gray", label=f"nominal ({nominal:.0f}/hr)")
    ax_throughput.set_xlabel("Arrival CV")
    ax_throughput.set_ylabel("Effective throughput (cases/hr)")
    ax_throughput.set_title("Throughput vs. arrival variability")
    ax_throughput.legend()

    ax_wait.set_xlabel("Arrival CV")
    ax_wait.set_ylabel("Mean wait (s)")
    ax_wait.set_title("Mean wait vs. arrival variability")
    ax_wait.legend()

    fig.tight_layout()
    os.makedirs(RESULTS_DIR, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def plot_buffer_trace(config: Config, path: str) -> None:
    """Single-run buffer level vs. time (F7): shows congestion rising during
    arrival bursts and draining afterward."""
    _, metrics = run_once(config, return_metrics=True)
    times = [t for t, _ in metrics.buffer_level_trace]
    levels = [level for _, level in metrics.buffer_level_trace]

    fig, ax = plt.subplots(figsize=(9, 4))
    ax.step(times, levels, where="post")
    ax.axvline(config.warmup_s, linestyle="--", color="gray", label="warm-up ends")
    ax.set_xlabel("Simulated time (s)")
    ax.set_ylabel("Buffer level (cases)")
    ax.set_title(f"Buffer occupancy trace ({config.policy}, CV={config.arrival_cv})")
    ax.legend()

    fig.tight_layout()
    os.makedirs(RESULTS_DIR, exist_ok=True)
    fig.savefig(path)
    plt.close(fig)


def main() -> None:
    df = sweep()
    summary_cols = ["throughput_cases_per_hr", "utilization", "mean_wait_s", "p95_wait_s", "rejected_count"]
    print(df.groupby(["policy", "cv"])[summary_cols].mean().round(2))

    chart_path = os.path.join(RESULTS_DIR, "comparison.png")
    plot_comparison(df, chart_path)
    print(f"\nSaved chart to {chart_path}")

    trace_path = os.path.join(RESULTS_DIR, "buffer_trace.png")
    plot_buffer_trace(Config(), trace_path)
    print(f"Saved chart to {trace_path}")


if __name__ == "__main__":
    main()
