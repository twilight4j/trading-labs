from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from backtest.analytics import plot_backtest, summarize
from backtest.data import load_price_series
from backtest.strategies import available_strategies, get_strategy

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


def _default_plot_path(security_id: str, strategy: str) -> Path:
    safe = security_id.replace(":", "_")
    return Path("backtest_plots") / f"{safe}_{strategy}.png"


@app.command("run")
def run(
    strategy: str = typer.Option("golden_cross", help=f"등록 전략: {', '.join(available_strategies())}"),
    security_id: str = typer.Option("KRX:005930"),
    fast: int = typer.Option(50, min=1),
    slow: int = typer.Option(200, min=2),
    start: str | None = typer.Option(None, help="YYYY-MM-DD"),
    end: str | None = typer.Option(None, help="YYYY-MM-DD"),
    data_dir: Path = typer.Option(Path("data/market-data")),
    initial_cash: float = typer.Option(10_000_000.0),
    fee_rate: float = typer.Option(0.0015, help="편도 수수료+슬리피지 비율"),
    plot: bool = typer.Option(False, "--plot", help="결과 그래프 PNG 저장"),
    plot_path: Path | None = typer.Option(None, help="PNG 경로 (기본: backtest_plots/<id>_<strategy>.png)"),
    show_plot: bool = typer.Option(False, "--show-plot", help="그래프 창으로 표시"),
) -> None:
    """등록된 전략으로 단일 종목 백테스트를 실행합니다."""
    if strategy == "golden_cross" and fast >= slow:
        raise typer.BadParameter("fast must be < slow")

    try:
        params: dict[str, object] = {}
        if strategy == "golden_cross":
            params = {"fast": fast, "slow": slow}
        strat = get_strategy(strategy, **params)
    except KeyError as exc:
        raise typer.BadParameter(str(exc)) from exc

    prices = load_price_series(
        data_dir,
        security_id,
        start=_parse_date(start),
        end=_parse_date(end),
    )
    result = strat.run(prices, initial_cash=initial_cash, fee_rate=fee_rate)
    summary = summarize(result)

    typer.echo(f"strategy={strategy}  security_id={security_id}  fee={fee_rate}")
    if strategy == "golden_cross":
        typer.echo(f"fast={fast}  slow={slow}")
    typer.echo(f"bars={summary['bars']}  trades={summary['trade_count']}")
    typer.echo(f"initial_cash={summary['initial_cash']:,.0f}")
    typer.echo(f"final_equity={summary['final_equity']:,.0f}  total_return={_pct(float(summary['total_return']))}")
    typer.echo(f"buy_hold_return={_pct(float(summary['buy_hold_return']))}  max_drawdown={_pct(float(summary['max_drawdown']))}")
    if not result.trades.empty:
        typer.echo("")
        typer.echo(result.trades.to_string(index=False))

    if plot or show_plot or plot_path is not None:
        if plot_path is not None:
            output: Path | None = plot_path
        elif plot:
            output = _default_plot_path(security_id, strategy)
        else:
            output = None
        saved = plot_backtest(
            result,
            security_id=security_id,
            strategy=strategy,
            fast=fast if strategy == "golden_cross" else None,
            slow=slow if strategy == "golden_cross" else None,
            output_path=output,
            show=show_plot,
        )
        if saved is not None:
            typer.echo(f"\nplot saved: {saved}")


if __name__ == "__main__":
    app()
