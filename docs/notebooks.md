---
type: Guide
title: 노트북 워크벤치
description: Jupyter에서 백테스트를 실행하고 전략을 패키지로 승격하는 경로.
tags: [backtest, notebook]
status: stable
generated: { by: agent/cursor, at: 2026-08-16T07:00:00Z }
---

# 개요

노트북은 실험 면입니다. 안정된 전략은 `src/backtest/strategies/`가 소스 오브 트루스입니다. CLI와 노트북은 같은 `run_backtest()`를 호출합니다.

이 슬라이스에 **없는 것:** 무한매수법 구현, `run_bar_by_bar` 일반화, 미국 ETF 수집, ipywidgets.

가정·엔진 한계는 [토이 백테스트](/docs/backtest.md)를 보세요.

# 설치

```bash
uv sync --group dev --group notebook
```

- Cursor: 커널로 프로젝트 `.venv` (`/.venv/bin/python`)를 고릅니다. 별도 `--user` 커널 등록은 필요 없습니다.
- 브라우저: `uv run jupyter lab`

`sys.path`를 손으로 넣지 마세요. editable install로 `import backtest`가 됩니다.

# 노트북

| 경로 | 역할 |
|------|------|
| [notebooks/golden_cross.ipynb](/notebooks/golden_cross.ipynb) | `run_backtest` 레퍼런스 런 |
| [notebooks/universe_golden_cross.ipynb](/notebooks/universe_golden_cross.ipynb) | 시총 유니버스 배치·종목/기간 분석 |
| [notebooks/templates/strategy_scratch.ipynb](/notebooks/templates/strategy_scratch.ipynb) | 새 전략 실험 (경로 A/B) |

**데이터 전제:** `data/market-data/curated/daily_prices/`가 있어야 합니다.

Cursor 노트북의 cwd는 `notebooks/`입니다. `Path("data/market-data")`는 저장소 루트 기준으로 해석됩니다. 커널을 재시작한 뒤 셀을 다시 실행하세요.

```bash
uv run market-data backfill --start 2015-01-01
# 스모크
uv run market-data backfill --start 2026-07-20 --end 2026-07-20 --data-dir data/market-data/test
```

# `run_backtest`

```python
from datetime import date
from pathlib import Path

from backtest import plot_backtest, run_backtest, summarize

result = run_backtest(
    "golden_cross",
    "KRX:005930",
    data_dir=Path("data/market-data"),
    start=date(2015, 1, 1),
    fast=50,
    slow=200,
)
summarize(result)
plot_backtest(result, security_id="KRX:005930", show=True)
```

`**strategy_params`는 등록 전략 생성자에 그대로 전달됩니다. 로드·실행은 CLI `backtest run`과 동일합니다.

# 유니버스 분석

```python
from datetime import date
from backtest import list_universe, run_universe_backtest

universe = list_universe(as_of=date(2026, 7, 30), min_market_cap=100_000_000_000)
panel = run_universe_backtest("golden_cross", universe, start=date(2015, 1, 1), fast=50, slow=200)
panel.summaries  # excess_return, max_drawdown, effective
```

효과: buy&hold 대비 초과수익이 양수이고 MDD가 `mdd_limit`(기본 -30%)보다 얕음. 시총 단위는 원. 기준일 시총으로 과거를 돌리면 생존편향. 결과는 `save_run_panel` / `load_run_panel`로 `backtest_runs/`에 둘 수 있습니다.

# 승격 규약

1. `notebooks/templates/strategy_scratch.ipynb`에서 실험합니다.
2. **경로 A** (롱 온리, 전량, 다음 봉 시가): `golden_cross`/`death_cross` 컬럼을 만들고 `run_bar_by_bar`를 씁니다.
3. **경로 B** (분할·지정가·상태머신 등): 커스텀 루프로 `BacktestResult`를 조립합니다. 무한매수법은 이 경로입니다.
4. `src/backtest/strategies/<name>.py`에 `Strategy`를 구현하고 `STRATEGIES`에 등록합니다.
5. synthetic DataFrame 테스트를 추가합니다.
6. 노트북은 `run_backtest("<name>", ...)` 러너로 줄입니다.

경로 B equity/trades 컬럼은 엔진 출력과 맞춥니다. 공유 엔진을 쓰지 않으면 `prepare()`가 시그널 컬럼을 만들 필요가 없습니다.

투자 조언을 제공하지 않습니다.
