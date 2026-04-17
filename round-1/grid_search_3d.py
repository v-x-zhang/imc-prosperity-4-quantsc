#!/usr/bin/env python3
"""3D grid search over three parameters."""

import subprocess
import re
import sys
import tempfile
import os

# Config
PARAM_1 = "ANCHOR_WIDTH_SKEW"
GRID_1 = [0, 2, 4]

PARAM_2 = "FLATTEN_WIDTH_SKEW"
GRID_2 = [0, 2, 4]

PARAM_3 = "QUOTE_EDGE_SKEW"
GRID_3 = [0, 2, 4]

SOURCE_FILE = "round_1_ash_v2.py"
ROUND = "1"

# "sharpe" or "pnl"
METRIC = sys.argv[1] if len(sys.argv) > 1 else "pnl"

VENV_PYTHON = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "venv", "Scripts", "prosperity4btest.exe"
)


# Helpers
def run_backtest(filepath: str) -> dict:
    result = subprocess.run(
        [VENV_PYTHON, filepath, ROUND],
        capture_output=True, text=True, timeout=120,
    )
    output = result.stdout + result.stderr

    sharpe = None
    pnl = None
    m = re.search(r"sharpe_ratio:\s*([\d.\-inf]+)", output)
    if m and m.group(1) not in ("inf", "-inf", "nan"):
        sharpe = float(m.group(1))
    m = re.search(r"final_pnl:\s*([\d,.\-]+)", output)
    if m:
        pnl = float(m.group(1).replace(",", ""))

    days = re.findall(r"Round \d+ day [^\:]+:\s*([\d,.\-]+)", output)
    day_pnls = [float(d.replace(",", "")) for d in days]

    return {"sharpe": sharpe, "pnl": pnl, "days": day_pnls, "output": output}


def patch_file(src: str, params: dict[str, float]) -> str:
    """Create a temp copy of `src` with the given parameters substituted.
    Handles underscore-separated numeric literals (e.g. `5_000`).
    """
    with open(src, "r") as f:
        code = f.read()
    for param, value in params.items():
        pattern = rf"({param}\s*=\s*)[\d._]+"
        code, n = re.subn(pattern, rf"\g<1>{value}", code, count=1)
        if n == 0:
            raise RuntimeError(f"could not patch {param} in {src}")
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=os.path.dirname(src), delete=False
    )
    tmp.write(code)
    tmp.close()
    return tmp.name


# Main
def main():
    print(f"3D grid search: {PARAM_1} x {PARAM_2} x {PARAM_3}")
    print(f"  {PARAM_1}: {GRID_1}")
    print(f"  {PARAM_2}: {GRID_2}")
    print(f"  {PARAM_3}: {GRID_3}")
    print(f"Optimizing: {METRIC.upper()}")
    print("=" * 80)

    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), SOURCE_FILE)
    # results[(v1, v2, v3)] = (metric, pnl, sharpe, day_pnls)
    results: dict[tuple, tuple] = {}

    total = len(GRID_1) * len(GRID_2) * len(GRID_3)
    i = 0
    for v1 in GRID_1:
        for v2 in GRID_2:
            for v3 in GRID_3:
                i += 1
                tmp_path = patch_file(src, {PARAM_1: v1, PARAM_2: v2, PARAM_3: v3})
                try:
                    r = run_backtest(tmp_path)
                    metric_val = r[METRIC]
                    results[(v1, v2, v3)] = (metric_val, r["pnl"], r["sharpe"], r["days"])
                    days_str = "[" + ", ".join(f"{d:>8,.0f}" for d in r["days"]) + "]" if r["days"] else "[]"
                    print(
                        f"  [{i:>3}/{total}] {PARAM_1}={v1:<6} {PARAM_2}={v2:<4} {PARAM_3}={v3:<4} "
                        f"→  PnL={r['pnl'] if r['pnl'] is not None else 'N/A':>10} "
                        f"Sharpe={r['sharpe'] if r['sharpe'] is not None else 'N/A':>7}  "
                        f"days={days_str}"
                    )
                except Exception as e:
                    print(f"  [{i:>3}/{total}] {PARAM_1}={v1} {PARAM_2}={v2} {PARAM_3}={v3} → ERROR: {e}")
                    results[(v1, v2, v3)] = (None, None, None, [])
                finally:
                    os.unlink(tmp_path)

    print("=" * 80)

    # Matrix print (rows = PARAM_1, cols = PARAM_2), one slice per v3.
    def _print_matrix(title: str, cell_fn):
        print(f"\n{title}")
        header = f"{'':>10} | " + " ".join(f"{v2:>10}" for v2 in GRID_2)
        print(header)
        print("-" * len(header))
        for v1 in GRID_1:
            cells = " ".join(cell_fn(v1, v2) for v2 in GRID_2)
            print(f"{v1:>10} | {cells}")

    def _fmt(v):
        return f"{v:>10.2f}" if v is not None else f"{'N/A':>10}"

    for v3 in GRID_3:
        _print_matrix(
            f"{METRIC.upper()} matrix @ {PARAM_3}={v3}  (rows={PARAM_1}, cols={PARAM_2}):",
            lambda v1, v2, v3=v3: _fmt(results[(v1, v2, v3)][0]),
        )

    # Per-day matrices — one slice per (v3, day).
    n_days = max((len(r[3]) for r in results.values()), default=0)
    for v3 in GRID_3:
        for d in range(n_days):
            _print_matrix(
                f"Day {d} PnL @ {PARAM_3}={v3}  (rows={PARAM_1}, cols={PARAM_2}):",
                lambda v1, v2, v3=v3, d=d: _fmt(
                    results[(v1, v2, v3)][3][d] if d < len(results[(v1, v2, v3)][3]) else None
                ),
            )

    # Best
    valid = [(k, r) for k, r in results.items() if r[0] is not None]
    if valid:
        (best_v1, best_v2, best_v3), (best_m, best_p, best_s, best_d) = max(valid, key=lambda kv: kv[1][0])
        print(
            f"\nBEST: {PARAM_1}={best_v1}, {PARAM_2}={best_v2}, {PARAM_3}={best_v3}  "
            f"{METRIC.upper()}={best_m:.4f}  "
            f"PnL={best_p:,.0f}  Sharpe={best_s if best_s is not None else 'N/A'}"
        )
    else:
        print("\nNo valid results.")


if __name__ == "__main__":
    main()
