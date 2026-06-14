# 아키텍처

## 디렉토리 구조
```
sec_extract/
├── __main__.py        # python -m sec_extract 진입점
├── cli.py             # argparse — 인자 파싱, 기업 루프, 워크북 호출
├── client.py          # SecClient — HTTP(User-Agent, 10req/s, 재시도, 디스크 캐시)
├── resolve.py         # 티커 → CIK (company_tickers.json)
├── facts.py           # CompanyFacts — companyfacts API 래퍼
├── canonical_map.py   # ★ 표준화 레이어 (사람 편집): 표준항목 → 후보 태그
├── normalize.py       # 연도별 태그 해석, 재작성 dedup, 검토 플래그, CompanyResult
├── excel.py           # 워크북 구성 (제표/Comparison/Review/Provenance)
└── xlsx.py            # 의존성 없는 최소 XLSX 작성기 (stdlib)
tests/test_sec_extract.py   # 네트워크 불필요 단위 테스트
docs/SEC_EXTRACT.md         # 사용자용 사용 설명서 (README 역할)
```

## 패턴
- **레이어드 + 단방향 의존**: `cli` → `client`/`resolve`/`facts` → `normalize` → `excel` → `xlsx`.
  하위 레이어는 상위를 모른다. 네트워크(`client`)와 표현(`excel`/`xlsx`)을 정규화 로직과 분리.
- **설정 주도(config-driven)**: 표준화 규칙은 코드가 아니라 데이터(`canonical_map.STATEMENTS`).
  새 항목·새 후보 태그는 코드 수정 없이 이 설정만 바꾼다.
- **순수 함수 정규화**: `normalize.py` 는 네트워크·IO 없이 `CompanyFacts` 입력만으로 결정적
  결과를 낸다 → 합성 데이터로 테스트 가능.
- **출처 보존**: 모든 채택 값은 어느 태그·어느 공시에서 왔는지 끝까지 들고 다닌다.

## 데이터 흐름
```
티커(예: AAPL)
  → resolve.py: company_tickers.json 에서 CIK(10자리) 해석
  → facts.py:   companyfacts API 호출 (SecClient 경유, 캐시)
  → normalize.py: 연도 집합 산출 → 항목 x 연도마다 후보 태그 해석
                  · 최신 제출본 채택(재작성 dedup)
                  · AMBIGUOUS/RESTATED/GAP 플래그 부착
  → excel.py → xlsx.py: 제표 시트 + Comparison + Review + Provenance 워크북 저장
```

## 상태 관리
- **무상태(stateless) 파이프라인**: 실행마다 입력(티커)로부터 출력(.xlsx)을 새로 만든다.
- **유일한 영속 상태는 디스크 캐시**(`.sec_cache/`): URL 기준 원본 JSON 저장 → 재실행이
  즉시 끝나고 결과가 재현 가능하다. `--refresh`/`--no-cache` 로 우회.
- 전역 가변 상태 없음. `SecClient` 인스턴스 하나를 기업 루프에서 공유(레이트리밋 일관성).
