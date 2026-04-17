import numpy as np
from scipy.optimize import minimize_scalar

BUDGET = 100
SPEED_INVESTMENT = 10  
SPEED_MULTIPLIER = 0.3


def research(x):
    return 200_000 * np.log(1 + x) / np.log(1 + 100)


def scale(x):
    return 7 * x / 100


def net_pnl(research_invest, speed_invest, speed_mult):
    scale_invest = BUDGET - speed_invest - research_invest
    if scale_invest < 0 or research_invest < 0:
        return -np.inf
    gross = research(research_invest) * scale(scale_invest) * speed_mult
    return gross - BUDGET


def optimize(speed_invest, speed_mult):
    remaining = BUDGET - speed_invest

    def neg_pnl(research_invest):
        scale_invest = remaining - research_invest
        if scale_invest < 0:
            return np.inf
        return -(research(research_invest) * scale(scale_invest) * speed_mult - BUDGET)

    result = minimize_scalar(neg_pnl, bounds=(0, remaining), method="bounded")
    best_research = result.x
    best_scale = remaining - best_research
    best_pnl = -result.fun
    return best_research, best_scale, best_pnl


if __name__ == "__main__":
    r, s, pnl = optimize(SPEED_INVESTMENT, SPEED_MULTIPLIER)
    print(f"Speed investment:    {SPEED_INVESTMENT:.2f} (multiplier: {SPEED_MULTIPLIER})")
    print(f"Research investment: {r:.2f}")
    print(f"Scale investment:    {s:.2f}")
    print(f"Research value:      {research(r):.2f}")
    print(f"Scale value:         {scale(s):.4f}")
    print(f"Gross PnL:           {research(r) * scale(s) * SPEED_MULTIPLIER:.2f}")
    print(f"Net PnL:             {pnl:.2f}")
