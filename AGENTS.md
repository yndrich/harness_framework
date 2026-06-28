# Codex 작업 지침

이 저장소의 기본 프로젝트 맥락은 `CLAUDE.md`에 있다. 의미 있는 변경을 하기
전에 반드시 `CLAUDE.md`를 읽고, 이 파일과 `CLAUDE.md`의 지침이 겹치면 더
엄격하거나 더 구체적인 지침을 따른다.

## 프로젝트 요약

`sec_extract`는 SEC EDGAR 10-K/10-Q 공시에서 표준화된 재무 데이터를 추출해
비교 가능한 Excel 워크북으로 저장하는 Python CLI다. 판단이 애매한 재무 데이터는
조용히 채택하지 말고 사람이 검토할 수 있도록 표면화해야 한다.

## 필수 규칙

- Python 3.12 표준 라이브러리만 사용한다. 운영 코드에 외부 의존성을 추가하지 않는다.
- `requests`, `openpyxl`, `pandas`, `lxml`, `bs4`, `numpy` 같은 서드파티 패키지를
  import하지 않는다.
- 모든 SEC HTTP 접근은 `sec_extract/client.py::SecClient`를 통해서만 수행한다.
  `client.py` 밖에서 `urllib.request.urlopen`을 직접 호출하지 않는다.
- 표준화 재무 태그 매핑은 `sec_extract/canonical_map.py`에만 둔다.
- 기능 모듈에 `us-gaap` 후보 태그를 하드코딩하지 않는다. 필요한 태그는
  `canonical_map.py`에서 읽는다.
- 불확실한 값을 조용히 선택하지 않는다. 후보 충돌, 재작성, 누락, 미인식 축,
  회사 고유 태그, 정합성 문제는 검토 플래그로 드러낸다.
- 모든 출력 값은 가능한 한 출처를 보존해야 한다: source tag, accession, form,
  filed date, period, unit.

## 아키텍처 경계

데이터 흐름은 다음 레이어를 유지한다:

```text
client
  -> resolve / facts / submissions / xbrl_instance
  -> normalize / segments / quarterly
  -> excel / raw_model
```

하위 레이어가 상위 레이어를 import하지 않는다. 네트워크와 파일시스템 관심사는
가능한 한 정규화/파싱 로직 밖에 둔다.

## 테스트 기준

- 새 동작을 추가할 때는 가능한 한 TDD를 따른다. 구현 전에 테스트를 추가하거나
  갱신한다.
- `sec_extract` 테스트는 네트워크 없이 실행되어야 하며, 합성 데이터를 사용한다.
- 검증 명령은 우선 다음을 사용한다:
  - `python3 tests/test_sec_extract.py`
  - `python3 tests/test_quarterly.py`
- `scripts/test_execute.py`는 하네스용 pytest 테스트다. `pytest`를 운영 의존성으로
  만들지 않는다.

## 데이터 처리 메모

- `companyfacts`는 회사 전체 기준의 표준화 fact에 적합하다.
- 사업부, 지역, 제품, 회사 고유 KPI 데이터는 공시 XBRL 인스턴스와 dimension 파싱이
  필요하다.
- 회사 고유 KPI concept 또는 member는 명시적인 표준화 규칙이 추가되기 전까지
  Review로 보낸다.
- 공시에 corporate, eliminations, intersegment, other, adjustment member가 있으면
  reconciliation 차이가 정상일 수 있다.

## 출력 기준

- 연간 워크북 출력에는 재무제표, Comparison, Review, Provenance 시트가 포함되어야 한다.
- Raw/tidy model 출력에 새 필드나 시트를 추가할 때는 값을 감사할 수 있을 만큼 충분한
  메타데이터를 보존한다.
- 생성된 `.xlsx`, `.sec_cache/`, `__pycache__/`, phase output 파일은 커밋하지 않는다.

## 문서화

- 동작, 명령어, 시트 구성, 아키텍처 규칙이 바뀌면 `docs/SEC_EXTRACT.md`,
  `docs/ARCHITECTURE.md`, `CLAUDE.md`를 함께 갱신한다.
- CLI 문서는 `sec_extract/cli.py`와 일치시킨다.

## 저장소 위생

- 편집 전에 `git status --short`를 확인한다. 사용자 또는 Claude Code의 무관한 변경을
  덮어쓰지 않는다.
- 패치는 요청된 작업에 집중해 작게 유지한다.
- 명시적으로 요청받지 않는 한 커밋, 브랜치 생성, 파괴적인 git 작업을 하지 않는다.
