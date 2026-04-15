from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict
import jsonpickle

class Trader:
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 50,
        "INTARIAN_PEPPER_ROOT": 50,
    }

    def bid(self):
        return 15

    def get_mid(self, order_depth: OrderDepth) -> float:
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        if best_bid and best_ask:
            return (best_bid + best_ask) / 2
        return best_bid or best_ask or 0

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
                # Flat mean-reverting around 10000 — market make here
                theo = 10_000
            elif product == "INTARIAN_PEPPER_ROOT":
                # End-of-day theo = starting mid + 1000
                # Anchor to first observed mid, then use that + 1000 as theo all day
                key = "pepper_anchor"
                if key not in trader_state:
                    trader_state[key] = mid
                anchor = trader_state[key]
                theo = anchor + 1000  # end-of-day fair value
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

            # === 2. Passive: penny the top of book, clamped to theo ===
            best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
            best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

            if best_bid is not None and buy_room > 0:
                penny_bid = min(best_bid + 1, int(theo) - 1)
                orders.append(Order(product, penny_bid, buy_room))

            if best_ask is not None and sell_room > 0:
                penny_ask = max(best_ask - 1, int(theo) + 1)
                orders.append(Order(product, penny_ask, -sell_room))

            result[product] = orders

        traderData = jsonpickle.encode(trader_state)
        conversions = 0
        return result, conversions, traderData