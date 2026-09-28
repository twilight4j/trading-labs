---
type: Guide
title: 백테스트
description: 단일 종목 전략 플러그인 백테스트 가정·실행·한계.
tags: [backtest, golden-cross, infinite-buy]
status: stable
generated: { by: agent/cursor, at: 2026-08-17T23:10:00+09:00 }
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
| 비용 | `fee_rate` 편도 위탁수수료(매수·매도). `sell_tax_rate` 매도세(기본 0). 호가·슬리피지 미반영 |
| 가격 | `close_adjusted` 우선, 없으면 `close_raw` |

# 가정 (infinite_buy)

무한매수법 V4. 주문·T 규칙은 [script.js](/docs/strategies/무한매수법/script.js), 개념은 [가이드](/docs/strategies/무한매수법/무한매수법.md). 공유 엔진 대신 커스텀 `run()` (경로 B).

**사이클 시작 시 한 번:** `splits`, `initial_cash`, `big_buy_pct`, `target_pct`. **매일 갱신:** 보유수량·평단 (체결로 계산), T, P, 모드.

| 항목 | 내용 |
|------|------|
| 주문 | 전일 종가 후 확정 → 당일 OHLC 체결. **백테스트 시작일 첫 매수는 당일 종가에 무조건 체결** (큰수는 수량 산정) |
| 별%(P) | `target_pct - (target_pct / (n/2)) * T`. 쿼터 LOC만 사용 |
| 지정가 3/4 | 사이클 시작 `target_pct` 고정. `high`가 닿으면 지정가 체결 |
| 큰수 | 매일 `전일종가 * (1+big_buy_pct)`가 매수 한계 상한 |
| 대폭락 티어 | `1회매수금 / (기본수량+k)` +1주, 최대 5단, 큰수 미만 |
| 리버스 | `T > n-1` 다음 봉 MOC 1/(n/2). 이후 SMA5 LOC. 매도 시 `T*(1-2/n)` |
| 복리 | 보유 0이면 다음 봉부터 종료 잔액을 새 원금으로 첫 매수 |
| WAIT | 옵션. `wait_extended=True`일 때만, 무포지션에서 N일 고점 대비 조정이 부족하면 `first_buy`를 쉼. 기본 꺼짐 |
| 수량 | `floor`. 별지점 − tick (기본 1원) |
| 비용 | `fee_rate` 편도 위탁수수료(매수·매도). `sell_tax_rate` 매도세(코스피/코스닥 0.20%=`0.002`, ETF 0) |

KRX 가격제한은 `price_limit_pct`(기본 30%)로 클립합니다. 미국 ETF 로더는 없습니다. 3배 레버리지 가정은 KRX 일봉에도 그대로 적용되므로 계수(`target_pct`)를 종목에 맞게 넣으세요.

# 무한매수법 정량 리포트

`summarize_infinite_buy(result)` / `format_infinite_buy_report(...)`. CLI `infinite_buy`와 [infinite_buy.ipynb](/notebooks/infinite_buy.ipynb)가 같은 텍스트를 출력합니다. 미종료 사이클은 마지막 종가로 평가합니다. 복리가 엔진 기본입니다. 배당 현금흐름은 없습니다.

| 항목 | 정의 |
|------|------|
| 평가 수익률 | `(final_equity - initial_cash) / initial_cash` |
| 최대 투입액 | `max(shares * avg_price)`, 가동률은 원금 대비 |
| 투입액 대비 | 손익 / 최대 투입액 |
| 사이클 완료 | 보유가 양수에서 0이 된 횟수 |
| 재투자 | 최종 사이클 원금 − 시작 원금 |
| 최종 사이클 원금 | 그날 `principal` (복리 반영) |
| 수수료 | `trades.fee` 합 (위탁수수료) |
| 세금 | `trades.tax` 합 (매도세, 매수는 0) |
| 매수/매도 | 체결 건수 (`trades.side`) |
| 경과 일수 | 첫날~마지막날 달력 일수 (`end - start`) |
| MDD 구간 | 평가액 고점일 ~ 그 낙폭의 저점일 |
| 물밀 | 보유 중 `close < avg_price`. 평단 회복 = 최장 연속 구간 |
| 단순보유 | 시작일 종가 전량, 수수료 없음. 알파 = 전략 손익 − 단순보유 손익 |

일별 평가는 `style_infinite_buy_equity(result.equity)` (원본 영문 컬럼은 그대로). 체결 이력은 `infinite_buy_fills(result)` / `style_infinite_buy_fills(...)`. 투입 = 남은 보유 매입원가(수수료 제외). 평가손익 = 평가금 − 그날 사이클 원금. 배당 없음. 사이클 완료 행 아래에 구분선. 리버스·물밀(종가 < 평단)은 빨강.

수정주가가 비어 있으면(액면분할 왜곡):

```bash
uv run market-data prices rebuild-adjusted --security-id KRX:005930 --start 2015-01-01
```

# Examples

```bash
uv sync --group dev
uv run backtest run --strategy golden_cross --security-id KRX:005930 --fast 50 --slow 200 --start 2015-01-01
uv run backtest run --strategy infinite_buy --security-id KRX:005930 \
  --splits 40 --target-pct 0.15 --big-buy-pct 0.10 --start 2015-01-01
```

그래프·일별 평가·체결 이력은 노트북에서 봅니다: [golden_cross.ipynb](/notebooks/golden_cross.ipynb), [infinite_buy.ipynb](/notebooks/infinite_buy.ipynb). 유니버스 분석은 [universe_golden_cross.ipynb](/notebooks/universe_golden_cross.ipynb). 설치·승격은 [노트북 워크벤치](/docs/notebooks.md)를 보세요.

주요 옵션: `--strategy`, `--data-dir`, `--end`, `--initial-cash`, `--fee-rate`, `--sell-tax-rate`. `infinite_buy`는 `--splits`, `--target-pct`, `--big-buy-pct`. 사이클 재시작 대기는 `--wait-extended` (기본 꺼짐), `--entry-lookback`, `--entry-pullback-pct`.

기본 `--data-dir`는 `data/market-data`입니다. `infinite_buy` 노트북 그래프는 종가·평단·존버 기준가·매도 체결, 사이클 완료 수직선(번호), 리버스 구간 음영을 그립니다.

# 유니버스 배치

`list_universe(as_of, min_market_cap)` → `run_universe_backtest`. `market_cap`은 **원**. 기본 하한 1,000억.

효과: `excess_return > 0` 그리고 `max_drawdown >= mdd_limit`(기본 -30%). 기준일 시총으로 과거를 돌리면 생존편향이 있습니다. PIT는 `as_of`를 백테스트 시작일에 맞춥니다. `as_of`가 휴일이면 그 이전 마지막 거래일을 씁니다. 업종은 마스터에 없습니다.

# 한계

- 생존편향·상장폐지·거래정지 미처리 (유니버스 `as_of`가 최근이면 과거 구간은 생존편향)
- 포트폴리오 동시보유·파라미터 탐색은 범위 밖
- 수정주가가 비어 있으면 raw 종가로 대체되므로 분할 구간 왜곡 가능
- 시가·종가가 0 이하인 봉(휴장·결측성 데이터)은 로드 시 제외
- 무한매수법 일봉 근사: 장중 호가·LOC 부분체결·증권사 거부(큰수 합산 외)는 없음

투자 조언을 제공하지 않습니다.
