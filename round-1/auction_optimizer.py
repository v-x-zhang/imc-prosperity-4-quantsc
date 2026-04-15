"""
Clearing Auction Optimizer (Single Book)

Given one orderbook and a fair value, finds the optimal limit order
(BUY or SELL, price, quantity) that maximizes profit.

Clearing rules:
  1. Clearing price = price that maximizes total traded volume
  2. Ties broken by choosing the higher price
  3. Allocation: price priority, then time priority
  4. Our order is LAST in time priority at any price level
"""


import heapq
from tqdm import tqdm


def find_clearing(bids, asks):
    """
    Find clearing price and volume for given bids and asks.
    Returns (clearing_price, volume) or (None, 0).
    """
    prices = sorted(set(p for p, _ in bids) | set(p for p, _ in asks))

    best_cp = None
    best_vol = 0

    for cp in prices:
        buy_vol = sum(q for p, q in bids if p >= cp)
        sell_vol = sum(q for p, q in asks if p <= cp)
        vol = min(buy_vol, sell_vol)

        if vol > best_vol or (vol == best_vol and best_cp is not None and cp > best_cp):
            best_vol = vol
            best_cp = cp

    return best_cp, best_vol


def our_fill(bids, asks, our_side, our_price, our_qty):
    """
    Compute clearing price and our filled quantity when we add our order last.
    Returns (clearing_price, our_filled_qty).
    """
    # Build combined book
    all_bids = list(bids)
    all_asks = list(asks)
    if our_side == "BUY":
        all_bids.append((our_price, our_qty))
    else:
        all_asks.append((our_price, our_qty))

    cp, vol = find_clearing(all_bids, all_asks)
    if cp is None or vol == 0:
        return None, 0

    # Check if our order participates
    if our_side == "BUY" and our_price < cp:
        return cp, 0
    if our_side == "SELL" and our_price > cp:
        return cp, 0

    total_buy = sum(q for p, q in all_bids if p >= cp)
    total_sell = sum(q for p, q in all_asks if p <= cp)
    traded = min(total_buy, total_sell)

    if our_side == "BUY":
        # Fill priority: higher price first, then time (we're last)
        remaining = traded

        # 1. Fill all bids strictly above clearing price (existing orders first at each level)
        for bp in sorted(set(p for p, _ in all_bids), reverse=True):
            if bp <= cp:
                break
            # Existing orders at this level
            for p, q in bids:
                if p == bp:
                    fill = min(q, remaining)
                    remaining -= fill
            # Our order at this level (if applicable)
            if our_price == bp:
                return cp, max(min(our_qty, remaining), 0)

        # 2. At clearing price level: existing orders first, then us
        for p, q in bids:
            if p == cp:
                fill = min(q, remaining)
                remaining -= fill

        if our_price == cp:
            return cp, max(min(our_qty, remaining), 0)

        return cp, 0

    else:  # SELL
        remaining = traded

        # 1. Fill all asks strictly below clearing price
        for ap in sorted(set(p for p, _ in all_asks)):
            if ap >= cp:
                break
            for p, q in asks:
                if p == ap:
                    fill = min(q, remaining)
                    remaining -= fill
            if our_price == ap:
                return cp, max(min(our_qty, remaining), 0)

        # 2. At clearing price level: existing orders first, then us
        for p, q in asks:
            if p == cp:
                fill = min(q, remaining)
                remaining -= fill

        if our_price == cp:
            return cp, max(min(our_qty, remaining), 0)

        return cp, 0


def calc_profit(side, cp, filled, fair_value, trading_fee=0.10):
    """
    Profit accounting for all fees.
    BUY:  buy at cp, sell to guild at fair_value (minus trading_fee)
    SELL: sell at cp, buy back from guild at fair_value (minus trading_fee)
    """
    if side == "BUY":
        return (fair_value - cp - trading_fee) * filled
    else:
        return (cp - fair_value - trading_fee) * filled


