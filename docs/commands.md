---
type: Playbook
title: 명령 모음
description: 준비, 처음 채우기(backfill), 상시 실행, 필요할 때 직접 돌리는 수집, 스모크, 백테스트·노트북, 테스트 — 순서대로 쓰는 명령.
tags: [collector, cli, operation]
status: draft
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-04T07:00:00Z }
---

# 명령 모음

무엇을 언제 치는지만 적습니다. 각 명령이 안에서 하는 일은 [데이터 흐름](flow.md), 옵션은 `--help` 가 원본입니다.

```bash
uv run market-data --help
uv run labs-api --help
uv run backtest --help
```

## 1. 준비

```bash
uv sync --group dev
cp .env.example .env
```

| `.env` | 무엇 |
|---|---|
| `KRX_ID`, `KRX_PW` | KRX 정보데이터시스템 계정 — 일봉·수정주가(pykrx) |
| `DART_API_KEY` | OpenDART 키 — 재무 |
| `UI_API_TOKEN` | labs API 토큰. trading-engine 의 `UI_API_TOKEN` 과 같은 값(16자 이상). 없으면 API 가 모든 요청을 거부합니다 |

데이터는 `data/market-data` 에 쌓입니다(git 에 올리지 않습니다). 다른 곳에 두려면 명령마다 `--data-dir`.

## 2. 처음 채우기 (한 번)

오래 걸리므로 맥이 잠들지 않게 `caffeinate -sm` 으로 감쌉니다.

```bash
# 일봉 — 평일마다 하루씩. 휴장일은 저장하지 않습니다
caffeinate -sm uv run market-data backfill --start 2010-01-01

# 재무 — 종목코드 매핑을 먼저. OpenDART 일일 한도가 있어 연 단위로 끊습니다
uv run market-data fundamentals sync-corp-codes
caffeinate -sm uv run market-data fundamentals backfill --start-year 2023 --end-year 2023

# 컨센서스 — 오늘 날짜 스냅샷(약 10분). 적정주가에 필요합니다
uv run market-data consensus update
```

재무가 한도에 걸려 멈추면 끝난 부분은 남습니다. 한도가 풀린 뒤 같은 명령을 다시 실행하면 이어서 받습니다.

## 3. 상시 실행

```bash
uv run labs-api serve        # 127.0.0.1:8100
```

이 프로세스 하나가 API 와 수집 스케줄러를 함께 돌립니다 — 평일 18:30 일봉, 토요일 09:00 컨센서스. **하나만 띄웁니다**(둘이면 수집이 두 번 돕니다).

- 이 맥에서는 trading-engine 저장소의 launchd 서비스 `labs-api` 가 띄웁니다. 따로 실행하지 않습니다.
- 스케줄 켜고 끄기와 "지금 실행"은 trading-ui 의 데이터 수집 화면에서 합니다.
- 규칙은 [수집 스케줄과 화면에서의 실행](collection.md).

## 4. 필요할 때 직접

화면에서도 되는 것(일봉·컨센서스·재무)을 명령으로 돌리거나, 화면에 없는 것을 돌립니다.

```bash
uv run market-data update                         # 일봉 — 빠진 거래일을 모두 채웁니다(18:30 전에는 어제까지)
uv run market-data consensus update               # 컨센서스 — 오늘 날짜 스냅샷
caffeinate -sm uv run market-data fundamentals update   # 재무 — 올해 보고서 재수집. 분기·공시 뒤에 가끔
uv run market-data validate --date 2026-10-02     # 그날 일봉의 품질 검사만(쓰지 않습니다)
```

**수정주가** — 스케줄도 화면 실행도 없습니다. 백테스트만 쓰므로, 어떤 종목을 백테스트하기 전이나 그 종목에 액면분할 같은 이벤트가 생긴 뒤에 그 종목 것만 받습니다.

```bash
uv run market-data prices rebuild-adjusted --security-id KRX:005930 --start 2015-01-01
```

화면에서 실행 중인 작업을 명령으로 또 돌리지 않습니다. 명령은 labs API 와 다른 프로세스라 서로 막아 주지 않습니다.

## 5. 스모크

실제 데이터를 건드리지 않고 작은 범위로 돌려 봅니다(`data/market-data/test`).

```bash
uv run market-data backfill --start 2026-07-20 --end 2026-07-20 --data-dir data/market-data/test
uv run market-data fundamentals sync-corp-codes --data-dir data/market-data/test
uv run market-data fundamentals update --year 2025 --limit 3 --data-dir data/market-data/test
uv run market-data consensus update --limit 5 --data-dir data/market-data/test
```

## 6. 백테스트와 노트북

> **2026-10-04 현재 이 저장소에서는 실행되지 않습니다.** `backtest` 명령과 노트북이 부르는 `backtest.data` 모듈(`src/backtest/data/`)이 git 에 없습니다. `.gitignore` 의 `data` 규칙이 데이터 폴더뿐 아니라 그 소스 폴더까지 무시해서 한 번도 커밋되지 않았습니다. 모듈을 되살리고 규칙을 루트의 `/data` 로 좁혀야 합니다.

```bash
uv run backtest run --strategy golden_cross --security-id KRX:005930 --fast 50 --slow 200 --start 2015-01-01

uv sync --group dev --group notebook
uv run jupyter lab           # 커널은 프로젝트 .venv
```

가정과 옵션은 [토이 백테스트](backtest.md), 노트북 쓰는 법은 [노트북 워크벤치](notebooks.md).

## 7. 테스트

```bash
uv run --group dev pytest
```

위와 같은 이유로 백테스트 테스트 네 파일(`tests/test_backtest_*.py`)은 수집 단계에서 실패합니다. 나머지만 돌리려면 파일마다 `--ignore=tests/test_backtest_api.py` 처럼 뺍니다(수집·적정주가·API 테스트 64개).

투자 조언을 제공하지 않습니다.
