# outfit-data

"모닝픽" 앱의 **뉴스·증시·Daily Up** 탭에 쓰는 데이터를 만드는 저장소예요.

- `build.py` — 무료 공개 데이터만 모아서 `news.json`, `market.json`, `daily.json` 을 만들어요 (파이썬 표준 라이브러리만 사용).
- `daily.json` — 💬 Talk Pick(영어 질문 중급·중상급 + 단어·문법 해설·모범 답안·선생님 노트)과 🥄 AI 한 스푼을 매일 아침 6시(한국 시간) 이후 한 번 만들어요. 최근 14일치를 보관해요.
- GitHub Actions가 약 15분마다 실행해서 결과를 **`data` 브랜치**에 올려요 (커밋 1개로 덮어써서 기록이 쌓이지 않아요).
  - GitHub의 예약 실행(cron)은 자주 밀리거나 빠져서, 실행이 끝날 때 **다음 실행을 직접 예약**하고 `cadence` 환경의 대기 시간(14분)만큼 기다렸다 시작하는 방식이에요. cron은 1시간마다 끊긴 반복을 다시 잇는 예비용이에요.
  - 새 저장소에 설치할 때는 대기 환경을 한 번 만들어 주세요: `gh api -X PUT repos/<저장소>/environments/cadence -F wait_timer=14` (최신 설정 파일: `setup/update.yml`)
- 앱은 `https://raw.githubusercontent.com/bottleman-bang/outfit-data/data/market.json` 처럼 읽어요.

## 데이터 출처 (모두 무료)
| 구분 | 출처 |
|---|---|
| 국내·해외 지수, 환율, 금리, 원자재, 국내 순위·투자자 동향 | 네이버 증권 |
| 미국 종목(마켓맵·순위), 실적 발표 일정 | Nasdaq |
| 코인 | CoinGecko, Upbit, alternative.me(공포탐욕) |
| 경제 일정 | ForexFactory |
| 뉴스 | Bloomberg·CNBC·FT·WSJ·MarketWatch·CoinDesk·Federal Reserve·The Economist RSS, Google 뉴스(Reuters 등 공신력 있는 매체만), 연합뉴스·매일경제 RSS |
| 요약·번역 | 무료 번역 + 규칙 기반 요약 · (선택) 무료 Gemini API 키를 `GEMINI_API_KEY` 시크릿으로 넣으면 AI 요약 |
| 경제노트·시장 해설·Talk Pick·AI 한 스푼 | 무료 Gemini API (`GEMINI_API_KEY` 시크릿) |
| 영어 첨삭 (앱에서 실시간) | Pollinations 무료 공개 AI (키 없음, 한 곳에서 45초에 1번) |

개인적인 비상업 용도예요. 기사 원문 저작권은 각 언론사에 있어요.

