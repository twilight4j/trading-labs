from __future__ import annotations

from datetime import date
from pathlib import Path

import typer

from collector.config import Settings, load_environment
from collector.ingestion.adjusted import AdjustedPricesService
from collector.ingestion.fundamentals import FundamentalsService
from collector.ingestion.scheduler import serve as run_scheduler
from collector.ingestion.service import IngestionService
from collector.providers import DartQuotaExceeded
from collector.quality import validate_prices
from collector.storage import Lakehouse

load_environment()

app = typer.Typer(help="KRX 전 종목 데이터 수집 CLI")
fundamentals_app = typer.Typer(help="OpenDART 주요계정 수집 (일봉 파이프라인과 분리)")
prices_app = typer.Typer(help="일봉 수정주가 재구축 (일별 raw 수집과 분리)")
app.add_typer(fundamentals_app, name="fundamentals")
app.add_typer(prices_app, name="prices")


def _settings(data_dir: Path) -> Settings:
    return Settings(data_dir=data_dir)


def _parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise typer.BadParameter("YYYY-MM-DD 형식이어야 합니다.") from exc


@app.command()
def backfill(
    start: str = typer.Option("2010-01-01"),
    end: str = typer.Option(date.today().isoformat()),
    data_dir: Path = typer.Option(Path("data/market-data")),
) -> None:
    runs = IngestionService(_settings(data_dir)).backfill(_parse_date(start), _parse_date(end))
    typer.echo(f"{len(runs)}개 거래일 수집 완료")


@app.command()
def update(data_dir: Path = typer.Option(Path("data/market-data"))) -> None:
    run = IngestionService(_settings(data_dir)).update()
    typer.echo("갱신할 거래일이 없습니다." if run is None else f"완료: {run.run_id} ({run.rows_written}행)")


@app.command()
def validate(date_: str = typer.Option(..., "--date"), data_dir: Path = typer.Option(Path("data/market-data"))) -> None:
    target_date = _parse_date(date_)
    prices = Lakehouse(_settings(data_dir)).read_curated("daily_prices")
    subset = prices[prices["trade_date"].astype(str).str.startswith(target_date.isoformat())]
    _, issues = validate_prices(subset)
    typer.echo(f"검사 행: {len(subset)}, 오류: {len(issues)}")
    for issue in issues:
        typer.echo(f"[{issue.severity}] {issue.check}: {issue.message}")


@app.command()
def serve(data_dir: Path = typer.Option(Path("data/market-data"))) -> None:
    run_scheduler(_settings(data_dir))


@prices_app.command("rebuild-adjusted")
def prices_rebuild_adjusted(
    start: str = typer.Option("2010-01-01"),
    end: str = typer.Option(date.today().isoformat()),
    security_id: list[str] | None = typer.Option(None, "--security-id", help="예: KRX:005930. 미지정 시 eligible 마스터 전체"),
    limit: int | None = typer.Option(None, "--limit", help="스모크용 종목 수 제한"),
    data_dir: Path = typer.Option(Path("data/market-data")),
) -> None:
    """종목별 수정주가를 받아 curated daily_prices의 *_adjusted 컬럼을 채웁니다."""
    run = AdjustedPricesService(_settings(data_dir)).rebuild(
        _parse_date(start),
        _parse_date(end),
        security_ids=security_id,
        limit=limit,
    )
    typer.echo(f"수정주가 재구축 완료: {run.run_id} ({run.rows_written}행)")


@fundamentals_app.command("sync-corp-codes")
def fundamentals_sync_corp_codes(data_dir: Path = typer.Option(Path("data/market-data"))) -> None:
    master = FundamentalsService(_settings(data_dir)).sync_corp_codes()
    matched = int(master["dart_corp_code"].notna().sum())
    typer.echo(f"dart_corp_code 매핑 완료: {matched}/{len(master)}")


@fundamentals_app.command("backfill")
def fundamentals_backfill(
    start_year: int = typer.Option(2020, "--start-year"),
    end_year: int = typer.Option(date.today().year, "--end-year"),
    reprt_code: list[str] | None = typer.Option(None, "--reprt-code", help="보고서 코드. 미지정 시 전체(11011~11014)"),
    limit: int | None = typer.Option(None, "--limit", help="스모크용 종목 수 제한"),
    skip_existing: bool = typer.Option(True, "--skip-existing/--no-skip-existing", help="완료 curated 파티션 건너뛰기"),
    data_dir: Path = typer.Option(Path("data/market-data")),
) -> None:
    codes = tuple(reprt_code) if reprt_code else None
    try:
        runs = FundamentalsService(_settings(data_dir)).backfill(
            start_year, end_year, codes, limit=limit, skip_existing=skip_existing
        )
    except DartQuotaExceeded as exc:
        rows = sum(run.rows_written for run in exc.completed_runs)
        typer.echo(
            f"OpenDART 일일 한도 초과로 중단: 완료 {len(exc.completed_runs)}개 파티션, {rows}행. "
            "완료분은 유지됩니다. 한도 리셋 후 같은 명령으로 재개하세요(--skip-existing 기본)."
        )
        raise typer.Exit(code=2) from exc
    rows = sum(run.rows_written for run in runs)
    typer.echo(f"재무 수집 완료: {len(runs)}개 파티션, {rows}행")


@fundamentals_app.command("update")
def fundamentals_update(
    year: int = typer.Option(date.today().year, "--year"),
    reprt_code: list[str] | None = typer.Option(None, "--reprt-code", help="보고서 코드. 미지정 시 전체(11011~11014)"),
    limit: int | None = typer.Option(None, "--limit", help="스모크용 종목 수 제한"),
    skip_existing: bool = typer.Option(False, "--skip-existing/--no-skip-existing", help="완료 curated 파티션 건너뛰기"),
    data_dir: Path = typer.Option(Path("data/market-data")),
) -> None:
    codes = tuple(reprt_code) if reprt_code else None
    try:
        runs = FundamentalsService(_settings(data_dir)).update(
            year, reprt_codes=codes, limit=limit, skip_existing=skip_existing
        )
    except DartQuotaExceeded as exc:
        rows = sum(run.rows_written for run in exc.completed_runs)
        typer.echo(
            f"OpenDART 일일 한도 초과로 중단: 완료 {len(exc.completed_runs)}개 파티션, {rows}행. "
            "완료분은 유지됩니다. 한도 리셋 후 다시 실행하세요."
        )
        raise typer.Exit(code=2) from exc
    rows = sum(run.rows_written for run in runs)
    typer.echo(f"재무 갱신 완료: {len(runs)}개 파티션, {rows}행")


if __name__ == "__main__":
    app()
