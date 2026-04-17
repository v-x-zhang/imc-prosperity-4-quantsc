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


# Pepper v1 — directional buy strategy ported from round_1.py::_trade_pepper,
# but with the anchor snapped to the nearest multiple of PEPPER_ANCHOR_ROUND
# (from round_1_pepper_v0) instead of the raw first-seen mid.
#
# theo = anchor + PEPPER_SLOPE * (t - t0)
# Rules:
#   diff = best_ask - theo
#   diff <= 4: buy up to 40 if OBI > 0 else 20
#   diff <= 8: buy up to 20 if OBI > 0 else 5
# Falls back to an unconditional buy at best_ask if the anchor hasn't been
# seeded yet (first tick with only a one-sided book).

class Trader:
    POSITION_LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
    DISABLED_PRODUCTS = {"ASH_COATED_OSMIUM"}

    PEPPER_SLOPE = 0.001
    PEPPER_ANCHOR_ROUND = 1000

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        result: dict[Symbol, list[Order]] = {}
        conversions = 0

        trader_state: dict[str, Any] = {}
        if state.traderData:
            try:
                trader_state = json.loads(state.traderData)
            except Exception:
                trader_state = {}

        for product in state.order_depths:
            if product in self.DISABLED_PRODUCTS:
                result[product] = []
                continue

            order_depth = state.order_depths[product]
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS[product]

            if product == "INTARIAN_PEPPER_ROOT":
                orders = self._trade_pepper(order_depth, pos, limit, product, state.timestamp, trader_state)
            else:
                orders = []

            result[product] = orders

        trader_data = json.dumps(trader_state)
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def _trade_pepper(self, order_depth: OrderDepth, pos: int, limit: int, product: str, timestamp: int, trader_state: dict) -> list[Order]:
        orders: list[Order] = []
        buy_room = limit - pos
        best_ask = min(order_depth.sell_orders.keys()) if order_depth.sell_orders else None
        best_bid = max(order_depth.buy_orders.keys()) if order_depth.buy_orders else None
        mid = (best_bid + best_ask) / 2 if best_bid and best_ask else None

        bv = order_depth.buy_orders.get(best_bid, 0) if best_bid else 0
        av = -order_depth.sell_orders.get(best_ask, 0) if best_ask else 0
        obi = (bv - av) / (bv + av + 1e-9)

        key = "pepper_anchor"
        # Snap anchor to the nearest multiple of PEPPER_ANCHOR_ROUND on the first
        # two-sided mid — v0 style, rather than storing the raw first-seen mid.
        if key not in trader_state and mid is not None:
            trader_state[key] = round(mid / self.PEPPER_ANCHOR_ROUND) * self.PEPPER_ANCHOR_ROUND
            trader_state["pepper_t0"] = timestamp

        if buy_room > 0 and best_ask is not None and key in trader_state:
            anchor = trader_state[key]
            t0 = trader_state["pepper_t0"]
            theo = anchor + (timestamp - t0) * self.PEPPER_SLOPE

            diff = best_ask - theo
            if diff <= 4:
                qty = min(buy_room, 40) if obi > 0 else min(buy_room, 20)
                orders.append(Order(product, best_ask, qty))
            elif diff <= 8:
                qty = min(buy_room, 20) if obi > 0 else min(buy_room, 5)
                orders.append(Order(product, best_ask, qty))
        elif buy_room > 0 and best_ask is not None:
            orders.append(Order(product, best_ask, buy_room))

        return orders
