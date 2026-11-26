# outfit-data

"오늘 뭐 입지" 앱의 **뉴스·증시** 탭에 쓰는 데이터를 만드는 저장소예요.

- `build.py` — 무료 공개 데이터만 모아서 `news.json`, `market.json` 을 만들어요 (파이썬 표준 라이브러리만 사용).
- GitHub Actions가 15분마다 실행해서 결과를 **`data` 브랜치**에 올려요 (커밋 1개로 덮어써서 기록이 쌓이지 않아요).
- 앱은 `https://raw.githubusercontent.com/bottleman-bang/outfit-data/data/market.json` 처럼 읽어요.

## 데이터 출처 (모두 무료)
| 구분 | 출처 |
|---|---|
| 국내·해외 지수, 환율, 금리, 원자재, 국내 순위·투자자 동향 | 네이버 증권 |
| 미국 종목(마켓맵·순위), 실적 발표 일정 | Nasdaq |
| 코인 | CoinGecko, Upbit, alternative.me(공포탐욕) |
| 경제 일정 | ForexFactory |
| 뉴스 | Bloomberg·CNBC·FT·WSJ·MarketWatch·CoinDesk·Federal Reserve·The Economist RSS, Google 뉴스(Reuters 등 공신력 있는 매체만), 연합뉴스·매일경제 RSS |
| 요약·번역 | GitHub Models (GITHUB_TOKEN, 무료 한도) → 실패 시 무료 번역 + 규칙 기반 요약 |

개인적인 비상업 용도예요. 기사 원문 저작권은 각 언론사에 있어요.

## 자동 실행 켜기
`setup/update.yml` 내용을 `.github/workflows/update.yml` 로 만들면 15분마다 자동으로 돌아요.
