from datamodel import OrderDepth, TradingState, Order
from typing import List, Dict

class Trader:
    # Position limits (check the round's wiki page for exact values)
    POSITION_LIMITS: Dict[str, int] = {
        "ASH_COATED_OSMIUM": 50,
        "INTARIAN_PEPPER_ROOT": 50,
    }

    def bid(self):
        return 15

    def get_theo(self, product: str, timestamp: int) -> float:
        if product == "ASH_COATED_OSMIUM":
            return 10000
        elif product == "INTARIAN_PEPPER_ROOT":
            # Starts at 13000 on day 1, drifts up ~1000 over the day
            return 13000 + timestamp / 1000
        return 0

    def run(self, state: TradingState):
        result: Dict[str, List[Order]] = {}

        for product in state.order_depths:
            order_depth: OrderDepth = state.order_depths[product]
            orders: List[Order] = []
            theo = self.get_theo(product, state.timestamp)
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 50)

            buy_room = limit - pos      # how many more we can buy
            sell_room = limit + pos      # how many more we can sell

            # === Penny the top of book ===
            # Bid 1 above best bid, ask 1 below best ask, but stay on our side of theo

            best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
            best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

            if best_bid is not None and buy_room > 0:
                penny_bid = best_bid + 1
                # Don't bid above theo
                penny_bid = min(penny_bid, int(theo) - 1)
                orders.append(Order(product, penny_bid, buy_room))

            if best_ask is not None and sell_room > 0:
                penny_ask = best_ask - 1
                # Don't ask below theo
                penny_ask = max(penny_ask, int(theo) + 1)
                orders.append(Order(product, penny_ask, -sell_room))

            result[product] = orders

        traderData = ""
        conversions = 0
        return result, conversions, traderData