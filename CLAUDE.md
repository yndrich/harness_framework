# 프로젝트: sec_extract — SEC 재무정보 표준화 추출기

SEC EDGAR 10-K/10-Q 공시에서 표준화된 재무정보를 가져와 다년·다기업 비교용
엑셀로 떨구는 파이썬 CLI. 자동 판단이 애매한 항목은 사람이 검토하도록 표면화한다.

## 기술 스택
- Python 3.12 — **표준 라이브러리만** (외부 패키지 0개)
- HTTP: `urllib`  /  엑셀 생성: 직접 구현한 `sec_extract/xlsx.py`
- 데이터 출처: SEC EDGAR 공개 API (`data.sec.gov`, `www.sec.gov`)

## 아키텍처 규칙
- CRITICAL: **외부 의존성 금지.** `pip install` 불가 환경(pip/ensurepip 없음)이다.
  `requests`/`openpyxl`/`lxml`/`pandas` 등 어떤 서드파티도 import 하지 마라.
  필요하면 stdlib 로 직접 구현한다 (XLSX 는 `xlsx.py` 가 이미 그렇게 한다).
- CRITICAL: **모든 SEC HTTP 요청은 `client.py` 의 `SecClient` 를 통해서만.**
  직접 `urllib.request.urlopen` 호출 금지. 이유: SEC 는 연락처 담긴 User-Agent
  없으면 403, IP 당 10 req/s 제한이 있다. `SecClient` 가 UA·레이트리밋·재시도·캐시를 담당.
- CRITICAL: **표준화 매핑은 `canonical_map.py` 에서만 정의·수정.** us-gaap 태그를
  다른 모듈 코드에 하드코딩하지 마라. 이유: 표준화 레이어는 단일 출처여야 사람이 관리한다.
- CRITICAL: **애매한 값을 조용히 채택하지 마라.** 후보 태그 충돌·재작성·중간연도
  누락은 반드시 검토 플래그(`AMBIGUOUS`/`RESTATED`/`GAP`)로 표면화한다. 이유:
  '사람 검토 가능성'이 이 제품의 핵심 요구사항이다.
- 모든 산출 값은 출처(us-gaap 태그 · 공시 accession · 제출일)를 추적할 수 있어야
  한다 (Provenance 시트). 출처 없는 값을 만들지 마라.
- 레이어 경계 유지: `client` → (`resolve`/`facts`) → `normalize` → `excel`.
  하위 레이어가 상위를 import 하지 않는다.

## 개발 프로세스
- CRITICAL: 새 기능 구현 시 반드시 테스트를 먼저 작성하고, 테스트가 통과하는
  구현을 작성할 것 (TDD). 테스트는 **네트워크 없이** 합성 데이터로 돌아가야 한다.
- 커밋 메시지는 conventional commits 형식을 따를 것 (feat:, fix:, docs:, refactor:)

## 명령어
```bash
python3 -m sec_extract AAPL --years 5 -o out.xlsx   # 실행 (단일 기업)
python3 -m sec_extract AAPL MSFT NVDA -o cmp.xlsx    # 다기업 비교
python3 tests/test_sec_extract.py                    # 테스트 (pytest 불필요)
python3 scripts/execute.py <task-name>               # 하네스로 다음 phase 실행
```
