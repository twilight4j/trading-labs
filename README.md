# Trading Labs

한국 주식의 일봉·재무·컨센서스를 모아 두고, 그 데이터로 적정주가를 계산하고 전략을 백테스트하는 연구용 저장소입니다.
trading-ui 의 적정주가 분석·데이터 수집 화면이 쓰는 API 도 여기 있습니다.

| 구성 | 하는 일 |
|---|---|
| 수집 `market-data` | 일봉(pykrx)·재무(OpenDART)·컨센서스(WiseReport)를 `data/market-data` 에 쌓습니다 |
| labs API `labs-api serve` | 적정주가·수집 상태 API(127.0.0.1:8100, 게이트웨이를 거쳐 부릅니다)와 수집 스케줄러를 한 프로세스로 돌립니다 |
| 백테스트 `backtest` | 쌓인 일봉으로 단일 종목 전략을 돌려 봅니다. 노트북으로도 봅니다 |

## Quickstart

Python 3.11+ 와 [uv](https://docs.astral.sh/uv/) 가 필요합니다.

```bash
uv sync --group dev
cp .env.example .env      # 값마다 설명이 파일에 있습니다
uv run labs-api serve     # API 와 수집 스케줄러 — 하나만 띄웁니다
```

데이터가 비어 있으면 먼저 채웁니다. 처음 채우기부터 수동 갱신·백테스트까지의 명령은 [명령 모음](docs/commands.md)에 있습니다.

## 문서

구조와 규칙은 [docs/](docs/index.md)에 있습니다 — 명령 모음, 수집 스케줄, 적정주가 계산, 데이터 흐름, 백테스트.

투자 조언을 제공하지 않습니다.
