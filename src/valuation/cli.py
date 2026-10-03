from __future__ import annotations

from pathlib import Path

import typer
import uvicorn

from collector.config import Settings
from valuation.api import create_app
from valuation.per import DEFAULT_PER_CONFIG

app = typer.Typer(help="trading-labs 가치투자(적정시총·상승여력) API")


@app.callback()
def main() -> None:
    """trading-ui가 Vite 프록시(/api/labs)로 호출하는 API. 모든 요청에 UI_API_TOKEN 이 필요합니다."""


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1"),
    port: int = typer.Option(8100),
    data_dir: Path = typer.Option(Path("data/market-data")),
    per_config: Path = typer.Option(DEFAULT_PER_CONFIG, help="기준PER 설정 TOML (없으면 전 종목 10)"),
) -> None:
    uvicorn.run(create_app(Settings(data_dir=data_dir), per_config), host=host, port=port)


if __name__ == "__main__":
    app()
