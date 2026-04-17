#!/usr/bin/env python3
"""Grid search over given parameter and round."""

import subprocess
import re
import sys
import shutil
import tempfile
import os

# Config
PARAM_NAME = "EWMA_SPAN"
GRID = [100, 200, 300, 400, 500, 600, 700, 800, 900, 1000]
SOURCE_FILE = "round_1_ash_v1.py"
ROUND = "1"

# "sharpe" or "pnl"
METRIC = sys.argv[1] if len(sys.argv) > 1 else "sharpe"

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

    # Also grab per-day totals
    days = re.findall(r"Round \d+ day [^\:]+:\s*([\d,.\-]+)", output)
    day_pnls = [float(d.replace(",", "")) for d in days]

    return {"sharpe": sharpe, "pnl": pnl, "days": day_pnls, "output": output}

def patch_file(src: str, param: str, value: float) -> str:
    """Create a temp copy with the parameter patched."""
    with open(src, "r") as f:
        code = f.read()
    pattern = rf"({param}\s*=\s*)[\d.]+"
    patched = re.sub(pattern, rf"\g<1>{value}", code)
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".py", dir=os.path.dirname(src), delete=False
    )
    tmp.write(patched)
    tmp.close()
    return tmp.name

# Main
def main():
    print(f"Grid search: {PARAM_NAME} over {GRID}")
    print(f"Optimizing: {METRIC.upper()}")
    print("=" * 60)

    results = []
    src = os.path.join(os.path.dirname(os.path.abspath(__file__)), SOURCE_FILE)

    for val in GRID:
        tmp_path = patch_file(src, PARAM_NAME, val)
        try:
            r = run_backtest(tmp_path)
            metric_val = r[METRIC]
            results.append((val, metric_val, r["pnl"], r["sharpe"], r["days"]))
            metric_str = f"{metric_val:.4f}" if metric_val is not None else "N/A"
            print(f"  {PARAM_NAME}={val:<5.2f}  →  PnL={r['pnl']:>10,.0f}  Sharpe={r['sharpe'] or 'N/A':>8}  days={r['days']}")
        except Exception as e:
            print(f"  {PARAM_NAME}={val:<5.2f}  →  ERROR: {e}")
            results.append((val, None, None, None, []))
        finally:
            os.unlink(tmp_path)

    print("=" * 60)

    # Find best
    valid = [(v, m, p, s, d) for v, m, p, s, d in results if m is not None]
    if valid:
        best = max(valid, key=lambda x: x[1])
        print(f"BEST: {PARAM_NAME}={best[0]:.2f}  {METRIC.upper()}={best[1]:.4f}  PnL={best[2]:,.0f}")
    else:
        print("No valid results.")

if __name__ == "__main__":
    main()
