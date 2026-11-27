# 모닝픽 데이터 (outfit-data) — 작업 안내서

모닝픽 앱(`~/outfit-app`, 그 저장소의 `AGENTS.md`도 같이 보세요)이 읽는 뉴스·증시·Daily Up 데이터를 만드는 저장소예요.
규칙은 앱과 같아요. **전부 무료**로 만들고, 사용자와는 **한국어**로 대화해요.

## 무엇을 만드나
`build.py`(표준 라이브러리만 사용) → `out/`에 아래 파일을 만들고 **`data` 브랜치에 커밋 1개로 덮어써요.**
- `market.json`: 국내·해외 지수, 환율·금리·원자재, 코인, 경제 일정, AI 증시 분석(`brief`, `commentary`, `focus`=us|kr, `session`=휴장 판단)
- `news.json`: 주요 뉴스·분류별 뉴스, AI 핵심 요약(`brief`), 기사별 요약, 오늘의 경제노트
- `daily.json`: Talk Pick(영어 질문), AI 한 스푼 — 하루 1번(아침 6시 이후 첫 실행)
- `cache.json`: 번역·요약 캐시, `slots`(마지막으로 만든 시간표 칸)

## 갱신 시간표 (한국 시간)
| 대상 | 시각 | 내용 |
|---|---|---|
| 증시 | **07시** | 밤사이 **미국 증시 중심** 분석 (오늘 한국장에 줄 영향 포함) |
| 뉴스 | **08 · 12 · 16시** | 주요 뉴스, AI 핵심 요약 |
| 증시 | **17시** | 오늘 **한국 증시 중심** 분석 (수급·업종·환율) |

- 시간표는 `build.py`의 `NEWS_SLOTS`, `MARKET_SLOTS`에 있어요. 바꾸면 앱 화면의 '다음 업데이트' 표시(`market.js`의 `nextAt([..])`, `news.js`)도 같이 바꿔요.
- **휴장 판단**(`market_session`): 지수의 마지막 거래 시각(`at`)으로 직전 장이 열렸는지 봐요. 쉬었으면 AI가 "지난 거래일을 짧게 되짚고 다음 거래일 관전 포인트 위주"로 쓰게 해요(주말·공휴일 자동 판단).
- AI(Gemini 무료 키, GitHub secret `GEMINI_API_KEY`)가 실패하면 15분 뒤 실행에서 최대 2번 더 시도해요(`newsTry`, `marketTry`). 키가 없으면 규칙 기반 요약을 써요.
- 시간표와 상관없이 바로 만들기: Actions → 수동 실행에서 `force`에 `all`/`news`/`market`을 넣어요(로컬에서는 `FORCE=all python3 build.py out`).

## 자동 실행 (`.github/workflows/update.yml`, 같은 내용을 `setup/update.yml`에도 복사해 둬요)
- GitHub 예약 실행(cron)은 잘 안 돌아서(처음 12시간에 1번만 돌았어요) **스스로 다음 실행을 예약하는 방식**이에요.
  - 실행이 끝날 때 `gh workflow run update.yml -f chain=true`로 다음 실행을 만들어요(GITHUB_TOKEN으로 허용돼요).
  - 다음 실행은 `cadence` 환경의 **14분 대기**(wait timer) 후 시작해요. 이미 기다리는 실행이 있으면 새로 만들지 않아요.
  - 매시 7분 cron은 반복이 끊겼을 때 다시 이어 주는 예비용이에요.
- 깨어나도 정해진 시각이 아니면 `build.py`가 `out/.skip`을 만들고, 이때는 올리기를 건너뛰어요.
- 대기 환경을 만드는 명령(처음 한 번): `gh api -X PUT repos/<저장소>/environments/cadence -F wait_timer=14`
- 데이터가 오래돼 보이면 `gh run list --workflow update.yml`로 `waiting` 상태인 실행이 있는지 확인하고, 없으면 `gh workflow run update.yml`로 다시 시작해요.

## 로컬 시험
```bash
O=$(mktemp -d); for f in cache news market daily; do curl -sfL https://raw.githubusercontent.com/bottleman-bang/outfit-data/data/$f.json -o $O/$f.json; done
python3 build.py $O        # 시간이 된 것만 만들고, 아니면 "nothing due"
FORCE=all python3 build.py $O
```
