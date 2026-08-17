---
type: Guide
title: 백테스트
description: 단일 종목 전략 플러그인 백테스트 가정·실행·한계.
tags: [backtest, golden-cross]
status: stable
generated: { by: agent/cursor, at: 2026-08-09T08:34:00Z }
---

# 개요

단일 종목 전략을 curated 일봉으로 돌려 보는 학습용 엔진입니다. 전략은 `strategies/`에 플러그인으로 추가합니다. 패키지·데이터 경로는 [프로젝트 구조](/docs/structure.md), 수정주가 재구축은 [데이터 흐름](/docs/flow.md)을 보세요.

# 패키지 구조

```text
src/backtest/
  api.py              # run_backtest, run_universe_backtest
  cli.py              # backtest run --strategy ...
  data/prices.py      # curated 로드 (단일·패널)
  data/universe.py    # 기준일 시총 유니버스
  core/               # BacktestResult, RunPanel, run_bar_by_bar
  strategies/         # Strategy protocol + registry
  analytics/          # metrics, plot, cross_section
```

# 가정 (golden_cross)

| 항목 | 내용 |
|------|------|
| 신호 | 종가 기준 단기 SMA가 장기 SMA를 상향 돌파(골든) / 하향 돌파(데드) |
| 체결 | 신호일 `t` 확정 → **다음 거래일 시가**에 매수·매도 (룩어헤드 방지) |
| 포지션 | 현금 ↔ 전량 보유 (롱 온리, 1포지션) |
| 비용 | 편도 `fee_rate`(기본 0.15%)만 반영. 세금·호가·미반영 |
| 가격 | `close_adjusted` 우선, 없으면 `close_raw` |

수정주가가 비어 있으면(액면분할 왜곡):

```bash
uv run market-data prices rebuild-adjusted --security-id KRX:005930 --start 2015-01-01
```

# Examples

```bash
uv sync --group dev
uv run backtest run --strategy golden_cross --security-id KRX:005930 --fast 50 --slow 200 --start 2015-01-01

# 그래프 저장 (가격+SMA+매매 / 자산곡선 vs buy&hold)
uv run backtest run --security-id KRX:005930 --start 2015-01-01 --plot
uv run backtest run --security-id KRX:005930 --plot-path reports/samsung.png --show-plot
```

노트북: [golden_cross.ipynb](/notebooks/golden_cross.ipynb), 유니버스 분석은 [universe_golden_cross.ipynb](/notebooks/universe_golden_cross.ipynb). 설치·승격은 [노트북 워크벤치](/docs/notebooks.md)를 보세요.

주요 옵션: `--strategy`, `--data-dir`, `--end`, `--initial-cash`, `--fee-rate`, `--plot`, `--plot-path`, `--show-plot`.

`--plot`만 주면 `backtest_plots/<security_id>_<strategy>.png`에 저장합니다. 기본 `--data-dir`는 `data/market-data`입니다.

# 유니버스 배치

`list_universe(as_of, min_market_cap)` → `run_universe_backtest`. `market_cap`은 **원**. 기본 하한 1,000억.

효과: `excess_return > 0` 그리고 `max_drawdown >= mdd_limit`(기본 -30%). 기준일 시총으로 과거를 돌리면 생존편향이 있습니다. PIT는 `as_of`를 백테스트 시작일에 맞춥니다. `as_of`가 휴일이면 그 이전 마지막 거래일을 씁니다. 업종은 마스터에 없습니다.

# 한계

- 생존편향·상장폐지·거래정지 미처리 (유니버스 `as_of`가 최근이면 과거 구간은 생존편향)
- 포트폴리오 동시보유·파라미터 탐색은 범위 밖
- 수정주가가 비어 있으면 raw 종가로 대체되므로 분할 구간 왜곡 가능
- 시가·종가가 0 이하인 봉(휴장·결측성 데이터)은 로드 시 제외

투자 조언을 제공하지 않습니다.
