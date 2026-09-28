from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from backtest.analytics import (
    format_infinite_buy_fills,
    format_infinite_buy_report,
    infinite_buy_fills,
    summarize,
    summarize_infinite_buy,
)
from backtest.api import run_backtest
from backtest.strategies import available_strategies

app = typer.Typer(help="단일 종목 토이 백테스트")


@app.callback()
def _root() -> None:
    """단일 종목 토이 백테스트."""


def _parse_date(value: str | None) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("YYYY-MM-DD 형식이어야 합니다.") from exc


def _pct(value: float) -> str:
    return f"{value * 100:.2f}%"


@app.command("run")
def run(
    strategy: str = typer.Option("golden_cross", help=f"등록 전략: {', '.join(available_strategies())}"),
    security_id: str = typer.Option("KRX:005930"),
    fast: int = typer.Option(50, min=1),
    slow: int = typer.Option(200, min=2),
    splits: int = typer.Option(40, min=2, help="무한매수법 분할 수"),
    target_pct: float = typer.Option(0.15, help="무한매수법 목표 수익률 (사이클 고정)"),
    big_buy_pct: float = typer.Option(0.10, help="무한매수법 큰수 기준 (전일 종가 대비)"),
    wait_extended: bool = typer.Option(False, help="무한매수법: 고점 근처에서 사이클 재시작 대기"),
    entry_lookback: int = typer.Option(20, min=2, help="무한매수법 WAIT 고점 룩백 일수"),
    entry_pullback_pct: float = typer.Option(0.10, help="무한매수법 WAIT 고점 대비 조정 비율"),
    start: str | None = typer.Option(None, help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, help="YYYY-MM-DD"),
    data_dir: Path = typer.Option(Path("data/market-data")),
    initial_cash: float = typer.Option(10_000_000.0),
    fee_rate: float = typer.Option(0.0015, help="편도 위탁수수료 비율 (매수·매도 동일)"),
    sell_tax_rate: float = typer.Option(0.0, help="매도세 비율 (코스피/코스닥 0.002, ETF 0). 매수에는 없음"),
) -> None:
    """등록된 전략으로 단일 종목 백테스트를 실행합니다."""
    params: dict[str, object] = {}
    if strategy == "golden_cross":
        params = {"fast": fast, "slow": slow}
    elif strategy == "infinite_buy":
        params = {
            "splits": splits,
            "target_pct": target_pct,
            "big_buy_pct": big_buy_pct,
            "wait_extended": wait_extended,
            "entry_lookback": entry_lookback,
            "entry_pullback_pct": entry_pullback_pct,
        }

    try:
        result = run_backtest(
            strategy,
            security_id,
            data_dir=data_dir,
            start=_parse_date(start),
            end=_parse_date(end),
            initial_cash=initial_cash,
            fee_rate=fee_rate,
            sell_tax_rate=sell_tax_rate,
            **params,
        )
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc
    except ValueError as exc:
        raise typer.BadParameter(str(exc)) from exc

    typer.echo(f"strategy={strategy}  security_id={security_id}  fee={fee_rate}  sell_tax={sell_tax_rate}")
    if strategy == "golden_cross":
        typer.echo(f"fast={fast}  slow={slow}")
    elif strategy == "infinite_buy":
        typer.echo(
            f"splits={splits}  target_pct={target_pct}  big_buy_pct={big_buy_pct}  "
            f"wait_extended={wait_extended}  entry_lookback={entry_lookback}  "
            f"entry_pullback_pct={entry_pullback_pct}"
        )

    if strategy == "infinite_buy":
        report = format_infinite_buy_report(summarize_infinite_buy(result))
        typer.echo("")
        typer.echo(report)
    else:
        summary = summarize(result)
        typer.echo(f"bars={summary['bars']}  trades={summary['trade_count']}")
        typer.echo(f"initial_cash={summary['initial_cash']:,.0f}")
        typer.echo(f"final_equity={summary['final_equity']:,.0f}  total_return={_pct(float(summary['total_return']))}")
        typer.echo(f"buy_hold_return={_pct(float(summary['buy_hold_return']))}  max_drawdown={_pct(float(summary['max_drawdown']))}")
    if not result.trades.empty:
        typer.echo("")
        if strategy == "infinite_buy":
            typer.echo(format_infinite_buy_fills(infinite_buy_fills(result)))
        else:
            typer.echo(result.trades.to_string(index=False))


if __name__ == "__main__":
    app()
