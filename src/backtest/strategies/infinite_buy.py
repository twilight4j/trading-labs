from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

from backtest.core.costs import commission_and_tax, validate_trade_costs
from backtest.core.types import BacktestResult

MODE_NORMAL = "NORMAL"
MODE_REVERSE = "REVERSE"


def p_value(target_pct: float, splits: int, t: float, *, reverse: bool = False) -> float:
    """Star percent as a fraction. Reverse mode is 0."""
    if reverse or splits < 2:
        return 0.0
    return target_pct - (target_pct / (splits / 2.0)) * t


def star_price(avg: float, p_frac: float) -> float:
    return avg * (1.0 + p_frac)


def buy_amount(balance: float, splits: int, t: float, *, reverse: bool) -> float:
    if reverse:
        return balance / 4.0
    return balance / max(0.1, splits - t)


def first_half_qtys(amt: float, price1: float, price2: float) -> tuple[int, int]:
    if price1 <= 0 or price2 <= 0 or amt <= 0:
        return 0, 0
    q1 = int((amt * 0.5) // price1)
    total_qty = int(amt // price2)
    q2 = max(0, total_qty - q1)
    return q1, q2


def crash_tier_prices(
    amt: float,
    base_qty: int,
    large_num: float,
    *,
    max_tiers: int = 5,
    max_loops: int = 15,
) -> list[float]:
    prices: list[float] = []
    check_qty = base_qty + 1
    found = 0
    for _ in range(max_loops):
        if check_qty <= 0:
            break
        tier_price = amt / check_qty
        if 0 < tier_price < large_num:
            prices.append(float(tier_price))
            found += 1
        if found >= max_tiers:
            break
        check_qty += 1
    return prices


def clip_to_band(price: float, ref: float, limit_pct: float) -> float:
    if limit_pct <= 0 or ref <= 0:
        return price
    lo = ref * (1.0 - limit_pct)
    hi = ref * (1.0 + limit_pct)
    return min(max(price, lo), hi)


@dataclass(frozen=True)
class BuyLeg:
    limit: float
    qty: int
    reason: str


@dataclass
class OrderTicket:
    buy_legs: list[BuyLeg] = field(default_factory=list)
    crash_tiers: list[BuyLeg] = field(default_factory=list)
    buy_forbidden: bool = False
    quarter_limit: float | None = None
    quarter_qty: int = 0
    target_limit: float | None = None
    target_qty: int = 0
    reverse_moc_qty: int = 0
    reverse_loc_limit: float | None = None
    reverse_loc_qty: int = 0


@dataclass
class _State:
    principal: float
    cash: float
    shares: int
    avg: float
    t: float
    mode: str


def _tick_price(price: float, tick_size: float) -> float:
    return max(tick_size if tick_size > 0 else 0.0, price - tick_size)


@dataclass(frozen=True)
class InfiniteBuyStrategy:
    name: str = "infinite_buy"
    splits: int = 40
    target_pct: float = 0.15
    big_buy_pct: float = 0.10
    tick_size: float = 1.0
    price_limit_pct: float = 0.30
    start_shares: int = 0
    start_avg: float = 0.0
    wait_extended: bool = False
    entry_lookback: int = 20
    entry_pullback_pct: float = 0.10

    def prepare(self, prices: pd.DataFrame) -> pd.DataFrame:
        return prices

    def run(
        self,
        prices: pd.DataFrame,
        *,
        initial_cash: float = 10_000_000.0,
        fee_rate: float = 0.0015,
        sell_tax_rate: float = 0.0,
    ) -> BacktestResult:
        self._validate(initial_cash, fee_rate, sell_tax_rate)
        required = {"trade_date", "open", "close"}
        missing = required - set(prices.columns)
        if missing:
            raise KeyError(f"missing columns: {sorted(missing)}")

        state = self._initial_state(initial_cash)
        ticket: OrderTicket | None = None
        closes: list[float] = []
        equity_rows: list[dict] = []
        trade_rows: list[dict] = []

        for _, row in prices.iterrows():
            open_px, high_px, low_px, close_px = _ohlc(row)
            trade_date = row["trade_date"]
            if close_px <= 0 or open_px <= 0:
                continue

            previous_mode = state.mode
            if ticket is None and state.shares == 0:
                # Start bar: 무조건 매수. 큰수는 당일 종가로 수량을 잡고, 종가 <= 큰수이므로 그날 체결된다.
                ticket = self._next_ticket(
                    state, close_px, close_px, entered_reverse=False, closes=closes
                )
            if ticket is not None:
                state, day_trades = self._fill(
                    ticket, state, high_px, close_px, fee_rate, sell_tax_rate, trade_date
                )
                trade_rows.extend(day_trades)
                if state.shares < 0:
                    state.shares = 0
            else:
                t, mode, principal = _update_t_mode(
                    old_shares=state.shares,
                    new_shares=state.shares,
                    old_t=state.t,
                    old_mode=state.mode,
                    old_avg=state.avg,
                    new_avg=state.avg,
                    close=close_px,
                    splits=self.splits,
                    target_pct=self.target_pct,
                    cash=state.cash,
                    principal=state.principal,
                )
                state = _State(
                    principal=principal,
                    cash=state.cash,
                    shares=state.shares,
                    avg=state.avg,
                    t=t,
                    mode=mode,
                )

            closes.append(close_px)
            sma5 = sum(closes[-5:]) / len(closes[-5:])
            entered_reverse = previous_mode == MODE_NORMAL and state.mode == MODE_REVERSE
            ticket = self._next_ticket(
                state, close_px, sma5, entered_reverse=entered_reverse, closes=closes
            )

            p_frac = p_value(self.target_pct, self.splits, state.t, reverse=state.mode == MODE_REVERSE)
            star = star_price(state.avg, p_frac) if state.shares > 0 else 0.0
            row = {
                "trade_date": trade_date,
                "cash": state.cash,
                "shares": float(state.shares),
                "open": open_px,
                "high": high_px,
                "low": low_px,
                "close": close_px,
                "equity": state.cash + state.shares * close_px,
                "position": 1 if state.shares > 0 else 0,
                "principal": state.principal,
                "t_value": state.t,
                "avg_price": state.avg,
                "star": star,
                "p_value": p_frac,
                "mode": state.mode,
            }
            if self.wait_extended:
                if state.shares <= 0 and self._is_extended(closes, close_px):
                    row["regime"] = "WAIT"
                elif state.mode == MODE_REVERSE:
                    row["regime"] = MODE_REVERSE
                else:
                    row["regime"] = MODE_NORMAL
            equity_rows.append(row)

        equity = pd.DataFrame(equity_rows)
        trades = pd.DataFrame(trade_rows)
        return BacktestResult(
            equity=equity,
            trades=trades,
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            sell_tax_rate=sell_tax_rate,
        )

    def _validate(self, initial_cash: float, fee_rate: float, sell_tax_rate: float) -> None:
        if self.splits < 2:
            raise ValueError("splits must be >= 2")
        if self.target_pct <= 0:
            raise ValueError("target_pct must be > 0")
        if self.big_buy_pct <= 0:
            raise ValueError("big_buy_pct must be > 0")
        if self.tick_size < 0:
            raise ValueError("tick_size must be >= 0")
        if self.price_limit_pct < 0:
            raise ValueError("price_limit_pct must be >= 0")
        if initial_cash <= 0:
            raise ValueError("initial_cash must be positive")
        validate_trade_costs(fee_rate, sell_tax_rate)
        if (self.start_shares > 0 and self.start_avg <= 0) or (self.start_shares <= 0 and self.start_avg > 0):
            raise ValueError("start_shares and start_avg must be set together")
        if self.entry_lookback < 2:
            raise ValueError("entry_lookback must be >= 2")
        if self.entry_pullback_pct < 0 or self.entry_pullback_pct >= 1:
            raise ValueError("entry_pullback_pct must be in [0, 1)")

    def _initial_state(self, initial_cash: float) -> _State:
        if self.start_shares > 0 and self.start_avg > 0:
            invested = self.start_shares * self.start_avg
            if invested > initial_cash:
                raise ValueError("start position cost exceeds initial_cash")
            t = (invested / initial_cash) * self.splits
            mode = MODE_REVERSE if t > self.splits - 1 else MODE_NORMAL
            return _State(
                principal=initial_cash,
                cash=initial_cash - invested,
                shares=self.start_shares,
                avg=self.start_avg,
                t=t,
                mode=mode,
            )
        return _State(
            principal=initial_cash,
            cash=initial_cash,
            shares=0,
            avg=0.0,
            t=0.0,
            mode=MODE_NORMAL,
        )

    def _is_extended(self, closes: list[float], close: float) -> bool:
        if not self.wait_extended:
            return False
        if len(closes) < self.entry_lookback:
            return False
        high = max(closes[-self.entry_lookback :])
        if high <= 0:
            return False
        return close > high * (1.0 - self.entry_pullback_pct)

    def _next_ticket(
        self,
        state: _State,
        close: float,
        sma5: float,
        *,
        entered_reverse: bool,
        closes: list[float],
    ) -> OrderTicket:
        n = self.splits
        large_num = clip_to_band(close * (1.0 + self.big_buy_pct), close, self.price_limit_pct)
        reverse = state.mode == MODE_REVERSE
        p_frac = p_value(self.target_pct, n, state.t, reverse=reverse)
        ticket = OrderTicket()

        if state.shares <= 0:
            if self.wait_extended and self._is_extended(closes, close):
                return ticket
            amt = state.principal / n
            qty = int(amt // large_num) if large_num > 0 else 0
            if qty > 0:
                ticket.buy_legs.append(BuyLeg(large_num, qty, "first_buy"))
            ticket.crash_tiers = self._crash_legs(amt, qty, large_num, close)
            return ticket

        amt = buy_amount(state.cash, n, state.t, reverse=reverse)
        rev_qty = int(state.shares // (n / 2.0))

        if reverse and entered_reverse:
            ticket.reverse_moc_qty = rev_qty
            ticket.buy_forbidden = True
            return ticket

        if reverse:
            sma5_buy = _tick_price(max(sma5, self.tick_size), self.tick_size)
            qty = int(amt // sma5_buy) if sma5_buy > 0 else 0
            if qty > 0:
                ticket.buy_legs.append(BuyLeg(sma5_buy, qty, "reverse_buy"))
            ticket.crash_tiers = self._crash_legs(amt, qty, large_num, close)
            ticket.reverse_loc_limit = sma5
            ticket.reverse_loc_qty = rev_qty
            return ticket

        star_sell = max(self.tick_size, star_price(state.avg, p_frac))
        star_buy = _tick_price(star_sell, self.tick_size)
        price1 = clip_to_band(min(star_buy, large_num), close, self.price_limit_pct)
        price2 = clip_to_band(min(state.avg, large_num), close, self.price_limit_pct)
        if state.t < n / 2.0:
            q1, q2 = first_half_qtys(amt, price1, price2)
            if q1 > 0:
                ticket.buy_legs.append(BuyLeg(price1, q1, "half_star"))
            if q2 > 0:
                ticket.buy_legs.append(BuyLeg(price2, q2, "half_avg"))
            base_qty = q1 + q2
        else:
            final_price = clip_to_band(min(star_buy, large_num), close, self.price_limit_pct)
            qty = int(amt // final_price) if final_price > 0 else 0
            if qty > 0:
                ticket.buy_legs.append(BuyLeg(final_price, qty, "second_half"))
            base_qty = qty

        ticket.crash_tiers = self._crash_legs(amt, base_qty, large_num, close)
        q_qty = int(state.shares * 0.25)
        ticket.quarter_limit = star_sell
        ticket.quarter_qty = q_qty
        ticket.target_limit = state.avg * (1.0 + self.target_pct)
        ticket.target_qty = state.shares - q_qty
        return ticket

    def _crash_legs(self, amt: float, base_qty: int, large_num: float, ref_close: float) -> list[BuyLeg]:
        legs: list[BuyLeg] = []
        for price in crash_tier_prices(amt, base_qty, large_num):
            clipped = clip_to_band(price, ref_close, self.price_limit_pct)
            if 0 < clipped < large_num:
                legs.append(BuyLeg(clipped, 1, "crash_tier"))
        return legs

    def _fill(
        self,
        ticket: OrderTicket,
        state: _State,
        high: float,
        close: float,
        fee_rate: float,
        sell_tax_rate: float,
        trade_date: object,
    ) -> tuple[_State, list[dict]]:
        old_shares = state.shares
        old_avg = state.avg
        old_t = state.t
        old_mode = state.mode
        cash = state.cash
        shares = state.shares
        avg = state.avg
        trades: list[dict] = []

        def record(side: str, price: float, qty: int, fee: float, tax: float, reason: str) -> None:
            trades.append({
                "trade_date": trade_date,
                "side": side,
                "price": price,
                "shares": float(qty),
                "fee": fee,
                "tax": tax,
                "cash_after": cash,
                "reason": reason,
            })

        def sell(qty: int, price: float, reason: str) -> None:
            nonlocal cash, shares
            qty = min(qty, shares)
            if qty <= 0 or price <= 0:
                return
            notional = qty * price
            fee, tax = commission_and_tax(
                notional, side="sell", fee_rate=fee_rate, sell_tax_rate=sell_tax_rate
            )
            cash += notional - fee - tax
            shares -= qty
            record("sell", price, qty, fee, tax, reason)

        def buy(qty: int, price: float, reason: str) -> int:
            nonlocal cash, shares, avg
            if qty <= 0 or price <= 0:
                return 0
            cost_each = price * (1.0 + fee_rate)
            affordable = int(cash // cost_each) if cost_each > 0 else 0
            qty = min(qty, affordable)
            if qty <= 0:
                return 0
            notional = qty * price
            fee, tax = commission_and_tax(
                notional, side="buy", fee_rate=fee_rate, sell_tax_rate=sell_tax_rate
            )
            spent = notional + fee
            new_cost = shares * avg + notional
            cash -= spent
            shares += qty
            avg = new_cost / shares if shares else 0.0
            record("buy", price, qty, fee, tax, reason)
            return qty

        if ticket.reverse_moc_qty > 0:
            sell(ticket.reverse_moc_qty, close, "reverse_moc")
        elif ticket.reverse_loc_limit is not None:
            if close >= ticket.reverse_loc_limit:
                sell(ticket.reverse_loc_qty, close, "reverse_loc")
        else:
            if ticket.target_limit is not None and high >= ticket.target_limit:
                sell(ticket.target_qty, ticket.target_limit, "target_limit")
            if shares > 0 and ticket.quarter_limit is not None and close >= ticket.quarter_limit:
                sell(ticket.quarter_qty, close, "quarter_sell")

        flattened = old_shares > 0 and shares <= 0
        if not flattened and not ticket.buy_forbidden:
            for leg in ticket.buy_legs:
                if close <= leg.limit:
                    buy(leg.qty, close, leg.reason)
            for leg in sorted(ticket.crash_tiers, key=lambda item: item.limit, reverse=True):
                if close <= leg.limit:
                    buy(leg.qty, close, leg.reason)

        t, mode, principal = _update_t_mode(
            old_shares=old_shares,
            new_shares=shares,
            old_t=old_t,
            old_mode=old_mode,
            old_avg=old_avg,
            new_avg=avg,
            close=close,
            splits=self.splits,
            target_pct=self.target_pct,
            cash=cash,
            principal=state.principal,
        )
        if shares <= 0:
            avg = 0.0
        return _State(principal=principal, cash=cash, shares=shares, avg=avg, t=t, mode=mode), trades


def _update_t_mode(
    *,
    old_shares: int,
    new_shares: int,
    old_t: float,
    old_mode: str,
    old_avg: float,
    new_avg: float,
    close: float,
    splits: int,
    target_pct: float,
    cash: float,
    principal: float,
) -> tuple[float, str, float]:
    action = "SELL" if new_shares < old_shares else "BUY" if new_shares > old_shares else "NONE"
    t = old_t
    mode = old_mode
    cycle_end = new_shares <= 0 and action == "SELL"

    if action == "SELL" and not cycle_end:
        q_qty = int(old_shares * 0.25)
        if new_shares <= old_shares * 0.60:
            t = old_t * 0.25
            if new_shares > q_qty:
                t += 0.5 if close > old_avg else 1.0
        elif mode == MODE_NORMAL:
            t = old_t * 0.75
        else:
            t = old_t * (1.0 - 2.0 / splits)
    elif action == "BUY":
        if mode == MODE_NORMAL:
            if old_shares == 0:
                t = t + 1.0
            elif t < splits / 2.0:
                t = t + (0.5 if close > old_avg else 1.0)
            else:
                t = t + 1.0
        else:
            t = t + ((splits - t) * 0.25)

    if cycle_end:
        return 0.0, MODE_NORMAL, cash

    if mode == MODE_NORMAL and t > splits - 1:
        mode = MODE_REVERSE
    elif mode == MODE_REVERSE and new_avg > 0 and close > new_avg * (1.0 - target_pct):
        mode = MODE_NORMAL
    return t, mode, principal


def _ohlc(row: pd.Series) -> tuple[float, float, float, float]:
    open_px = float(row["open"])
    close_px = float(row["close"])
    if "high" in row.index and pd.notna(row["high"]):
        high_px = float(row["high"])
    else:
        high_px = max(open_px, close_px)
    if "low" in row.index and pd.notna(row["low"]):
        low_px = float(row["low"])
    else:
        low_px = min(open_px, close_px)
    return open_px, high_px, low_px, close_px


def run_infinite_buy(
    prices: pd.DataFrame,
    *,
    splits: int = 40,
    target_pct: float = 0.15,
    big_buy_pct: float = 0.10,
    tick_size: float = 1.0,
    price_limit_pct: float = 0.30,
    initial_cash: float = 10_000_000.0,
    fee_rate: float = 0.0015,
    sell_tax_rate: float = 0.0,
    start_shares: int = 0,
    start_avg: float = 0.0,
    wait_extended: bool = False,
    entry_lookback: int = 20,
    entry_pullback_pct: float = 0.10,
) -> BacktestResult:
    return InfiniteBuyStrategy(
        splits=splits,
        target_pct=target_pct,
        big_buy_pct=big_buy_pct,
        tick_size=tick_size,
        price_limit_pct=price_limit_pct,
        start_shares=start_shares,
        start_avg=start_avg,
        wait_extended=wait_extended,
        entry_lookback=entry_lookback,
        entry_pullback_pct=entry_pullback_pct,
    ).run(
        prices,
        initial_cash=initial_cash,
        fee_rate=fee_rate,
        sell_tax_rate=sell_tax_rate,
    )
