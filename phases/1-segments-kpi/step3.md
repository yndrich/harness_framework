# Step 3: excel-segments

## 읽어야 할 파일
- `/docs/UI_GUIDE.md` (엑셀 레이아웃·검토 색상 규약), `/docs/CLAUDE.md`
- `sec_extract/excel.py`, `sec_extract/xlsx.py` (작성기 지원 범위), `sec_extract/segments.py` (step 2)
- `tests/test_sec_extract.py` (워크북 스모크 테스트 패턴 — 테스트 먼저)

## 작업

부문/지역/제품 분해를 엑셀에 추가하고, 회사 고유 KPI 는 검토 큐로 노출한다.
TDD: 워크북 스모크 테스트를 먼저 확장한다.

`excel.py` 확장:
- 새 시트 `Segments`, `Geography`(가능하면 `Products`): 행 = 멤버, 열 = 연도.
  다기업이면 기존 제표 시트처럼 기업 블록을 가로로.
- 검토 플래그(unknown-axis / custom-tag / does-not-reconcile)는 기존 `Review` 시트에
  합류시킨다(별도 시트 아님). 색상 규약은 UI_GUIDE 를 따른다.
- step 2 의 `reconcile`(정보성)는 분해 시트 하단 또는 Provenance 에 '계산합 vs 보고총계'로 병기.
- 회사 고유 KPI 후보(`KPI (review)`): 자동 표준화하지 않고 원본 태그/멤버/값 그대로 나열 + REVIEW.
- 분해 값도 Provenance 에 출처(인스턴스 accession/축/멤버) 기록.

규칙:
- `xlsx.py` 가 지원하는 기능(값·스타일·병합·틀고정)만 사용. 차트/조건부서식 가정 금지.
- 기존 6시트 구성·명명·색상 규약 유지. 기존 시트 레이아웃을 깨지 마라.

## 테스트 (먼저 작성)
- 합성 분해 데이터(step 2 출력 형태)로 워크북 생성 → 유효한 zip/XML, `Segments`·`Geography`
  시트 존재, Review 에 신규 플래그 행이 합류하는지 검증(네트워크 없음).

## Acceptance Criteria
```bash
python3 tests/test_sec_extract.py     # 워크북 스모크에 신규 시트/플래그 검증 포함, 전체 통과
```

## 검증 절차
1. AC 실행. 2. UI_GUIDE 레이아웃/색상·CLAUDE CRITICAL(출처 추적)·신규 테스트 확인. 3. index.json step 3 업데이트.

## 금지사항
- 회사 고유 KPI 를 표준 항목인 척 섞지 마라. 이유: 검토 전 자동 채택 금지(ADR-006).
- xlsx.py 미지원 기능을 새로 가정하지 마라. 필요하면 작성기를 먼저 확장하고 테스트하라.
