# Step 1: inline-xbrl-parser

## 읽어야 할 파일
- `/docs/ARCHITECTURE.md`, `/docs/ADR.md` (ADR-001, ADR-007), `/docs/CLAUDE.md`
- `sec_extract/submissions.py` (step 0 산출물 — 인스턴스 문서 URL 제공)
- `sec_extract/facts.py` (fact dict 형태 참고)
- `tests/test_sec_extract.py` (러너 패턴 — 테스트 먼저)

## 작업

XBRL 인스턴스에서 **차원 포함** 사실을 뽑는다(inline 주 문서의 `<ix:...>` 또는 별도 `.xml`
인스턴스). companyfacts 가 버리는 축/멤버 컨텍스트를 복원하는 것이 이 phase 의 핵심이다.
TDD: 테스트를 먼저 작성한다.

새 모듈 `sec_extract/xbrl_instance.py`.

```python
def parse_instance(text: str) -> list[dict]:
    """XBRL 인스턴스 텍스트에서 fact 리스트 반환. 각 fact:
    {concept, value, raw_text, unit, decimals, context_ref,
     dims: {axis_qname: member_qname}, start, end, instant}
    - 값 태그: <ix:nonFraction name="us-gaap:..." contextRef="c1" unitRef="usd"
      decimals="-6" scale="6" sign="-" format="ixt:num-dot-decimal">1,234</ix:nonFraction>
    - 컨텍스트: <xbrli:context id="c1"> 의 <xbrli:period>(startDate/endDate/instant)와
      <xbrldi:explicitMember dimension="us-gaap:...Axis">us-gaap:...Member</...>

    숫자 정규화(중요):
    - raw_text 에서 콤마·공백 등 서식문자 제거 후 숫자 파싱(format 의 ixt 변환 고려:
      num-dot-decimal / num-comma-decimal 등 최소 둘).
    - value = parsed * 10**int(scale)  (scale 기본 0), sign=='-' 이면 부호 반전.
    - decimals 는 '정밀도 메타데이터'일 뿐 배율이 아니다 — 곱하지 마라. 기록만 한다."""

def parse_instance_url(client, url) -> list[dict]:
    """SecClient 로 인스턴스 문서를 받아 parse_instance 호출(네트워크 경계 분리)."""
```

규칙:
- **stdlib only.** `xml.etree.ElementTree` 로 네임스페이스 처리(ix, xbrli, xbrldi, us-gaap, srt, dei).
  주 문서가 깨진 XHTML 일 수 있으니, ET 파싱 실패 시 별도 인스턴스(.xml) 폴백 또는 관대한
  추출 경로를 둔다(이유: 실패해도 부분 결과를 내야 한다). 문서가 수 MB 일 수 있음.
- 차원 없는(=primary) fact 와 차원 있는 fact 를 **모두** 보존. 차원 유무로 거르지 마라.
- 대상은 숫자 사실(`ix:nonFraction`). `ix:nonNumeric`(텍스트)은 이 step 범위 밖.
- 회사 고유 네임스페이스(예: `aapl:`) 태그·멤버는 버리지 말고 그대로 보존(다음 step 에서 라우팅).

## 테스트 (먼저 작성)
작은 합성 inline-XBRL 문자열을 넣어 검증(네트워크 없음):
- 축/멤버(`dims`), 기간(start/end 또는 instant) 추출 정확.
- scale·sign·콤마 정규화: `format` 콤마 텍스트 + `scale=6` + `sign=-` → 올바른 음수 큰 값.
- 차원 없는 fact 와 있는 fact 가 모두 반환되는지.

## Acceptance Criteria
```bash
python3 tests/test_sec_extract.py    # 신규 케이스 포함 전체 통과
```
신규 테스트는 `xbrl_instance.py` 미구현 시 실패해야 한다.

## 검증 절차
1. AC 실행. 2. 레이어 경계·CLAUDE CRITICAL·신규 테스트 존재 확인. 3. index.json step 1 업데이트.

## 금지사항
- 서드파티 XML/HTML 파서(lxml, beautifulsoup) import 금지. 이유: pip 불가.
- 차원 있는 fact 를 조용히 버리지 마라. 이유: 그게 이 phase 의 목적.
- `decimals` 를 배율로 곱하지 마라. 이유: 값이 틀어진다(정밀도 메타데이터일 뿐).
