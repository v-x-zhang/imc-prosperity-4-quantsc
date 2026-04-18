"""
Score distribution analysis for speed bid strategy.
Uses leaderboard data to understand the competitive landscape.
"""

import pandas as pd
import matplotlib.pyplot as plt
import numpy as np

df = pd.read_csv("data/leaderboard_full.csv")

# Winsorize at 1st and 99th percentiles
low = df["score"].quantile(0.01)
high = df["score"].quantile(0.99)
df["score_w"] = df["score"].clip(lower=low, upper=high)

fig, axes = plt.subplots(2, 2, figsize=(14, 10))
fig.suptitle("Leaderboard Score Distribution (Winsorized 1%-99%)", fontsize=14)

# 1. Histogram of winsorized scores
ax = axes[0, 0]
ax.hist(df["score_w"], bins=100, edgecolor="black", alpha=0.7)
ax.set_xlabel("Score")
ax.set_ylabel("Count")
ax.set_title("Score Distribution (All Teams)")
ax.axvline(df["score_w"].median(), color="red", linestyle="--", label=f"Median: {df['score_w'].median():,.0f}")
ax.axvline(df["score_w"].mean(), color="orange", linestyle="--", label=f"Mean: {df['score_w'].mean():,.0f}")
ax.legend()

# 2. CDF of winsorized scores
ax = axes[0, 1]
sorted_scores = np.sort(df["score_w"])
cdf = np.arange(1, len(sorted_scores) + 1) / len(sorted_scores)
ax.plot(sorted_scores, cdf)
ax.set_xlabel("Score")
ax.set_ylabel("Cumulative Fraction of Teams")
ax.set_title("CDF of Scores")
ax.grid(True, alpha=0.3)

# 3. Top 500 zoom-in
ax = axes[1, 0]
top500 = df.nsmallest(500, "rank")
ax.hist(top500["score"], bins=50, edgecolor="black", alpha=0.7, color="green")
ax.set_xlabel("Score")
ax.set_ylabel("Count")
ax.set_title("Score Distribution (Top 500)")

# 4. Score vs Rank (winsorized)
ax = axes[1, 1]
ax.scatter(df["rank"], df["score_w"], s=1, alpha=0.3)
ax.set_xlabel("Rank")
ax.set_ylabel("Score")
ax.set_title("Score vs Rank")
ax.grid(True, alpha=0.3)

plt.tight_layout()
plt.savefig("data/score_distribution.png", dpi=150)
print("Saved plot to data/score_distribution.png")

# Print summary stats
print("\n=== Score Distribution Summary ===")
print(df["score"].describe())
print(f"\nTeams with score > 0: {(df['score'] > 0).sum()}")
print(f"Teams with score = 0: {(df['score'] == 0).sum()}")
print(f"Teams with score < 0: {(df['score'] < 0).sum()}")

# Percentile analysis
print("\n=== Percentile Breakdown ===")
for p in [99, 95, 90, 75, 50, 25, 10, 5, 1]:
    val = np.percentile(df["score"], 100 - p)
    print(f"Top {p:>2}% (rank ~{int(len(df) * p / 100):>5}): score >= {val:>10,.0f}")
