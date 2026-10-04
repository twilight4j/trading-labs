# Trading Labs

한국 전 종목 일봉·재무(주요계정) 데이터 수집·보관을 위한 연구용 파이프라인입니다.

**준비**
```bash
uv sync --group dev
cp .env.example .env   # KRX_ID, KRX_PW, DART_API_KEY 입력
```

**노트북 백테스트**
```bash
uv sync --group notebook
uv run jupyter lab
```
커널은 프로젝트 `.venv`를 고릅니다. 예제: [notebooks/golden_cross.ipynb](notebooks/golden_cross.ipynb), 유니버스 분석: [notebooks/universe_golden_cross.ipynb](notebooks/universe_golden_cross.ipynb). 상세는 [docs/notebooks.md](docs/notebooks.md).

**1) backfill (최초·대량 수집)**
```bash
# 일봉
caffeinate -sm uv run market-data backfill --start 2010-01-01

# 재무 — corp 매핑 후, 한도 있으면 연 단위로 끊기
uv run market-data fundamentals sync-corp-codes
caffeinate -sm uv run market-data fundamentals backfill --start-year 2023 --end-year 2023
```

**2) 스케줄 (추가 등록 · 이후 유지)**
```bash
# 일봉(평일 18:30)·컨센서스(토 09:00): labs API 프로세스가 스케줄러를 함께 돌린다 — 하나만 띄운다
caffeinate -sm uv run labs-api serve

# 재무: 분기·공시 후 가끔 (매일 X). 기본=올해
caffeinate -sm uv run market-data fundamentals update
```

**스모크** (`data/market-data/test`)
```bash
uv run market-data backfill --start 2026-07-20 --end 2026-07-20 --data-dir data/market-data/test
uv run market-data fundamentals sync-corp-codes --data-dir data/market-data/test
uv run market-data fundamentals update --year 2025 --limit 3 --data-dir data/market-data/test
```

**3) 가치투자 적정시총·상승여력** — [docs/valuation.md](docs/valuation.md)
```bash
# 컨센서스 스냅샷 (labs-api 가 주 1회 자동 실행, 수동 실행도 가능)
uv run market-data consensus update
# trading-ui용 API (127.0.0.1:8100, Vite 프록시 /api/labs) — .env 의 UI_API_TOKEN 이 있어야 열립니다.
# 위 스케줄과 같은 프로세스다. 화면의 데이터 수집에서 지금 실행·스케줄 켜고 끄기 — docs/collection.md
uv run labs-api serve
```

- 가격(`pykrx`): `.env`의 `KRX_ID` / `KRX_PW`
- 재무(`OpenDART`): `.env`의 `DART_API_KEY`
- 수정주가 재구축: `uv run market-data prices rebuild-adjusted --security-id KRX:005930 --start 2015-01-01`
- 구조·CLI·한도/재개: [docs/](docs/README.md)

투자 조언을 제공하지 않습니다.
