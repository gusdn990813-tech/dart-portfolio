# 📋 DART 포트폴리오 공시 대시보드

`portfolio.json`에 종목코드만 적어두면, GitHub Actions가 주기적으로 **금융감독원 전자공시(DART) OpenAPI**를 조회해
내 종목의 공시만 모아주고, GitHub Pages로 배포된 웹 대시보드에서 확인하는 구조입니다.

- 서버·비용 없음 (전부 GitHub 무료 범위)
- API 키는 GitHub Secret에 저장 → 웹페이지에 노출되지 않음
- 브라우저는 저장소 안의 JSON만 읽으므로 CORS 문제 없음
- 유상증자·전환사채·최대주주변경·실적 등 **주가 영향이 큰 공시를 자동으로 강조**

```
브라우저 ──▶ GitHub Pages (docs/index.html + docs/data/*.json)
                     ▲
                     │ 커밋
            GitHub Actions (매시간) ──▶ DART OpenAPI
```

---

## 1. OpenDART API 키 발급 (2분, 무료)

1. https://opendart.fss.or.kr 접속 → **인증키 신청/관리** → **인증키 신청**
2. 이메일·이름 입력 후 신청 → 메일로 온 링크에서 인증
3. **오픈API 이용현황**에서 40자리 인증키 복사

> 하루 20,000건까지 호출 가능합니다. 이 대시보드는 종목 수만큼(예: 20종목이면 20~30건) 쓰므로 한도 걱정은 없습니다.

## 2. GitHub 저장소 만들기

1. GitHub에서 새 저장소 생성 (이름 예: `dart-portfolio`) — **Public 권장**
   (Private도 되지만, Pages를 쓰려면 유료 플랜이 필요합니다)
2. 이 폴더의 파일 전체를 업로드하고 커밋
   ```bash
   git init && git add . && git commit -m "init"
   git branch -M main
   git remote add origin https://github.com/<내계정>/dart-portfolio.git
   git push -u origin main
   ```

## 3. API 키를 Secret으로 등록

저장소 → **Settings → Secrets and variables → Actions → New repository secret**

| 항목 | 값 |
|---|---|
| Name | `DART_API_KEY` |
| Secret | 발급받은 40자리 인증키 |

## 4. GitHub Pages 켜기

저장소 → **Settings → Pages**

- Source: `Deploy from a branch`
- Branch: `main` / 폴더 `/docs` → **Save**

1분쯤 뒤 `https://<내계정>.github.io/dart-portfolio/` 로 접속됩니다.

## 5. 첫 수집 실행

저장소 → **Actions → Update DART disclosures → Run workflow**

초록불이 뜨면 `docs/data/`에 데이터가 커밋되고, Pages 주소에서 바로 보입니다.
이후에는 **KST 08~20시 매시 정각**에 자동으로 갱신됩니다.

---

## 포트폴리오 수정하기

`portfolio.json`을 GitHub 웹에서 연필 아이콘으로 직접 고치면 됩니다. 저장하는 순간 워크플로가 다시 돌아 반영됩니다.

```json
{
  "lookback_days": 90,
  "keep_days": 365,
  "portfolio": [
    { "ticker": "005930", "label": "삼성전자", "group": "반도체" },
    { "ticker": "042700" }
  ],
  "watchlist": [
    { "ticker": "042660", "label": "한화오션", "group": "조선" }
  ]
}
```

| 항목 | 설명 |
|---|---|
| `ticker` | **6자리 종목코드** (필수). 종목명이 아니라 숫자 코드입니다 |
| `label` | 화면에 표시할 이름. 비워두면 DART 등록 상호로 자동 채워짐 |
| `group` | 섹터 등 임의 분류 (선택) |
| `watchlist` | 보유하진 않지만 지켜보는 종목. 같은 방식으로 조회됩니다 |
| `lookback_days` | 매 실행 시 조회할 과거 일수 (기본 90) |
| `keep_days` | 대시보드에 보관할 기간 (기본 365) |

## 대시보드 기능