def optimize(bids, asks, fair_value, max_qty, trading_fee=0.10):
    """
    Find the optimal order to maximize profit accounting for fees.
    Returns (best, top_candidates) where top_candidates is a sorted list of top 10.
    """
    all_prices = sorted(set(p for p, _ in bids) | set(p for p, _ in asks))
    if not all_prices:
        print("Empty orderbook!")
        return None, []

    best = None
    best_profit = 0
    top_10 = []  # min-heap of (profit, side, price, qty, cp, filled)

    price_lo = min(all_prices) - 3
    price_hi = max(all_prices) + 3

    with tqdm(desc="Optimizing") as pbar:
        for side in ["BUY", "SELL"]:
            for price in range(price_lo, price_hi + 1):
                prev_filled = 0
                for qty in range(1, max_qty + 1):
                    cp, filled = our_fill(bids, asks, side, price, qty)
                    pbar.update(1)
                    if cp is None or filled == 0:
                        continue

                    # If fill didn't increase, more qty won't help
                    if filled <= prev_filled:
                        break
                    prev_filled = filled

                    profit = calc_profit(side, cp, filled, fair_value, trading_fee)

                    if profit > best_profit:
                        best_profit = profit
                        best = (side, price, qty, cp, filled, profit)

                    if profit > 0:
                        entry = (profit, side, price, qty, cp, filled)
                        if len(top_10) < 10:
                            heapq.heappush(top_10, entry)
                        elif profit > top_10[0][0]:
                            heapq.heapreplace(top_10, entry)

    top_candidates = sorted(top_10, reverse=True)
    return best, top_candidates


# ============================================================
# ENTER YOUR ORDERBOOK AND FAIR VALUE HERE
# ============================================================

FAIR_VALUE = 30      # merchant guild buy price
TRADING_FEE = 0      # fee per unit traded in auction
MAX_QTY = 100000     # maximum quantity

bids = [
    # (price, quantity),
    (30, 30000),
    (29, 5000),
    (28, 12000),
    (27, 28000),
    # (20, 43000),
    # (19, 17000),
    # (18, 6000),
    # (17, 5000),
    # (16, 10000),
    # (15, 5000),
    # (14, 10000),
    # (13, 7000),
]

asks = [
    # (price, quantity),
    (28, 40000),
    (31, 20000),
    (32, 20000),
    (33, 30000),
    # (12, 20000),
    # (13, 25000),
    # (14, 35000),
    # (15, 6000),
    # (16, 5000),
    # (18, 10000),
    # (19, 12000),
]

if __name__ == "__main__":
    print("=" * 50)
    print("ORDERBOOK")
    print("=" * 50)
    print(f"Fair value: {FAIR_VALUE}")
    print(f"Bids: {bids}")
    print(f"Asks: {asks}")

    # Baseline (no our order)
    cp0, vol0 = find_clearing(bids, asks)
    print(f"\nBaseline clearing: price={cp0}, volume={vol0}")
    print()

    # Optimize
    result, top_candidates = optimize(bids, asks, FAIR_VALUE, MAX_QTY, TRADING_FEE)

    if result:
        side, price, qty, cp, filled, profit = result
        print("=" * 50)
        print("OPTIMAL ORDER")
        print("=" * 50)
        print(f"  Side:           {side}")
        print(f"  Price:          {price}")
        print(f"  Quantity:       {qty}")
        print(f"  Clearing price: {cp}")
        print(f"  Filled:         {filled}")
        print(f"  Profit:         {profit}")
    else:
        print("No profitable order found.")

    # Show top 10 orders by profit
    print("\n" + "=" * 50)
    print("TOP 10 ORDERS BY PROFIT")
    print("=" * 50)
    print(f"{'Profit':>8}  {'Side':<5} {'Price':>6} {'Qty':>5} {'CP':>6} {'Filled':>7}")
    for profit, side, price, qty, cp, filled in top_candidates:
        print(f"{profit:>8.1f}  {side:<5} {price:>6} {qty:>5} {cp:>6} {filled:>7}")
