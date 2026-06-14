# Step 4: cli-integration

## 읽어야 할 파일
- `/docs/ARCHITECTURE.md` (데이터 흐름), `/docs/CLAUDE.md`
- step 0~3 산출물: `submissions.py`, `xbrl_instance.py`, `segments.py`, `excel.py`
- `sec_extract/cli.py`, `sec_extract/normalize.py` (연도 라벨 기준 = 기간 end 의 연도)
- `tests/test_sec_extract.py` (러너 패턴)

## 작업

지금까지의 모듈(로케이터 → 파서 → 분해 → 엑셀)을 **CLI 파이프라인으로 결선**한다.
이 결선이 어느 step 에도 없었으므로 여기서 명시한다.

`cli.py` 확장:
- 옵트인 플래그 `--segments` 추가(기본 꺼짐). 이유: 인스턴스 문서는 공시당 수 MB라
  기본 경로(3대 재무제표)를 느리게 만들면 안 된다.
- `--segments` 시 기업마다:
  1. `submissions.list_annual_filings(client, cik10, n_years)` 로 10-K 목록.
  2. 각 공시 `find_instance_url` → `xbrl_instance.parse_instance_url` 로 차원 fact 수집.
  3. `segments.build_disaggregation(facts, years, revenue_tags)` 로 분해 테이블.
  4. 결과를 `CompanyResult` 에 실어 `excel.write_workbook` 가 분해 시트를 그리게 한다.
- **연도 정렬(중요)**: 분해의 연도 라벨을 normalize 와 동일 기준(기간 end 의 연도)으로 맞춰
  3대 재무제표 시트와 같은 열에 정렬되게 한다. 공시 `report_date` 가 아니라 fact 의 기간 end 기준.

규칙:
- 모든 네트워크는 SecClient(이미 cli 가 생성해 공유) 경유. 새 클라이언트 만들지 마라.
- `--segments` 가 꺼져 있으면 기존 동작·성능·출력과 100% 동일해야 한다(회귀 금지).
- 한 공시/한 기업 파싱이 실패해도 그 부분만 건너뛰고 나머지는 진행(부분 결과 원칙).

## 테스트 (먼저 작성)
- **오프라인 통합 테스트**: 가짜 client(합성 submissions JSON + 합성 인스턴스 텍스트 반환)를
  주입해 cli 파이프라인을 끝까지 태우고, 생성된 워크북에 분해 시트/값이 들어가는지 검증.
  실제 SEC 호출 없음.
- **(선택) 라이브 스모크**: 환경변수 `SEC_LIVE=1` 일 때만 도는 실호출 테스트. 기본 AC 에는
  포함되지 않으므로 네트워크 없이도 전체 통과해야 한다.

## Acceptance Criteria
```bash
python3 tests/test_sec_extract.py                 # 네트워크 없이 전체 통과(통합 테스트 포함)
SEC_LIVE=1 python3 -m sec_extract AAPL --segments -o /tmp/seg.xlsx   # 선택: 실데이터 수동 확인
```

## 검증 절차
1. 위 AC(첫 줄) 실행 — 반드시 네트워크 없이 통과.
2. `--segments` 끈 기본 실행이 기존과 동일한지 회귀 확인.
3. index.json step 4 업데이트. 모든 step 완료 시 `phases/index.json` 의
   `1-segments-kpi` 를 completed 로.

## 금지사항
- 테스트에서 기본적으로 실제 SEC API 를 호출하지 마라(라이브 스모크는 SEC_LIVE 게이트).
  이유: 느리고 불안정하며 레이트리밋에 걸린다.
- `--segments` 기본값을 켜지 마라. 이유: 코어 경로 성능 회귀.
