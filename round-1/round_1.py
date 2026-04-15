import json
from typing import Any
from datamodel import Listing, Observation, Order, OrderDepth, ProsperityEncoder, Symbol, Trade, TradingState


class Logger:
    def __init__(self) -> None:
        self.logs = ""
        self.max_log_length = 3750

    def print(self, *objects: Any, sep: str = " ", end: str = "\n") -> None:
        self.logs += sep.join(map(str, objects)) + end

    def flush(self, state: TradingState, orders: dict[Symbol, list[Order]], conversions: int, trader_data: str) -> None:
        base_length = len(
            self.to_json(
                [
                    self.compress_state(state, ""),
                    self.compress_orders(orders),
                    conversions,
                    "",
                    "",
                ]
            )
        )

        # We truncate state.traderData, trader_data, and self.logs to the same max. length to fit the log limit
        max_item_length = (self.max_log_length - base_length) // 3

        print(
            self.to_json(
                [
                    self.compress_state(state, self.truncate(state.traderData, max_item_length)),
                    self.compress_orders(orders),
                    conversions,
                    self.truncate(trader_data, max_item_length),
                    self.truncate(self.logs, max_item_length),
                ]
            )
        )

        self.logs = ""

    def compress_state(self, state: TradingState, trader_data: str) -> list[Any]:
        return [
            state.timestamp,
            trader_data,
            self.compress_listings(state.listings),
            self.compress_order_depths(state.order_depths),
            self.compress_trades(state.own_trades),
            self.compress_trades(state.market_trades),
            state.position,
            self.compress_observations(state.observations),
        ]

    def compress_listings(self, listings: dict[Symbol, Listing]) -> list[list[Any]]:
        compressed = []
        for listing in listings.values():
            compressed.append([listing.symbol, listing.product, listing.denomination])

        return compressed

    def compress_order_depths(self, order_depths: dict[Symbol, OrderDepth]) -> dict[Symbol, list[Any]]:
        compressed = {}
        for symbol, order_depth in order_depths.items():
            compressed[symbol] = [order_depth.buy_orders, order_depth.sell_orders]

        return compressed

    def compress_trades(self, trades: dict[Symbol, list[Trade]]) -> list[list[Any]]:
        compressed = []
        for arr in trades.values():
            for trade in arr:
                compressed.append(
                    [
                        trade.symbol,
                        trade.price,
                        trade.quantity,
                        trade.buyer,
                        trade.seller,
                        trade.timestamp,
                    ]
                )

        return compressed

    def compress_observations(self, observations: Observation) -> list[Any]:
        conversion_observations = {}
        for product, observation in observations.conversionObservations.items():
            conversion_observations[product] = [
                observation.bidPrice,
                observation.askPrice,
                observation.transportFees,
                observation.exportTariff,
                observation.importTariff,
                observation.sugarPrice,
                observation.sunlightIndex,
            ]

        return [observations.plainValueObservations, conversion_observations]

    def compress_orders(self, orders: dict[Symbol, list[Order]]) -> list[list[Any]]:
        compressed = []
        for arr in orders.values():
            for order in arr:
                compressed.append([order.symbol, order.price, order.quantity])

        return compressed

    def to_json(self, value: Any) -> str:
        return json.dumps(value, cls=ProsperityEncoder, separators=(",", ":"))

    def truncate(self, value: str, max_length: int) -> str:
        lo, hi = 0, min(len(value), max_length)
        out = ""

        while lo <= hi:
            mid = (lo + hi) // 2

            candidate = value[:mid]
            if len(candidate) < len(value):
                candidate += "..."

            encoded_candidate = json.dumps(candidate)

            if len(encoded_candidate) <= max_length:
                out = candidate
                lo = mid + 1
            else:
                hi = mid - 1

        return out


logger = Logger()


class Trader:
    POSITION_LIMITS = {
        "ASH_COATED_OSMIUM": 80,
        "INTARIAN_PEPPER_ROOT": 80,
    }

    DISABLED_PRODUCTS = {"INTARIAN_PEPPER_ROOT"}

    # Fraction of position limit beyond which we hit theo to flatten
    FLATTEN_THRESHOLD = 0.5

    def get_mid(self, order_depth: OrderDepth) -> float:
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        if best_bid and best_ask:
            return (best_bid + best_ask) / 2
        return best_bid or best_ask or 0

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        result = {}

        # Restore state
        trader_state = {}
        if state.traderData:
            try:
                trader_state = json.loads(state.traderData)
            except:
                trader_state = {}

        for product in state.order_depths:
            if product in self.DISABLED_PRODUCTS:
                result[product] = []
                continue
            order_depth: OrderDepth = state.order_depths[product]
            orders: list[Order] = []
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS.get(product, 50)
            mid = self.get_mid(order_depth)

            # --- Compute theo ---
            if product == "ASH_COATED_OSMIUM":
                theo = 10_000
            elif product == "INTARIAN_PEPPER_ROOT":
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
            # Also hit theo-priced orders when we need to flatten inventory
            if order_depth.sell_orders:
                for ask_price in sorted(order_depth.sell_orders.keys()):
                    if ask_price < theo and buy_room > 0:
                        ask_vol = -order_depth.sell_orders[ask_price]
                        qty = min(ask_vol, buy_room)
                        orders.append(Order(product, ask_price, qty))
                        buy_room -= qty
                    elif ask_price == theo and pos < -limit * self.FLATTEN_THRESHOLD and buy_room > 0:
                        # We're short past threshold — buy at theo to flatten
                        ask_vol = -order_depth.sell_orders[ask_price]
                        qty = min(ask_vol, buy_room, -pos)
                        if qty > 0:
                            orders.append(Order(product, ask_price, qty))
                            buy_room -= qty
                    else:
                        break

            if order_depth.buy_orders:
                for bid_price in sorted(order_depth.buy_orders.keys(), reverse=True):
                    if bid_price > theo and sell_room > 0:
                        bid_vol = order_depth.buy_orders[bid_price]
                        qty = min(bid_vol, sell_room)
                        orders.append(Order(product, bid_price, -qty))
                        sell_room -= qty
                    elif bid_price == theo and pos > limit * self.FLATTEN_THRESHOLD and sell_room > 0:
                        # We're long past threshold — sell at theo to flatten
                        bid_vol = order_depth.buy_orders[bid_price]
                        qty = min(bid_vol, sell_room, pos)
                        if qty > 0:
                            orders.append(Order(product, bid_price, -qty))
                            sell_room -= qty
                    else:
                        break

            # === 2. Passive: inventory-skewed penny quoting ===
            best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
            best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None

            if best_bid is not None:
                penny_bid = min(best_bid + 1, int(theo) - 1)
            else:
                penny_bid = int(theo) - 1

            if best_ask is not None:
                penny_ask = max(best_ask - 1, int(theo) + 1)
            else:
                penny_ask = int(theo) + 1

            bid_frac = 0.5
            ask_frac = 0.5

            bid_qty = min(int(buy_room * (0.5 + bid_frac)), buy_room)
            ask_qty = min(int(sell_room * (0.5 + ask_frac)), sell_room)

            if bid_qty > 0 and buy_room > 0:
                orders.append(Order(product, penny_bid, bid_qty))

            if ask_qty > 0 and sell_room > 0:
                orders.append(Order(product, penny_ask, -ask_qty))

            result[product] = orders

        trader_data = json.dumps(trader_state)
        conversions = 0

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
