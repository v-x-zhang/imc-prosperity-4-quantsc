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


# Layered ASH strategy (v2). Same three layers as v1, but ANCHOR_WIDTH,
# FLATTEN_WIDTH, and QUOTE_EDGE are adjusted asymmetrically based on current
# inventory (pos_ratio = pos / limit in [-1, 1]):
#
#   buy-side width  = base + SKEW * pos_ratio   (wider when long → harder to add)
#   sell-side width = base - SKEW * pos_ratio   (tighter when long → easier to shed)
#
#   buy-side flatten width  = FLATTEN_WIDTH + FLATTEN_WIDTH_SKEW * pos_ratio
#   sell-side flatten width = FLATTEN_WIDTH - FLATTEN_WIDTH_SKEW * pos_ratio
#       (flatten floors/ceilings migrate toward worse prices as |pos| grows)
#
#   buy-side quote edge  = QUOTE_EDGE + QUOTE_EDGE_SKEW * pos_ratio
#   sell-side quote edge = QUOTE_EDGE - QUOTE_EDGE_SKEW * pos_ratio
#       (penny quotes require more edge on the add side, less on the shed side)
#
# All widths are floored at 0 so they can't invert the inequalities.

class Trader:
    POSITION_LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}
    DISABLED_PRODUCTS = {"INTARIAN_PEPPER_ROOT"}

    LAYER = 3

    # L1 take thresholds — base widths, skewed by pos_ratio.
    ANCHOR_MODE = "ewma"      # "constant" or "ewma"
    CONSTANT_ANCHOR = 10_000  # price level that anchor is fixed at when ANCHOR_MODE = "constant"
    EWMA_SPAN = 500           # ticks; alpha = 2 / (span + 1)
    ANCHOR_WIDTH = 2          # base width; effective side width = base ± SKEW * pos_ratio
    ANCHOR_WIDTH_SKEW = 2     # how much the take width stretches/shrinks at |pos_ratio| = 1

    # L2 flatten thresholds — kicks in only when inventory is already heavy.
    FLATTEN_THRESHOLD = 40    # start flattening once |pos| exceeds this, target = ±FLATTEN_THRESHOLD
    FLATTEN_WIDTH = 0         # base flatten width; shrinks as |pos| grows past threshold
    FLATTEN_WIDTH_SKEW = 0    # at |pos_ratio| = 1 the flatten width moves by this much

    # L3 conditional pennying — base edge, skewed by pos_ratio so the add-side
    # quote demands more edge and the shed-side quote demands less.
    QUOTE_EDGE = 3
    QUOTE_EDGE_SKEW = 0

    def run(self, state: TradingState) -> tuple[dict[Symbol, list[Order]], int, str]:
        result: dict[Symbol, list[Order]] = {}
        conversions = 0

        # Persistent state: per-product EWMA of mid, carried across ticks via traderData.
        try:
            persistent = json.loads(state.traderData) if state.traderData else {}
        except (json.JSONDecodeError, ValueError):
            persistent = {}
        ewma_by_product: dict[str, float] = dict(persistent.get("ewma", {}))

        # Layer 0: empty baseline.
        if self.LAYER == 0:
            trader_data = json.dumps({"ewma": ewma_by_product}, separators=(",", ":"))
            logger.flush(state, result, conversions, trader_data)
            return result, conversions, trader_data

        alpha = 2.0 / (self.EWMA_SPAN + 1)

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

            # Update EWMA of mid (always maintained so toggling is cheap).
            # Seed prev at CONSTANT_ANCHOR (10_000) on first observation so the first mid
            # is blended into 10_000 rather than replacing it outright — avoids a single
            # early tick pinning the anchor.
            best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
            best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / 2.0
                prev = ewma_by_product.get(product, self.CONSTANT_ANCHOR)
                ewma_by_product[product] = alpha * mid + (1 - alpha) * prev

            if self.ANCHOR_MODE == "constant":
                anchor = self.CONSTANT_ANCHOR
            elif self.ANCHOR_MODE == "ewma":
                anchor = ewma_by_product.get(product)
            else:
                raise ValueError(f"unknown ANCHOR_MODE: {self.ANCHOR_MODE!r}")

            if anchor is None:
                # EWMA not yet seeded (no mid observed yet) — skip trading this tick.
                result[product] = orders
                continue

            # Inventory-aware widths: buy side widens when long, sell side tightens.
            pos_ratio = pos / limit if limit > 0 else 0.0
            buy_anchor_width = max(0.0, self.ANCHOR_WIDTH + self.ANCHOR_WIDTH_SKEW * pos_ratio)
            sell_anchor_width = max(0.0, self.ANCHOR_WIDTH - self.ANCHOR_WIDTH_SKEW * pos_ratio)
            lower_anchor = anchor - buy_anchor_width
            upper_anchor = anchor + sell_anchor_width

            # Mutable copy of the book — decrement levels as we aggress so that
            # later layers see the post-take BBO / volumes.
            book_bids = dict(order_depth.buy_orders)   # price -> +qty
            book_asks = dict(order_depth.sell_orders)  # price -> -qty

            # ---------- L1: aggressive takes within ±ANCHOR_WIDTH of anchor ----------
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
                        pos += qty
                        buy_room -= qty
                        sell_room += qty
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
                        pos -= qty
                        sell_room -= qty
                        buy_room += qty
                        book_bids[bid_price] -= qty
                        if book_bids[bid_price] == 0:
                            del book_bids[bid_price]

            # ---------- L2: flatten when |pos| > FLATTEN_THRESHOLD ----------
            # Only trades on the side that reduces |pos|, and only down to ±FLATTEN_THRESHOLD.
            if self.LAYER >= 2:
                # When long (pos_ratio > 0), shrink the sell-side flatten width so we
                # accept worse bids; symmetric for short on the buy side.
                flatten_sell_width = self.FLATTEN_WIDTH - self.FLATTEN_WIDTH_SKEW * pos_ratio
                flatten_buy_width = self.FLATTEN_WIDTH + self.FLATTEN_WIDTH_SKEW * pos_ratio
                flatten_sell_floor = anchor + flatten_sell_width  # accept bids >= this when long
                flatten_buy_ceil = anchor - flatten_buy_width     # accept asks <= this when short

                if pos > self.FLATTEN_THRESHOLD and book_bids:
                    shed_room = pos - self.FLATTEN_THRESHOLD
                    for bid_price in sorted(book_bids.keys(), reverse=True):
                        if shed_room <= 0 or sell_room <= 0:
                            break
                        if bid_price < flatten_sell_floor:
                            break
                        avail = book_bids[bid_price]
                        qty = min(avail, shed_room, sell_room)
                        if qty > 0:
                            orders.append(Order(product, bid_price, -qty))
                            pos -= qty
                            sell_room -= qty
                            buy_room += qty
                            shed_room -= qty
                            book_bids[bid_price] -= qty
                            if book_bids[bid_price] == 0:
                                del book_bids[bid_price]

                elif pos < -self.FLATTEN_THRESHOLD and book_asks:
                    shed_room = -self.FLATTEN_THRESHOLD - pos
                    for ask_price in sorted(book_asks.keys()):
                        if shed_room <= 0 or buy_room <= 0:
                            break
                        if ask_price > flatten_buy_ceil:
                            break
                        avail = -book_asks[ask_price]
                        qty = min(avail, shed_room, buy_room)
                        if qty > 0:
                            orders.append(Order(product, ask_price, qty))
                            pos += qty
                            buy_room -= qty
                            sell_room += qty
                            shed_room -= qty
                            book_asks[ask_price] += qty
                            if book_asks[ask_price] == 0:
                                del book_asks[ask_price]

            # ---------- L3: conditional pennying ----------
            # Quote a penny inside the residual BBO, but only if the penny price
            # still sits at least QUOTE_EDGE from anchor (else no edge to earn).
            if self.LAYER >= 3:
                # L2 flattening may have reduced |pos|; recompute pos_ratio so the
                # L3 edge reflects inventory after takes and flattens.
                post_pos_ratio = pos / limit if limit > 0 else 0.0
                buy_quote_edge = max(0.0, self.QUOTE_EDGE + self.QUOTE_EDGE_SKEW * post_pos_ratio)
                sell_quote_edge = max(0.0, self.QUOTE_EDGE - self.QUOTE_EDGE_SKEW * post_pos_ratio)

                post_bid = max(book_bids.keys()) if book_bids else None
                post_ask = min(book_asks.keys()) if book_asks else None

                if post_bid is not None and buy_room > 0:
                    quote_bid = post_bid + 1
                    if quote_bid <= anchor - buy_quote_edge:
                        orders.append(Order(product, quote_bid, buy_room))

                if post_ask is not None and sell_room > 0:
                    quote_ask = post_ask - 1
                    if quote_ask >= anchor + sell_quote_edge:
                        orders.append(Order(product, quote_ask, -sell_room))

            result[product] = orders

        trader_data = json.dumps({"ewma": ewma_by_product}, separators=(",", ":"))
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data