## 자동 실행 켜기 (한 번만)
### 👉 [여기를 눌러서 자동 업데이트 켜기](https://github.com/bottleman-bang/outfit-data/new/main?filename=.github/workflows/update.yml&value=name%3A%20%EB%89%B4%EC%8A%A4%C2%B7%EC%A6%9D%EC%8B%9C%20%EB%8D%B0%EC%9D%B4%ED%84%B0%20%EC%97%85%EB%8D%B0%EC%9D%B4%ED%8A%B8%0Aon%3A%0A%20%20schedule%3A%0A%20%20%20%20-%20cron%3A%20%27%2A/15%20%2A%20%2A%20%2A%20%2A%27%20%20%20%23%2015%EB%B6%84%EB%A7%88%EB%8B%A4%0A%20%20workflow_dispatch%3A%20%20%20%20%20%20%20%20%20%20%23%20%EC%88%98%EB%8F%99%20%EC%8B%A4%ED%96%89%20%EB%B2%84%ED%8A%BC%0Apermissions%3A%0A%20%20contents%3A%20write%20%20%20%23%20data%20%EB%B8%8C%EB%9E%9C%EC%B9%98%EC%97%90%20%EA%B2%B0%EA%B3%BC%20%EC%98%AC%EB%A6%AC%EA%B8%B0%0A%20%20actions%3A%20write%20%20%20%20%23%20%EC%98%88%EC%95%BD%20%EC%8B%A4%ED%96%89%EC%9D%B4%20%EA%BA%BC%EC%A7%80%EC%A7%80%20%EC%95%8A%EA%B2%8C%20%EC%9C%A0%EC%A7%80%0Aconcurrency%3A%0A%20%20group%3A%20update-data%0A%20%20cancel-in-progress%3A%20false%0Ajobs%3A%0A%20%20update%3A%0A%20%20%20%20runs-on%3A%20ubuntu-latest%0A%20%20%20%20timeout-minutes%3A%2010%0A%20%20%20%20steps%3A%0A%20%20%20%20%20%20-%20uses%3A%20actions/checkout%40v4%0A%20%20%20%20%20%20-%20name%3A%20%EC%9D%B4%EC%A0%84%20%EC%BA%90%EC%8B%9C%20%EA%B0%80%EC%A0%B8%EC%98%A4%EA%B8%B0%20%28%EB%B2%88%EC%97%AD%C2%B7%EC%9A%94%EC%95%BD%20%EC%9E%AC%EC%82%AC%EC%9A%A9%29%0A%20%20%20%20%20%20%20%20run%3A%20%7C%0A%20%20%20%20%20%20%20%20%20%20mkdir%20-p%20out%0A%20%20%20%20%20%20%20%20%20%20curl%20-sfL%20%22https%3A//raw.githubusercontent.com/%24%7B%7B%20github.repository%20%7D%7D/data/cache.json%22%20-o%20out/cache.json%20%7C%7C%20echo%20%27%7B%7D%27%20%3E%20out/cache.json%0A%20%20%20%20%20%20-%20name%3A%20%EB%89%B4%EC%8A%A4%C2%B7%EC%A6%9D%EC%8B%9C%20%EB%8D%B0%EC%9D%B4%ED%84%B0%20%EB%A7%8C%EB%93%A4%EA%B8%B0%0A%20%20%20%20%20%20%20%20env%3A%0A%20%20%20%20%20%20%20%20%20%20GEMINI_API_KEY%3A%20%24%7B%7B%20secrets.GEMINI_API_KEY%20%7D%7D%20%20%20%23%20%28%EC%84%A0%ED%83%9D%29%20%EB%84%A3%EC%9C%BC%EB%A9%B4%20AI%20%EC%9A%94%EC%95%BD%EC%9D%B4%20%EC%BC%9C%EC%A0%B8%EC%9A%94%0A%20%20%20%20%20%20%20%20run%3A%20python3%20build.py%20out%0A%20%20%20%20%20%20-%20name%3A%20data%20%EB%B8%8C%EB%9E%9C%EC%B9%98%EC%97%90%20%EC%98%AC%EB%A6%AC%EA%B8%B0%20%28%EA%B8%B0%EB%A1%9D%EC%9D%B4%20%EC%8C%93%EC%9D%B4%EC%A7%80%20%EC%95%8A%EA%B2%8C%201%EA%B0%9C%20%EC%BB%A4%EB%B0%8B%EC%9C%BC%EB%A1%9C%20%EB%8D%AE%EC%96%B4%EC%93%B0%EA%B8%B0%29%0A%20%20%20%20%20%20%20%20run%3A%20%7C%0A%20%20%20%20%20%20%20%20%20%20cd%20out%0A%20%20%20%20%20%20%20%20%20%20git%20init%20-q%20-b%20data%0A%20%20%20%20%20%20%20%20%20%20git%20config%20user.name%20%22data-bot%22%0A%20%20%20%20%20%20%20%20%20%20git%20config%20user.email%20%2241898282%2Bgithub-actions%5Bbot%5D%40users.noreply.github.com%22%0A%20%20%20%20%20%20%20%20%20%20git%20add%20-A%0A%20%20%20%20%20%20%20%20%20%20git%20commit%20-qm%20%22data%20%24%28date%20-u%20%2B%25FT%25TZ%29%22%0A%20%20%20%20%20%20%20%20%20%20git%20push%20-fq%20%22https%3A//x-access-token%3A%24%7B%7B%20secrets.GITHUB_TOKEN%20%7D%7D%40github.com/%24%7B%7B%20github.repository%20%7D%7D.git%22%20data%0A%20%20%20%20%20%20-%20name%3A%20%EC%98%88%EC%95%BD%20%EC%8B%A4%ED%96%89%20%EC%9C%A0%EC%A7%80%20%2860%EC%9D%BC%20%EB%B9%84%ED%99%9C%EC%84%B1%20%EC%9E%90%EB%8F%99%20%EC%A4%91%EC%A7%80%20%EB%B0%A9%EC%A7%80%29%0A%20%20%20%20%20%20%20%20env%3A%0A%20%20%20%20%20%20%20%20%20%20GH_TOKEN%3A%20%24%7B%7B%20github.token%20%7D%7D%0A%20%20%20%20%20%20%20%20run%3A%20gh%20api%20-X%20PUT%20%22repos/%24%7B%7B%20github.repository%20%7D%7D/actions/workflows/update.yml/enable%22%20%7C%7C%20true%0A)
열린 화면에서 오른쪽 위 초록색 **Commit changes…** → 다시 **Commit changes** 를 누르면 끝이에요.
(약 15분마다 뉴스·증시 데이터가 새로 만들어져요. 첫 실행은 상단 **Actions** 탭 → **뉴스·증시 데이터 업데이트** → **Run workflow** 로 바로 할 수 있어요.)

링크가 안 열리면: **Add file → Create new file** → 이름에 `.github/workflows/update.yml` → [`setup/update.yml`](setup/update.yml) 내용을 붙여넣고 Commit.

### (선택) AI 요약 켜기 — 무료
1. https://aistudio.google.com/apikey 에서 무료 API 키 만들기
2. 이 저장소 **Settings → Secrets and variables → Actions → New repository secret** → 이름 `GEMINI_API_KEY`, 값에 키 붙여넣기
없으면 무료 번역 + 자동 정리로 동작해요.
