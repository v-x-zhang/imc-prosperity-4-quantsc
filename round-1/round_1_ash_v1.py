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


# Layered ASH strategy (v1). Bump `LAYER` to enable successive ideas:
#   0: empty trader (baseline)
#   1: take any ask <= LOWER_ANCHOR, take any bid >= UPPER_ANCHOR

class Trader:
    POSITION_LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
    DISABLED_PRODUCTS = {"INTARIAN_PEPPER_ROOT"}

    LAYER = 1

    # L1 take thresholds — symmetric around 10,000, width tuned via grid search (1..10).
    CENTER = 10_000
    ANCHOR_WIDTH = 4  # buy when ask <= CENTER - width, sell when bid >= CENTER + width

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        result: dict[Symbol, list[Order]] = {}
        conversions = 0
        trader_data = ""

        # Layer 0: empty baseline.
        if self.LAYER == 0:
            logger.flush(state, result, conversions, trader_data)
            return result, conversions, trader_data

        for product in state.order_depths:
            if product in self.DISABLED_PRODUCTS:
                result[product] = []
                continue

            order_depth = state.order_depths[product]
            orders: list[Order] = []
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS[product]

            buy_room = limit - pos
            sell_room = limit + pos

            lower_anchor = self.CENTER - self.ANCHOR_WIDTH
            upper_anchor = self.CENTER + self.ANCHOR_WIDTH

            # Mutable copy of the book — decrement levels as we aggress so that
            # later layers see the post-take BBO / volumes.
            book_bids = dict(order_depth.buy_orders)   # price -> +qty
            book_asks = dict(order_depth.sell_orders)  # price -> -qty

            # ---------- L1: aggressive takes within ±ANCHOR_WIDTH of CENTER ----------
            if book_asks:
                for ask_price in sorted(book_asks.keys()):
                    if buy_room <= 0:
                        break
                    if ask_price > lower_anchor:
                        break
                    avail = -book_asks[ask_price]
                    qty = min(avail, buy_room)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        buy_room -= qty
                        book_asks[ask_price] += qty
                        if book_asks[ask_price] == 0:
                            del book_asks[ask_price]

            if book_bids:
                for bid_price in sorted(book_bids.keys(), reverse=True):
                    if sell_room <= 0:
                        break
                    if bid_price < upper_anchor:
                        break
                    avail = book_bids[bid_price]
                    qty = min(avail, sell_room)
                    if qty > 0:
                        orders.append(Order(product, bid_price, -qty))
                        sell_room -= qty
                        book_bids[bid_price] -= qty
                        if book_bids[bid_price] == 0:
                            del book_bids[bid_price]

            result[product] = orders

        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
