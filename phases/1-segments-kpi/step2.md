# Step 2: segment-mapping

## 읽어야 할 파일
- `/docs/ADR.md` (ADR-003 표준화, ADR-006 검토 플래그), `/docs/CLAUDE.md`
- `sec_extract/canonical_map.py` (표준화 레이어 — 여기에만 매핑을 둔다)
- `sec_extract/xbrl_instance.py` (step 1), `sec_extract/normalize.py` (플래그 (TYPE, detail) 관례)
- `tests/test_sec_extract.py` (러너 패턴 — 테스트 먼저)

## 작업

차원 사실을 '알려진 축 → 표준 그룹'으로 묶고, 모르는 축/회사 고유 멤버는 검토로 보낸다.
TDD: 테스트를 먼저 작성한다.

`canonical_map.py` 에 추가:
```python
KNOWN_AXES = {
    "us-gaap:StatementBusinessSegmentsAxis": "segment",
    "srt:StatementGeographicalAxis": "geography",
    "srt:ProductOrServiceAxis": "product",
}
# 분해 대상 개념(우선 매출). 후보 태그는 canonical_map 의 revenue 항목과 공유한다.
```

새 모듈 `sec_extract/segments.py`:
```python
def build_disaggregation(facts: list[dict], years: list[int],
                         concept_tags: list[str]) -> dict:
    """concept_tags(예: revenue 후보 태그)에 해당하는 차원 fact 를
    {group: {member_label: {year: value}}} 로 집계. group 은 KNOWN_AXES 값.
    반환에 'flags'(검토)와 'reconcile'(정보성) 포함.

    검토 플래그:
    - 미인식 축(KNOWN_AXES 에 없음)                 -> REVIEW: unknown-axis
    - 회사 고유 네임스페이스 멤버/개념(us-gaap/srt 아님) -> REVIEW: custom-tag

    재무 정합성(정보성 — 하드 플래그 아님):
    - 같은 (group, year)의 멤버 합 vs primary(무차원) 총계를 'reconcile' 에
      {computed_sum, reported_total, diff} 로 병기한다.
    - REVIEW(does-not-reconcile)는 '조정 멤버 부재 + |diff|/total > 허용오차(예 2%)'
      일 때만. 이유: 사업부간 제거·Corporate/Other·조정항목 때문에 합≠총계는 정상이라
      전부 플래그하면 거짓양성 폭탄이 된다."""
```

규칙:
- 매핑 지식은 `canonical_map.py`(KNOWN_AXES)에만. `segments.py` 에 축 문자열 하드코딩 금지.
- 자동 매핑이 불확실하면 조용히 추측하지 말고 REVIEW 로(ADR-006). 회사 고유 KPI 는 전량 검토 큐로.
- 검토 플래그 형식은 normalize.py 의 (TYPE, detail) 튜플 관례를 따른다.
- 연도 라벨은 normalize 와 동일 기준(기간 end 의 연도)으로 맞춘다.

## 테스트 (먼저 작성)
합성 fact 리스트로 검증(네트워크 없음):
- 알려진 축(segment/geography) → 올바른 group 으로 매핑, 멤버×연도 집계 정확.
- 미인식 축 → unknown-axis, 회사 고유 멤버 → custom-tag REVIEW.
- reconcile: 멤버 합·총계·diff 가 병기되는지. **조정 멤버가 있으면** does-not-reconcile 가
  뜨지 **않는지**(거짓양성 방지). 허용오차 초과 + 조정멤버 부재일 때만 뜨는지.

## Acceptance Criteria
```bash
python3 tests/test_sec_extract.py
```
신규 테스트는 `segments.py`/`KNOWN_AXES` 미구현 시 실패해야 한다.

## 검증 절차
1. AC 실행. 2. CLAUDE CRITICAL(매핑 단일출처, 애매값 플래그)·신규 테스트 확인. 3. index.json step 2 업데이트.

## 금지사항
- 미인식 축/커스텀 태그를 임의 그룹에 욱여넣지 마라. 이유: 잘못된 표준화는 침묵 추정이다.
- 멤버 합 불일치를 무조건 REVIEW 로 띄우지 마라. 이유: 정상 케이스가 많아 노이즈가 된다.
