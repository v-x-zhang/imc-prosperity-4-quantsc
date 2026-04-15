import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

data_dir = os.path.join(os.path.dirname(__file__), "data")

# Load all days
dfs = []
for fname in sorted(os.listdir(data_dir)):
    if fname.startswith("prices_round_1_day_") and fname.endswith(".csv"):
        df = pd.read_csv(os.path.join(data_dir, fname), sep=";")
        dfs.append(df)

df = pd.concat(dfs, ignore_index=True)
df.sort_values(["day", "timestamp"], inplace=True)

# Drop rows with missing or zero mid_price
df = df[df["mid_price"].notna() & (df["mid_price"] > 0)].copy()

# Create a continuous time index across days
day_length = df["timestamp"].max() + 100  # gap between days
df["time"] = (df["day"] - df["day"].min()) * day_length + df["timestamp"]

products = df["product"].unique()
colors = {"ASH_COATED_OSMIUM": "tab:blue", "INTARIAN_PEPPER_ROOT": "tab:orange"}

fig, axes = plt.subplots(4, 1, figsize=(14, 14), sharex=True)

# --- 1. Mid prices ---
ax = axes[0]
for prod in products:
    sub = df[df["product"] == prod]
    ax.plot(sub["time"], sub["mid_price"], label=prod, color=colors.get(prod), alpha=0.8, linewidth=0.8)
ax.set_ylabel("Mid Price")
ax.set_title("Mid Price Over Time")
ax.legend()
ax.grid(True, alpha=0.3)

# --- 2. Bid-Ask Spread (level 1) ---
ax = axes[1]
for prod in products:
    sub = df[df["product"] == prod].copy()
    sub["spread"] = sub["ask_price_1"] - sub["bid_price_1"]
    valid = sub.dropna(subset=["spread"])
    ax.plot(valid["time"], valid["spread"], label=prod, color=colors.get(prod), alpha=0.8, linewidth=0.8)
ax.set_ylabel("Spread")
ax.set_title("Bid-Ask Spread (Level 1)")
ax.legend()
ax.grid(True, alpha=0.3)

# --- 3. Log Returns ---
ax = axes[2]
for prod in products:
    sub = df[df["product"] == prod].copy()
    sub["log_return"] = np.log(sub["mid_price"]).diff()
    valid = sub.dropna(subset=["log_return"])
    ax.plot(valid["time"], valid["log_return"], label=prod, color=colors.get(prod), alpha=0.7, linewidth=0.7)
ax.set_ylabel("Log Return")
ax.set_title("Log Returns (tick-to-tick)")
ax.legend()
ax.grid(True, alpha=0.3)

# --- 4. Cumulative Returns ---
ax = axes[3]
for prod in products:
    sub = df[df["product"] == prod].copy()
    sub["cum_return"] = sub["mid_price"] / sub["mid_price"].iloc[0] - 1
    ax.plot(sub["time"], sub["cum_return"], label=prod, color=colors.get(prod), alpha=0.8, linewidth=0.8)
ax.set_ylabel("Cumulative Return")
ax.set_title("Cumulative Returns (from first observation)")
ax.set_xlabel("Time (continuous across days)")
ax.legend()
ax.grid(True, alpha=0.3)

# Add day boundaries
for ax in axes:
    for d in df["day"].unique():
        t = (d - df["day"].min()) * day_length
        ax.axvline(t, color="gray", linestyle="--", alpha=0.4, linewidth=0.8)

plt.tight_layout()
plt.savefig(os.path.join(os.path.dirname(__file__), "round1_price_analysis.png"), dpi=150)
plt.show()
print("Saved to round1_price_analysis.png")
