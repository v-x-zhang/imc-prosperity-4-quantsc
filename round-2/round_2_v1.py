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

    # ASH theo config
    ASH_THEO_MODE = "wall_mid"       # "constant" | "ewma" | "wall_mid"
    ASH_ANCHOR_SEED = 10_000
    ASH_EWMA_SPAN = 500              # only used when mode == "ewma"
    ASH_WALL_MIN_VOLUME = 20         # only used when mode == "wall_mid"

    # ASH taker settings
    ASH_BUY_WIDTH = 1                # min (theo - ask) required to lift
    ASH_SELL_WIDTH = 1               # min (bid - theo) required to hit

    # ASH maker settings
    ASH_MODE = "both"                # "take" | "make" | "both"
    ASH_MAKE_PENNY_ALWAYS = False    # True = penny every tick; False = only when spread >= threshold
    ASH_MAKE_SPREAD_THRESHOLD = 10   # min (best_ask - best_bid) to enable pennying

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
                theo = self._ash_theo(order_depth, trader_state)
                logger.print(f"ash theo ({self.ASH_THEO_MODE}) = {theo}")
                orders = self._ash_trade(order_depth, pos, limit, product, theo)
            elif product == "INTARIAN_PEPPER_ROOT":
                orders = self._trade_pepper(order_depth, pos, limit, product, trader_state)

            result[product] = orders

        trader_data = json.dumps(trader_state)
        logger.flush(state, result, conversions, trader_data)
        return result, conversions, trader_data

    def _ash_theo(self, order_depth: OrderDepth, trader_state: dict[str, Any]) -> float:
        mode = self.ASH_THEO_MODE

        if mode == "constant":
            return float(self.ASH_ANCHOR_SEED)

        if mode == "ewma":
            best_bid = max(order_depth.buy_orders) if order_depth.buy_orders else None
            best_ask = min(order_depth.sell_orders) if order_depth.sell_orders else None
            if best_bid is not None and best_ask is not None:
                mid = (best_bid + best_ask) / 2.0
                alpha = 2.0 / (self.ASH_EWMA_SPAN + 1)
                prev = trader_state.get("ash_ewma", self.ASH_ANCHOR_SEED)
                trader_state["ash_ewma"] = alpha * mid + (1 - alpha) * prev
            return trader_state.get("ash_ewma", float(self.ASH_ANCHOR_SEED))

        if mode == "wall_mid":
            wall_bid = None
            for price in sorted(order_depth.buy_orders):  # deepest = lowest bid first
                if order_depth.buy_orders[price] >= self.ASH_WALL_MIN_VOLUME:
                    wall_bid = price
                    break
            wall_ask = None
            for price in sorted(order_depth.sell_orders, reverse=True):  # deepest = highest ask first
                if -order_depth.sell_orders[price] >= self.ASH_WALL_MIN_VOLUME:
                    wall_ask = price
                    break
            if wall_bid is not None and wall_ask is not None:
                trader_state["ash_wall_mid"] = (wall_bid + wall_ask) / 2.0
            return trader_state.get("ash_wall_mid", float(self.ASH_ANCHOR_SEED))

        return float(self.ASH_ANCHOR_SEED)

    def _ash_trade(self, order_depth: OrderDepth, pos: int, limit: int, product: Symbol, theo: float) -> list[Order]:
        orders: list[Order] = []
        buy_room = limit - pos
        sell_room = limit + pos

        # working copies so take consumption is visible to make
        bids = dict(order_depth.buy_orders)
        asks = dict(order_depth.sell_orders)

        if self.ASH_MODE in ("take", "both"):
            take_orders, buy_room, sell_room = self._ash_take(bids, asks, buy_room, sell_room, product, theo)
            orders.extend(take_orders)

        if self.ASH_MODE in ("make", "both"):
            orders.extend(self._ash_make(bids, asks, buy_room, sell_room, product, theo))

        return orders

    def _ash_take(self, bids: dict[int, int], asks: dict[int, int], buy_room: int, sell_room: int, product: Symbol, theo: float) -> tuple[list[Order], int, int]:
        orders: list[Order] = []
        buy_edge = theo - self.ASH_BUY_WIDTH
        sell_edge = theo + self.ASH_SELL_WIDTH

        # take asks at or below (theo - buy_width)
        for ask_price in sorted(asks):
            if buy_room <= 0 or ask_price >= buy_edge:
                break
            avail = -asks[ask_price]
            qty = min(avail, buy_room)
            if qty > 0:
                orders.append(Order(product, ask_price, qty))
                buy_room -= qty
                asks[ask_price] += qty  # asks stored as negative; += qty moves toward 0
                if asks[ask_price] == 0:
                    del asks[ask_price]

        # take bids at or above (theo + sell_width)
        for bid_price in sorted(bids, reverse=True):
            if sell_room <= 0 or bid_price <= sell_edge:
                break
            avail = bids[bid_price]
            qty = min(avail, sell_room)
            if qty > 0:
                orders.append(Order(product, bid_price, -qty))
                sell_room -= qty
                bids[bid_price] -= qty
                if bids[bid_price] == 0:
                    del bids[bid_price]

        return orders, buy_room, sell_room

    def _ash_make(self, bids: dict[int, int], asks: dict[int, int], buy_room: int, sell_room: int, product: Symbol, theo: float) -> list[Order]:
        orders: list[Order] = []

        # one-sided book: mirror deepest liquidity from the other side around theo
        if not bids and asks and buy_room > 0:
            deepest_ask = max(asks)  # farthest-out ask
            mirror_bid = int(round(2 * theo - deepest_ask))
            orders.append(Order(product, mirror_bid, buy_room))
            return orders
        
        if not asks and bids and sell_room > 0:
            deepest_bid = min(bids)  # farthest-out bid
            mirror_ask = int(round(2 * theo - deepest_bid))
            orders.append(Order(product, mirror_ask, -sell_room))
            return orders
        
        if not bids or not asks:
            return orders

        best_bid = max(bids)
        best_ask = min(asks)
        spread = best_ask - best_bid

        if not self.ASH_MAKE_PENNY_ALWAYS and spread < self.ASH_MAKE_SPREAD_THRESHOLD:
            return orders

        penny_bid = best_bid + 1
        penny_ask = best_ask - 1
        if penny_bid >= penny_ask:  # don't cross / lock
            return orders

        if buy_room > 0:
            orders.append(Order(product, penny_bid, buy_room))
        if sell_room > 0:
            orders.append(Order(product, penny_ask, -sell_room))

        return orders

    def _trade_pepper(self, order_depth: OrderDepth, pos: int, limit: int, product: Symbol, trader_state: dict[str, Any]) -> list[Order]:
        return []
    