| 기능 | 설명 |
|---|---|
| ⚠️ 중요 공시 배너 | 최근 7일 중 **매우 중요(레벨 3)** 공시를 상단에 따로 표시 |
| 종목 / 분류 칩 | 클릭해서 다중 필터 (다시 클릭하면 해제) |
| 기간·중요도·검색 | 7/30/90일·전체, "중요 이상만", 제목 키워드 검색(하이라이트) |
| 🕘 시간순 ↔ 🏷 종목별 | 보기 전환. 종목별은 중요 공시가 있는 종목이 위로 |
| ✓ 읽음 표시 | 브라우저에 저장(localStorage). "읽지 않은 것만" 필터 가능 |
| NEW 배지 | 직전 수집 이후 새로 올라온 공시 |
| 제목 클릭 | DART 원문 문서로 바로 이동 |

## 중요도 분류 기준

`scripts/rules.py` 한 파일에 키워드로 정의돼 있습니다. 마음에 안 들면 여기만 고치세요.

| 레벨 | 분류 예시 |
|---|---|
| **3 매우 중요** | 위험신호(상장폐지·감사의견·횡령), 증자·CB, 실적(잠정실적·손익구조변동), 지배구조(최대주주변경·합병·영업양수도) |
| **2 중요** | 자기주식, 정기보고서, 지분변동(5%룰·임원소유), 계약·투자, 배당, 소송·제재 |
| **1 참고** | 주주총회, 정정공시 |
| **0 일반** | 그 외 |

정정공시(`[기재정정]`)는 원 공시보다 한 단계 낮게 매깁니다.

## 로컬에서 실행 / 미리보기

```bash
pip install -r requirements.txt

# 실제 수집
export DART_API_KEY=발급받은키          # Windows PowerShell: $env:DART_API_KEY="..."
python scripts/fetch_disclosures.py --days 30

# 데이터 없이 화면만 먼저 보고 싶다면 (가짜 샘플 데이터)
cp sample-data/*.json docs/data/

# 로컬 서버로 열기 (file:// 로 직접 열면 fetch가 막힙니다)
cd docs && python -m http.server 8000   # → http://localhost:8000
```

## 자주 겪는 문제

| 증상 | 원인 / 해결 |
|---|---|
| "데이터를 불러오지 못했습니다" | 아직 워크플로를 한 번도 안 돌렸거나 실패. Actions 탭 로그 확인 |
| `[010] 등록되지 않은 인증키` | Secret 이름이 `DART_API_KEY`인지, 키 앞뒤 공백이 없는지 확인 |
| `DART 상장사 목록에 없음` 로그 | 종목코드 오타이거나 비상장·상장폐지 종목. 대시보드 하단 로그와 `meta.json`의 `unresolved_tickers` 확인 |
| 자동 갱신이 멈춤 | GitHub는 **60일간 커밋이 없으면 스케줄 워크플로를 중단**합니다. Actions에서 수동 실행 한 번이면 재개 |
| 갱신 시각이 조금 늦음 | GitHub Actions 스케줄은 혼잡 시 수 분~수십 분 지연될 수 있습니다 (정상) |
| 페이지가 옛날 데이터 | 강력 새로고침 (Ctrl+Shift+R). 캐시 우회 쿼리를 쓰지만 CDN 지연이 있을 수 있습니다 |

## 파일 구조

```
├── portfolio.json                  ← 내 종목 (여기만 고치면 됨)
├── requirements.txt
├── .github/workflows/update.yml    ← 자동 수집 스케줄
├── scripts/
│   ├── fetch_disclosures.py        ← DART API 호출 + 저장
│   ├── rules.py                    ← 중요도 분류 키워드
│   └── make_sample_data.py         ← 미리보기용 가짜 데이터
├── docs/                           ← GitHub Pages 배포 폴더
│   ├── index.html                  ← 대시보드 (단일 파일)
│   └── data/                       ← 수집 결과 JSON (자동 생성)
└── sample-data/                    ← 미리보기용 샘플
```

---

데이터 출처: 금융감독원 전자공시시스템(DART) OpenAPI.
본 대시보드는 정보 제공용이며, 투자 판단과 그 결과에 대한 책임은 이용자 본인에게 있습니다.
