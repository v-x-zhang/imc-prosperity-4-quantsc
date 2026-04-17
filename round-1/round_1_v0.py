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


class Trader:
    POSITION_LIMITS = {"ASH_COATED_OSMIUM": 80, "INTARIAN_PEPPER_ROOT": 80}

    # --- ASH parameters (177482 anchor bot) ---
    ASH_ANCHOR = 10_000
    PEPPER_SLOPE = 0.001
    W = 1
    FLATTEN_THRESHOLD = 0.3
    SKEW = 5.0
    N_LEVELS = 1
    PENNY = True
    PENNY_ENTRY_ONLY = False
    EXIT_EDGE = 6

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
            order_depth = state.order_depths[product]
            orders: list[Order] = []
            pos = state.position.get(product, 0)
            limit = self.POSITION_LIMITS[product]

            if product == "ASH_COATED_OSMIUM":
                orders = self._trade_ash(order_depth, pos, limit, product)
            elif product == "INTARIAN_PEPPER_ROOT":
                orders = self._trade_pepper(order_depth, pos, limit, product, state.timestamp, trader_state)

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
        if key not in trader_state and mid is not None:
            trader_state[key] = mid
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

    def _trade_ash(self, order_depth: OrderDepth, pos: int, limit: int, product: str) -> list[Order]:
        orders: list[Order] = []
        anchor = self.ASH_ANCHOR
        buy_room = limit - pos
        sell_room = limit + pos

        book_bids = dict(order_depth.buy_orders)
        book_asks = dict(order_depth.sell_orders)

        # ---------- Aggressive takes ----------
        pos_ratio = pos / limit if limit > 0 else 0.0
        exit_extra = 0
        if self.EXIT_EDGE > 0:
            ft = self.FLATTEN_THRESHOLD
            if abs(pos_ratio) > ft:
                exit_extra = int(self.EXIT_EDGE * (abs(pos_ratio) - ft) / (1.0 - ft + 1e-9))

        if book_asks:
            buy_threshold = anchor + (exit_extra if pos_ratio < -self.FLATTEN_THRESHOLD else 0)
            for ask_price in sorted(book_asks.keys()):
                if buy_room <= 0:
                    break
                take = ask_price < anchor
                flatten = (
                    ask_price <= buy_threshold
                    and ask_price >= anchor
                    and pos < -limit * self.FLATTEN_THRESHOLD
                )
                if take or flatten:
                    avail = -book_asks[ask_price]
                    qty = min(avail, buy_room)
                    if flatten and not take:
                        qty = min(qty, -pos)
                    if qty > 0:
                        orders.append(Order(product, ask_price, qty))
                        buy_room -= qty
                        pos += qty
                        book_asks[ask_price] += qty
                        if book_asks[ask_price] == 0:
                            del book_asks[ask_price]
                else:
                    break

        if book_bids:
            sell_threshold = anchor - (exit_extra if pos_ratio > self.FLATTEN_THRESHOLD else 0)
            for bid_price in sorted(book_bids.keys(), reverse=True):
                if sell_room <= 0:
                    break
                take = bid_price > anchor
                flatten = (
                    bid_price >= sell_threshold
                    and bid_price <= anchor
                    and pos > limit * self.FLATTEN_THRESHOLD
                )
                if take or flatten:
                    avail = book_bids[bid_price]
                    qty = min(avail, sell_room)
                    if flatten and not take:
                        qty = min(qty, pos)
                    if qty > 0:
                        orders.append(Order(product, bid_price, -qty))
                        sell_room -= qty
                        pos -= qty
                        book_bids[bid_price] -= qty
                        if book_bids[bid_price] == 0:
                            del book_bids[bid_price]
                else:
                    break

        # Post-aggression BBO
        best_bid = max(book_bids.keys()) if book_bids else None
        best_ask = min(book_asks.keys()) if book_asks else None

        # ---------- Passive quoting ----------
        skew_offset = -self.SKEW * (pos / limit) if limit > 0 else 0.0
        theo_quote = anchor + skew_offset

        remaining_bid = buy_room
        remaining_ask = sell_room
        for lvl in range(self.N_LEVELS):
            offset = self.W + lvl
            target_bid = int(theo_quote - offset)
            target_ask = int(theo_quote + offset)

            if lvl == 0 and self.PENNY:
                penny_bid = True
                penny_ask = True
                if self.PENNY_ENTRY_ONLY:
                    if pos > 0:
                        penny_ask = False
                    elif pos < 0:
                        penny_bid = False
                if penny_bid and best_bid is not None:
                    target_bid = min(best_bid + 1, target_bid)
                if penny_ask and best_ask is not None:
                    target_ask = max(best_ask - 1, target_ask)

            if self.N_LEVELS == 1:
                bid_qty = remaining_bid
                ask_qty = remaining_ask
            else:
                frac = 0.6 if lvl == 0 else 0.4 / (self.N_LEVELS - 1)
                bid_qty = min(int(buy_room * frac) + (1 if lvl == self.N_LEVELS - 1 else 0), remaining_bid)
                ask_qty = min(int(sell_room * frac) + (1 if lvl == self.N_LEVELS - 1 else 0), remaining_ask)

            if bid_qty > 0:
                orders.append(Order(product, target_bid, bid_qty))
                remaining_bid -= bid_qty
            if ask_qty > 0:
                orders.append(Order(product, target_ask, -ask_qty))
                remaining_ask -= ask_qty

        return orders
    