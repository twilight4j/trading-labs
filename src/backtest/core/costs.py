from __future__ import annotations


def validate_trade_costs(fee_rate: float, sell_tax_rate: float) -> None:
    if fee_rate < 0:
        raise ValueError("fee_rate must be >= 0")
    if sell_tax_rate < 0:
        raise ValueError("sell_tax_rate must be >= 0")
    if fee_rate + sell_tax_rate >= 1:
        raise ValueError("fee_rate + sell_tax_rate must be < 1")


def commission_and_tax(
    notional: float,
    *,
    side: str,
    fee_rate: float,
    sell_tax_rate: float,
) -> tuple[float, float]:
    """Return (commission, tax). Korean stock tax is charged on sells only."""
    fee = notional * fee_rate
    tax = notional * sell_tax_rate if side == "sell" else 0.0
    return fee, tax
