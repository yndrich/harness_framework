# sec_extract — SEC 재무정보 표준화 추출기

SEC EDGAR 의 10-K/10-Q 공시에서 **표준화된 재무정보**를 가져와 엑셀로 떨군다.
여러 기업 · 여러 연도를 한 워크북에서 비교하고, 자동으로 판단하기 애매한 항목은
**검토 필요(Review)** 로 표면화한다. 외부 의존성 없음(파이썬 표준 라이브러리만).

## 빠른 시작

```bash
# 단일 기업 5개년
python3 -m sec_extract AAPL --years 5 -o apple.xlsx

# 여러 기업 비교
python3 -m sec_extract AAPL MSFT NVDA --years 5 -o compare.xlsx

# 분기 raw 데이터(사용자 모델용 tidy) — 최근 16분기
python3 -m sec_extract NVDA --raw-model --quarters 16 -o nvda_q.xlsx

# 특정 분기만 (단일 / 여러 개 / 범위) — 지정 시 --quarters 무시
python3 -m sec_extract NVDA --raw-model --period 2025Q1 -o nvda_2025q1.xlsx
python3 -m sec_extract NVDA --raw-model --period 2025Q1 2024Q3 -o nvda_picks.xlsx
python3 -m sec_extract NVDA --raw-model --period 2024Q1:2025Q1 -o nvda_range.xlsx

# 부문/지역/제품 매출 분해 시트 추가 (연간; --raw-model 과 함께면 분기 분해)
python3 -m sec_extract NVDA --segments -o nvda.xlsx
```

생성되는 시트:
- **Income Statement / Balance Sheet / Cash Flow** — 행=표준 항목, 열=연도
  (다기업이면 기업 블록이 가로로 나란히)
- **Comparison** — 핵심 지표 + 파생값(Free Cash Flow, 매출총이익률/영업이익률/순이익률)
- **Review** — 사람이 확인해야 하는 셀 목록 (색상 하이라이트)
- **Provenance** — 모든 값의 출처(us-gaap 태그 · 공시 accession · 제출일 · 기간) 추적

### 옵션
| 옵션 | 설명 |
|---|---|
| `-y, --years N` | 최근 N개 회계연도 (기본 5) |
| `-o, --output PATH` | 출력 .xlsx 경로 |
| `--user-agent "이름 email"` | SEC 요청 User-Agent (연락 이메일 필수). 환경변수 `SEC_USER_AGENT` 도 가능 |
| `--refresh` | 캐시 무시하고 새로 받기 |
| `--no-cache` | 캐시 사용 안 함 |
| `--cache-dir DIR` | 응답 캐시 위치 (기본 `.sec_cache/`) |
| `--segments` | 부문/지역/제품 매출 분해 시트 추가 (공시별 inline-XBRL 파싱 — 느림) |
| `--raw-model` | 분기 tidy Raw Data 출력 (사용자 모델 스키마 + Canonical Key) |
| `--quarters N` | `--raw-model` 시 최근 N개 분기 (기본 16) |
| `--period YYYYQn …` | `--raw-model` 시 특정 분기만: 단일 `2025Q1`, 여러 개 `2025Q1 2024Q3`, 범위 `2024Q1:2025Q1`. 지정 시 `--quarters` 무시. 달력에 없는 분기는 오류로 안내 |

> SEC 정책상 모든 요청에 **연락처가 담긴 User-Agent** 가 필요하다(없으면 403).
> 기본값에 이메일이 들어 있으나, 본인 연락처로 바꾸는 것을 권장한다.

## 왜 XBRL 직접 파싱이 아니라 companyfacts API 인가

SEC 의 `data.sec.gov/api/xbrl/companyfacts/CIK##########.json` 한 번 호출이면
한 기업의 모든 us-gaap XBRL 사실을 **이미 태그 표준화된 형태**로 연도/분기별로 받는다.
원본 XBRL 문서를 직접 파싱할 필요가 없다. 3대 재무제표의 집계값은 전부 여기 있다.

## 표준화(standardization) 가 동작하는 방식

같은 경제적 개념이라도 기업/연도마다 us-gaap 태그가 다르고, 시간이 지나며
추가·삭제·개명된다. 예: 매출 =
`RevenueFromContractWithCustomerExcludingAssessedTax`(ASC 606 이후) / `Revenues` /
`SalesRevenueNet`(구). 

