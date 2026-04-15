from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle

class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    # How wide to quote around theo
    SPREAD = 2

    def bid(self):
        return 15

    def get_mid(self, order_depth: OrderDepth) -> float:
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        if best_bid and best_ask:
            return (best_bid + best_ask) / 2
        return best_bid or best_ask or 0

    def get_vwap_mid(self, order_depth: OrderDepth) -> float:
        """Volume-weighted average price across all bid and ask levels."""
        total_vol = 0
        total_pv = 0
        for price, vol in order_depth.buy_orders.items():
            # buy_orders have positive volumes
            total_pv += price * vol
            total_vol += vol
        for price, vol in order_depth.sell_orders.items():
            # sell_orders have negative volumes, flip sign
            total_pv += price * (-vol)
            total_vol += (-vol)
        if total_vol > 0:
            return total_pv / total_vol
        return self.get_mid(order_depth)

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        # Restore state
        trader_state = {}
        if state.traderData:
            try:
                trader_state = jsonpickle.decode(state.traderData)
            except:
                trader_state = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 50)
            mid = self.get_mid(order_depth)

            # --- Compute theo ---
            if product == "ASH_COATED_OSMIUM":
                theo = 10_000
            elif product == "INTARIAN_PEPPER_ROOT":
                # Anchor to first observed mid, then drift +1 per 1000 timestamps
                key = "pepper_anchor"
                if key not in trader_state:
                    trader_state[key] = mid
                    trader_state["pepper_t0"] = state.timestamp
                anchor = trader_state[key]
                t0 = trader_state["pepper_t0"]
                theo = anchor + (state.timestamp - t0) * (1000 / 1_000_000)
            else:
                theo = mid

            buy_room = limit - pos
            sell_room = limit + pos

            # === 1. Aggressive: take everything priced better than theo ===

            # Buy all asks below theo
            if order_depth.sell_orders:
                for ask_price in sorted(order_depth.sell_orders.keys()):
                    if ask_price < theo and buy_room > 0:
                        ask_vol = -order_depth.sell_orders[ask_price]
                        qty = min(ask_vol, buy_room)
                        orders.append(Order(product, ask_price, qty))
                        buy_room -= qty
                    else:
                        break

            # Sell into all bids above theo
            if order_depth.buy_orders:
                for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if bid_price > theo and sell_room > 0:
                        bid_vol = order_depth.buy_orders[bid_price]
                        qty = min(bid_vol, sell_room)
                        orders.append(Order(product, bid_price, -qty))
                        sell_room -= qty
                    else:
                        break

            # === 2. Passive market making: skew sizes toward flat position ===
            # Quote tighter than the book, but skew qty to cycle inventory
            #
            # If we're long, we want to sell more than buy -> lean the ask
            # If we're short, we want to buy more than sell -> lean the bid
            # This keeps us turning over inventory instead of sitting at max position

            best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
            best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

            # Penny the book but clamp to theo
            if best_bid is not None:
                penny_bid = min(best_bid + 1, int(theo) - 1)
            else:
                penny_bid = int(theo) - 1

            if best_ask is not None:
                penny_ask = max(best_ask - 1, int(theo) + 1)
            else:
                penny_ask = int(theo) + 1

            # Skew: when long, bid less and ask more; when short, reverse
            # At pos=0, split evenly. At pos=+limit, bid 0 and ask full.
            bid_frac = (limit - pos) / (2 * limit)  # 1.0 when short limit, 0.0 when long limit
            ask_frac = (limit + pos) / (2 * limit)  # 1.0 when long limit, 0.0 when short limit

            bid_qty = min(int(buy_room * (0.5 + bid_frac)), buy_room)
            ask_qty = min(int(sell_room * (0.5 + ask_frac)), sell_room)

            if bid_qty > 0 and buy_room > 0:
                orders.append(Order(product, penny_bid, bid_qty))

            if ask_qty > 0 and sell_room > 0:
                orders.append(Order(product, penny_ask, -ask_qty))

            result[product] = orders

        traderData = jsonpickle.encode(trader_state)
        conversions = 0
        return result, conversions, traderData
