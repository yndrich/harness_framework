# Step 0: submissions-locator

## 읽어야 할 파일

먼저 아래를 읽고 아키텍처·설계 의도를 파악하라:

- `/docs/ARCHITECTURE.md`, `/docs/ADR.md` (특히 ADR-001, ADR-007), `/docs/CLAUDE.md`
- `sec_extract/client.py` (SecClient — 모든 HTTP 는 반드시 이걸 경유)
- `sec_extract/facts.py`, `sec_extract/resolve.py`
- `tests/test_sec_extract.py` (pytest 없이 도는 테스트 러너 패턴 — 이 step 에서 테스트를 먼저 쓴다)

## 작업

부문/지역/KPI 데이터는 companyfacts 에 없다(ADR-001). 공시별 XBRL 인스턴스를 파싱해야
하고, 그러려면 먼저 각 회계연도 10-K 의 공시 위치와 **실제 인스턴스 문서 URL** 을 찾아야 한다.

CLAUDE.md 의 TDD CRITICAL 에 따라 **테스트를 먼저 작성**한다(아래 테스트 항목 참고).

새 모듈 `sec_extract/submissions.py`. 테스트 용이성을 위해 네트워크와 순수 로직을 분리한다.

```python
SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"

def select_annual_filings(submissions: dict, n_years: int = 5) -> list[dict]:
    """(순수 함수, 네트워크 없음) 파싱된 submissions JSON 에서 10-K 공시를 추린다.
    filings.recent 의 병렬 배열(accessionNumber/form/filingDate/reportDate/
    primaryDocument/isXBRL/isInlineXBRL)을 dict 행으로 zip.
    - form 이 '10-K' 또는 '10-K/A' 인 것만.
    - 같은 report_date 는 최신 filing_date 1건으로 dedup(정정본 10-K/A 우선).
    - report_date 내림차순 상위 n_years.
    각 행: {accn, accn_nodash, form, filing_date, report_date,
            primary_document, is_inline_xbrl, is_xbrl}."""

def list_annual_filings(client, cik10, n_years=5) -> list[dict]:
    """SecClient 로 submissions 를 받아 select_annual_filings 호출."""

def filing_index_url(cik:int, accn_nodash:str) -> str:
    """https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/index.json"""

def find_instance_url(client, cik:int, filing:dict) -> str:
    """공시 폴더 index.json 을 받아 실제 XBRL 인스턴스 문서 URL 을 해석한다.
    - is_inline_xbrl 이면 inline 주 문서(primary_document, .htm)를 인스턴스로 사용.
    - 아니면 index 의 파일 목록에서 별도 인스턴스(.xml, '_htm.xml'/'_htm.xml' 류 또는
      type 이 'XML'/'EX-101.INS')를 찾는다.
    primary_document 하나에 의존하지 마라 — index 로 확인한다(이유: 정정본·구형 공시·
    예외 케이스에서 primary_document 가 인스턴스가 아닐 수 있다)."""
```

규칙(핵심 — 벗어나지 마라):
- 모든 네트워크는 `SecClient.get_json` 경유. 직접 `urllib` 호출 금지(이유: UA/레이트리밋/캐시).
- accession 두 형태: 대시 포함(`0000320193-24-000123`)·제거(`000032019324000123`).
  Archives 경로의 `{cik}` 는 0 패딩 없는 정수, 폴더명은 대시 없는 accession.
- 5개년 비교에서 가장 오래된 연도가 최신 10-K 비교란에만 있을 수 있으니, 필요한 연도를
  못 채우면 그 다음 과거 10-K 도 포함해 폴더 후보를 넓힌다.

## 테스트 (먼저 작성)
`tests/test_sec_extract.py`(또는 `tests/test_submissions.py`, 동일 러너 패턴)에 추가:
- 합성 submissions dict → `select_annual_filings` 가 10-K 만 추리고, 같은 report_date 의
  10-K/A 를 최신 filing_date 로 dedup 하며, 내림차순 상위 n_years 를 반환하는지.
- `filing_index_url` / accession 대시 변환 / Archives 경로 조립이 정확한지.
- (네트워크 호출 없음 — `select_annual_filings` 는 순수 함수라 dict 만 넣어 검증.)

## Acceptance Criteria
```bash
python3 tests/test_sec_extract.py    # 기존 케이스 + 이 step 신규 케이스 모두 통과
```
신규 테스트는 `submissions.py` 미구현 시 반드시 실패해야 한다(= AC 가 이 step 작업을 실제로 검증).

## 검증 절차
1. 위 AC 실행.
2. 체크리스트: ARCHITECTURE 레이어 경계(submissions 는 client 만 의존), CLAUDE.md
   CRITICAL(외부 의존성 0, SecClient 경유) 위반 없음, 신규 테스트 존재.
3. `phases/1-segments-kpi/index.json` step 0 상태 업데이트(completed/summary 또는 error/blocked).

## 금지사항
- SecClient 우회 금지. 이유: SEC 403/레이트리밋.
- 서드파티 패키지 import 금지(stdlib only). 이유: pip 불가 환경.
- `primary_document` 만 믿고 인스턴스를 추정하지 마라. 이유: 정정·구형 공시에서 깨진다.
- 기존 테스트를 깨뜨리지 마라.