`sec_extract/canonical_map.py` 가 **표준 항목 → 후보 태그 우선순위 리스트**를 정의한다.
정규화 단계는 **연도마다** 후보를 위에서부터 시도해 첫 값을 채택하므로, 태그가
바뀌어도 자동으로 흡수된다. 채택된 태그는 Provenance 시트에 기록된다.

새 기업을 다루다 값이 안 잡히면(Review 의 GAP), `canonical_map.py` 의 해당 항목에
후보 태그를 추가하면 된다 — 이 파일이 "사람이 관리하는 표준화 레이어"다.

## 검토 플래그 (Review 시트)

| 플래그 | 의미 | 처리 |
|---|---|---|
| **AMBIGUOUS** (연노랑) | 후보 태그가 둘 이상 값이 있고 서로 불일치 | 우선순위 1번 채택, 둘 다 표시 |
| **RESTATED** (연주황) | 같은 기간을 다른 공시가 다른 값으로 보고(재작성) | 최신 제출본 채택, 과거값 표시 |
| **GAP** (연빨강) | 다른 연도엔 값이 있는데 중간 연도가 비어 있음 | 태그 변경/누락 의심 → 매핑 보강 |

재작성 처리: companyfacts 는 같은 기간을 여러 공시(다른 accession/제출일)로 반환한다.
`sec_extract` 는 같은 (항목, 연도)에서 **최신 제출본**을 채택하고, 값이 갈리면 RESTATED 로
띄운다.

## 구조

```
sec_extract/
├── client.py         # HTTP: User-Agent, 10 req/s 제한, 재시도, 디스크 캐시
├── resolve.py        # 티커 → CIK (company_tickers.json)
├── facts.py          # companyfacts API 래퍼
├── submissions.py    # EDGAR 공시(10-K/10-Q) 목록·인스턴스 URL 탐색
├── xbrl_instance.py  # inline-XBRL 인스턴스 파서 (축/멤버 차원 복원)
├── canonical_map.py  # ★ 표준화 레이어 (사람이 편집) — 표준항목→후보태그·축/멤버 별칭
├── normalize.py      # 연도별 태그 해석, 재작성 dedup, 검토 플래그
├── quarterly.py      # 이산 분기 추출(매출 기준 날짜 달력) + --period 분기 선택
├── segments.py       # 연간 부문/지역/제품 분해 (표준 축 집계)
├── segment_detail.py # as-reported 분기/연간 매출 분해 (멤버 verbatim + 변경 로그)
├── excel.py          # 연간 워크북 (제표/Comparison/Review/Provenance)
├── raw_model.py      # 분기 tidy Raw Data 워크북 (사용자 모델 스키마)
├── xlsx.py           # 의존성 없는 최소 XLSX 작성기
└── cli.py            # 명령행 진입점
tests/  test_sec_extract.py · test_quarterly.py · test_segment_detail.py  (네트워크 불필요)
```

테스트: 세 파일을 직접 실행한다(`python3 tests/test_sec_extract.py` 등), pytest 있으면 `pytest tests/`.

## 부문별/지역별/제품별 매출 (구현됨: `--segments`, `--raw-model --segments`)

companyfacts API 는 **차원(dimension)** 데이터를 담지 않는다(사업부문별/지역별 매출 등).
그래서 해당 공시의 **inline-XBRL 인스턴스 문서**를 직접 파싱해 축/멤버를 복원한다
(`<context>` 의 `xbrldi:explicitMember`). 기업 고유 네임스페이스(예: `nvda:`)로 태깅된
멤버는 표준 택소노미에 없어 자동 표준화가 본질적으로 불가능하므로, **as-reported(보고된
그대로) 캡처**한다:

- `segments.py` — 연간 분해. 표준 축(`StatementBusinessSegmentsAxis`/
  `srt:StatementGeographicalAxis`/`srt:ProductOrServiceAxis`)으로 집계, 미인식 축·커스텀
  멤버는 Review 로. (`--segments` → 연간 워크북에 시트 추가)
- `segment_detail.py` — 분기/연간 멤버별 매출을 QName 그대로 보존 + 별칭 레이어
  (`canonical_map.AXIS_LABELS`/`MEMBER_ALIASES`) + 변경 로그(멤버 신규/중단/재작성) +
  합계 대비 reconcile. (`--raw-model --segments` → 분기 분해 시트 추가)

미구현(다음 단계): 비-GAAP KPI 표준화, 합성(composite) face 라인의 inline-XBRL 보강
(현재는 `face_only` 라인으로 Review 표면화).
