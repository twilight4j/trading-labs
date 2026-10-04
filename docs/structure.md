---
type: Reference
title: 프로젝트 구조
description: 디렉터리·모듈 역할과 data/market-data 레이어.
tags: [collector, backtest, structure]
status: stable
generated: { by: agent/cursor, at: 2026-08-09T08:34:00Z }
---

# 디렉터리 개요

```text
trading-labs/
├── docs/                      # 프로젝트 문서 (OKF)
├── src/collector/             # 데이터 수집 패키지
│   ├── cli.py                 # Typer CLI 진입점 (`market-data`)
│   ├── config.py              # Settings (경로·시장·스케줄)
│   ├── models/                # IngestionRun, QualityIssue
│   ├── providers/             # 외부 데이터 공급자
│   ├── transforms/            # 원본 → 정규화 스키마
│   ├── quality/               # 품질 검사·격리
│   ├── storage/               # Parquet lakehouse · DuckDB 카탈로그
│   └── ingestion/             # 일별 수집 오케스트레이션 · 스케줄러
├── src/backtest/              # 토이 백테스트
│   ├── api.py                 # run_backtest · run_universe_backtest
│   ├── cli.py                 # Typer CLI (`backtest`) — 전략 디스패치
│   ├── data/                  # curated 일봉 로드 · 유니버스 필터
│   ├── core/                  # BacktestResult · RunPanel · bar 엔진
│   ├── strategies/            # 전략 플러그인 (golden_cross 등)
│   └── analytics/             # 성과 요약 · 그래프 · 횡단면
├── notebooks/                 # Jupyter 실험 면 (golden_cross · 유니버스 분석)
├── tests/                     # pytest
├── data/                      # 런타임 데이터 루트 (gitignore)
│   └── market-data/           # 시세·재무 lakehouse
│       ├── raw/
│       ├── curated/
│       ├── metadata/
│       └── market_data.duckdb
└── pyproject.toml
```

파이프라인 동작은 [데이터 흐름](/docs/flow.md), 백테스트는 [토이 백테스트](/docs/backtest.md), 노트북은 [노트북 워크벤치](/docs/notebooks.md)를 보세요.

# Collector CLI

`market-data` 스크립트 진입점.

| 명령 | 역할 |
|------|------|
| `backfill` | 기간 내 평일(월–금) 일봉 일괄 수집 |
| `update` | 마지막 거래일 이후 빠진 평일을 모두 갱신(휴장일은 저장하지 않음) |
| `validate` | 특정일 curated 가격에 품질 검사만 수행 |

# `config.Settings`

| 필드 | 기본값 | 설명 |
|------|--------|------|
| `data_dir` | `data/market-data` | 데이터 루트 |
| `markets` | `KOSPI`, `KOSDAQ` | 수집 대상 시장 |
| `schedule_hour` / `schedule_minute` | `18` / `30` | 일봉 스케줄 시각(labs API 프로세스의 스케줄러). 이 시각 전에는 오늘 일봉을 받지 않음 |
| `timezone` | `Asia/Seoul` | 스케줄러 타임존 |

파생 경로: `raw_dir`, `curated_dir`, `metadata_dir`.

# `providers/`

| 모듈 | 클래스 | 역할 |
|------|--------|------|
| `base.py` | `MarketDataProvider` | 일봉·종목마스터 인터페이스 |
| `pykrx.py` | `PykrxProvider` | **가격** 공급자 (OHLCV + 시가총액). `KRX_ID`/`KRX_PW` 로그인 필요 |
| `fdr.py` | `FdrProvider` | **종목 마스터** 공급자 (KRX listing) |
| `dart.py` | `DartProvider` | **재무** 공급자 (corpCode + 주요계정). `DART_API_KEY` 필요 |

# `transforms/`

| 모듈 | 함수 | 역할 |
|------|------|------|
| `prices.py` | `normalize_prices` | 공급자 컬럼 → 안정 스키마 (`security_id`, OHLCV 등) |
| `prices.py` | `combine_raw_and_adjusted` | raw/adjusted OHLC 컬럼 병합 |
| `securities.py` | `normalize_security_master` | 종목 마스터 정규화, ETF·우선주 등 제외 마킹 |
| `fundamentals.py` | `attach_dart_corp_codes` 등 | DART corp 매핑·주요계정 정규화·as-of 조인 |
| `universe.py` | `build_universe` | 당일 가격 ∩ 마스터 → 연구 유니버스 스냅샷 |

# `quality/`

| 모듈 | 역할 |
|------|------|
| `checks.py` | 중복 키·결측·음수·OHLC 범위 검사. 유효 행만 통과 |
| `quarantine.py` | 무효 행을 `raw/quarantine`에 격리 저장 |

# `storage/`

| 모듈 | 클래스 | 역할 |
|------|--------|------|
| `parquet.py` | `Lakehouse` | raw/curated Parquet 쓰기·읽기, metadata JSON 기록 |
| `catalog.py` | `Catalog` | curated Parquet을 DuckDB 뷰로 노출 |

# `ingestion/`

| 모듈 | 역할 |
|------|------|
| `service.py` | `IngestionService` — 일별 수집 오케스트레이션 |
| `fundamentals.py` | `FundamentalsService` — OpenDART 주요계정 (일봉과 분리) |
| `adjusted.py` | `AdjustedPricesService` — 종목별 수정주가로 curated `*_adjusted` 재구축 |
| `scheduler.py` | APScheduler BlockingScheduler로 `update` 주기 실행 |

# `models/`

- `IngestionRun` — 수집 run ID·상태·행 수
- `QualityIssue` — 품질 이슈 (check, severity, message)

# Schema

## 데이터 레이어 (`data/market-data/`)

```text
data/market-data/
├── raw/
│   ├── daily_prices/
│   │   └── trade_date=YYYY-MM-DD/market=KOSPI|KOSDAQ/adjusted=false/run_id=.../
│   ├── quarantine/
│   │   └── trade_date=YYYY-MM-DD/run_id=.../
│   ├── dart_corp_codes/current/run_id=.../
│   └── fundamentals_accounts/
│       └── bsns_year=YYYY/reprt_code=11011|11012|11013|11014/run_id=.../
├── curated/
│   ├── daily_prices/trade_date=YYYY-MM-DD/
│   ├── universe_snapshot/as_of_date=YYYY-MM-DD/
│   ├── security_master/current/
│   └── fundamentals_accounts/bsns_year=YYYY/reprt_code=.../
└── metadata/
    ├── ingestion_runs/{run_id}.json
    └── quality_results/{run_id}.json
```

| 레이어 | 내용 |
|--------|------|
| **raw** | 공급자 원본 보존. run별 파티션 |
| **curated** | 검증·정규화된 연구용 테이블. 파티션 단위 교체(replace) |
| **metadata** | 수집 성공/실패 이력, 품질 이슈 JSON |

`fundamentals_accounts` curated 스키마(long form): `security_id`, `dart_corp_code`, `bsns_year`, `reprt_code`, `fs_div`, `account_id`, `account_nm`, `thstrm_amount`, `frmtrm_amount`, `currency`, `rcept_no`, `source`

투자 조언을 제공하지 않습니다.
