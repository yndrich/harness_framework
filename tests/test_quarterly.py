"""분기 추출(quarterly) + raw_model 어댑터 테스트 (네트워크 불필요).

`python3 tests/test_quarterly.py` 또는 `pytest tests/` 둘 다 동작.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sec_extract.facts import CompanyFacts
from sec_extract import quarterly as qt
from sec_extract import raw_model as rm
from sec_extract.canonical_map import STATEMENTS

# 깔끔한 분기 기간(일수 버킷에 맞게)
P = {
    "Q1": ("2022-02-01", "2022-05-01"),   # ~89d
    "Q2": ("2022-05-01", "2022-07-31"),   # ~91d
    "Q3": ("2022-08-01", "2022-10-31"),   # ~91d
    "6M": ("2022-02-01", "2022-07-31"),   # ~180d
    "9M": ("2022-02-01", "2022-10-31"),   # ~272d
    "FY": ("2022-02-01", "2023-01-31"),   # ~364d
}


def f(val, fp, span, form="10-Q", filed="2023-01-01"):
    s, e = P[span]
    return {"val": val, "fy": 2023, "fp": fp, "form": form, "filed": filed,
            "start": s, "end": e}


def inst(val, fp, end, form="10-Q", filed="2023-01-01"):
    return {"val": val, "fy": 2023, "fp": fp, "form": form, "filed": filed,
            "end": end}


def cf(usgaap):
    return CompanyFacts({"entityName": "T", "cik": 1,
                         "facts": {"us-gaap": usgaap}})


def _usd(facts):
    return {"units": {"USD": facts}}


# ---- 손익: 직접 3개월 + Q4 = 연간 − 9개월 -----------------------------
def test_income_direct_quarters_and_q4():
    """NVDA FY2023 모사: Q1 8288, Q2 6704, Q3 5931, FY 26974 → Q4=6051."""
    c = cf({"Revenues": _usd([
        f(8288, "Q1", "Q1"), f(6704, "Q2", "Q2"), f(5931, "Q3", "Q3"),
        f(20923, "Q3", "9M"),                 # 9개월 YTD = 8288+6704+5931
        f(26974, "FY", "FY", form="10-K"),    # 연간
    ])})
    tags = ["Revenues"]
    assert qt.quarterly_cell(c, tags, 2023, 1, "duration")["val"] == 8288
    assert qt.quarterly_cell(c, tags, 2023, 1, "duration")["method"] == "direct"
    assert qt.quarterly_cell(c, tags, 2023, 2, "duration")["val"] == 6704
    assert qt.quarterly_cell(c, tags, 2023, 3, "duration")["val"] == 5931
    q4 = qt.quarterly_cell(c, tags, 2023, 4, "duration")
    assert q4["val"] == 26974 - 20923 == 6051, q4
    assert q4["method"] == "annual-minus-9mo"


# ---- 현금흐름: YTD 누적만 있을 때 차분 -------------------------------
def test_cashflow_ytd_differencing():
    """3개월 fact 없이 YTD(누적)만: Q1 100, 6M 250, 9M 420, FY 600."""
    c = cf({"NetCashProvidedByUsedInOperatingActivities": _usd([
        f(100, "Q1", "Q1"),       # Q1 = 누적 = 이산 100
        f(250, "Q2", "6M"),       # 6개월 누적
        f(420, "Q3", "9M"),       # 9개월 누적
        f(600, "FY", "FY", form="10-K"),
    ])})
    tags = ["NetCashProvidedByUsedInOperatingActivities"]
    assert qt.quarterly_cell(c, tags, 2023, 1, "duration")["val"] == 100
    q2 = qt.quarterly_cell(c, tags, 2023, 2, "duration")
    assert q2["val"] == 150 and q2["method"] == "ytd-diff", q2   # 250-100
    assert qt.quarterly_cell(c, tags, 2023, 3, "duration")["val"] == 170  # 420-250
    assert qt.quarterly_cell(c, tags, 2023, 4, "duration")["val"] == 180  # 600-420


# ---- 재무상태표: 분기말 시점 잔액 ------------------------------------
def test_balance_sheet_instant():
    c = cf({"Assets": _usd([
        inst(44000, "Q1", "2022-05-01"),
        inst(45000, "Q2", "2022-07-31"),
        inst(41182, "FY", "2023-01-31", form="10-K"),
        # 같은 fy/FY 의 전년 비교 잔액(더 이른 end) — 현재기로 잡히면 안 됨
        inst(26000, "FY", "2022-01-30", form="10-K"),
    ])})
    tags = ["Assets"]
    assert qt.quarterly_cell(c, tags, 2023, 1, "instant")["val"] == 44000
    assert qt.quarterly_cell(c, tags, 2023, 4, "instant")["val"] == 41182  # 전년 26000 아님


def test_picks_current_not_comparative():
    """같은 fy=2024/fp=Q1 버킷의 '전년 비교값'을 현재값으로 오인하면 안 됨.

    companyfacts fy/fp 는 공시의 회계연도라, FY2024 Q1 10-Q 안에 전년(FY2023 Q1)
    비교값이 fy=2024/fp=Q1 로 함께 들어온다. end 가 늦은 현재값을 골라야 한다.
    """
    c = cf({"Revenues": {"units": {"USD": [
        {"val": 7192, "fy": 2024, "fp": "Q1", "form": "10-Q",
         "filed": "2023-05-25", "start": "2023-01-30", "end": "2023-04-30"},
        {"val": 8288, "fy": 2024, "fp": "Q1", "form": "10-Q",   # 전년 비교
         "filed": "2023-05-25", "start": "2022-02-01", "end": "2022-05-01"},
    ]}}})
    cell = qt.quarterly_cell(c, ["Revenues"], 2024, 1, "duration")
    assert cell["val"] == 7192, cell   # 전년 비교 8288 아님


def test_available_quarters():
    c = cf({"Revenues": _usd([
        f(8288, "Q1", "Q1"), f(6704, "Q2", "Q2"), f(5931, "Q3", "Q3"),
        f(20923, "Q3", "9M"), f(26974, "FY", "FY", form="10-K"),
    ])})
    assert qt.available_quarters(c, STATEMENTS) == [
        (2023, 1), (2023, 2), (2023, 3), (2023, 4)]


# ---- 날짜 기반 달력 회수: fy 라벨이 비교표시로 잘못 찍혀도 복구 -------
# 실제 companyfacts 버그: 같은 기간 값이 '공시의 회계연도'(fy)로 흩어진다.
# 예) capex 2024Q1 (기간 2023-01-30~2023-04-30) 값이 fy2025 로 찍혀 있어
# fy/fp 매칭으로는 못 찾는다. 매출로 만든 달력에 날짜로 매핑하면 회수된다.
NV = {  # NVDA fiscal 2024 (start 2023-01-30, end 2024-01-28) 분기 경계
    "start": "2023-01-30",
    "Q1": "2023-04-30", "Q2": "2023-07-30", "Q3": "2023-10-29", "Q4": "2024-01-28",
}


def _rev_fy2024():
    """매출: fy2024 직접 분기 + 9M + FY (달력 정의용, 라벨 정상)."""
    def d(val, fp, s, e, form="10-Q"):
        return {"val": val, "fy": 2024, "fp": fp, "form": form,
                "filed": "2023-06-01", "start": s, "end": e}
    return _usd([
        d(7192, "Q1", NV["start"], NV["Q1"]),
        d(13507, "Q2", "2023-05-01", NV["Q2"]),
        d(18120, "Q3", "2023-07-31", NV["Q3"]),
        d(38819, "Q3", NV["start"], NV["Q3"]),                 # 9M YTD
        d(60922, "FY", NV["start"], NV["Q4"], form="10-K"),    # 연간
    ])


def test_calendar_built_from_revenue():
    c = cf({"Revenues": _rev_fy2024()})
    cal = qt.fiscal_calendar(c, STATEMENTS)
    assert (2024, 1) in cal and (2024, 4) in cal
    assert cal[(2024, 1)]["end"].isoformat() == NV["Q1"]
    assert cal[(2024, 1)]["start"].isoformat() == NV["start"]
    assert cal[(2024, 4)]["end"].isoformat() == NV["Q4"]


def test_recovers_quarter_with_wrong_fy_stamp():
    """capex 90일 fact 가 fy2025 로 잘못 찍혀 있어도 날짜로 직접 회수."""
    c = cf({
        "Revenues": _rev_fy2024(),
        "PaymentsToAcquireProductiveAssets": _usd([
            # fy=2025(비교표시) 로 찍혔지만 기간은 fy2024 Q1
            {"val": 248, "fy": 2025, "fp": "Q1", "form": "10-Q",
             "filed": "2024-05-29", "start": NV["start"], "end": NV["Q1"]},
        ]),
    })
    cal = qt.fiscal_calendar(c, STATEMENTS)
    cell = qt.quarterly_cell(c, ["PaymentsToAcquireProductiveAssets"],
                             2024, 1, "duration", calendar=cal)
    assert cell and cell["val"] == 248, cell


def test_recovers_q4_annual_minus_9mo_across_fy_stamps():
    """연간·9M 이 서로 다른 fy 로 찍혀 있어도 Q4 = 연간 − 9M 회수."""
    c = cf({"Revenues": _rev_fy2024()})
    cell = qt.quarterly_cell(c, ["Revenues"], 2024, 4, "duration",
                             calendar=qt.fiscal_calendar(c, STATEMENTS))
    assert cell["val"] == 60922 - 38819 == 22103, cell
    assert cell["method"] == "annual-minus-9mo"


def test_genuine_gap_returns_none():
    """기간 fact 가 실제로 없으면(날조 금지) None 을 반환한다."""
    c = cf({
        "Revenues": _rev_fy2024(),
        "PaymentsToAcquireProductiveAssets": _usd([  # 9M·FY 만 있고 Q1/Q2 YTD 부재
            {"val": 1324, "fy": 2024, "fp": "Q3", "form": "10-Q",
             "filed": "2023-11-21", "start": NV["start"], "end": NV["Q3"]},
        ]),
    })
    cal = qt.fiscal_calendar(c, STATEMENTS)
    # Q1 은 90일/누적 fact 가 없으므로 회수 불가
    assert qt.quarterly_cell(c, ["PaymentsToAcquireProductiveAssets"],
                             2024, 1, "duration", calendar=cal) is None


def test_instant_matched_by_date_not_fy():
    """재무상태표 잔액을 fy/fp 가 아니라 분기말 날짜로 매칭(태그 변경 흡수)."""
    c = cf({
        "Revenues": _rev_fy2024(),
        "DebtSecuritiesCurrent": {"units": {"USD": [
            # 분기말 2024-01-28 잔액이 다음해 10-Q 비교표시(fy2025)로만 존재
            {"val": 18704, "fy": 2025, "fp": "Q1", "form": "10-Q",
             "filed": "2024-05-29", "end": NV["Q4"]},
        ]}},
    })
    cal = qt.fiscal_calendar(c, STATEMENTS)
    cell = qt.quarterly_cell(c, ["DebtSecuritiesCurrent"], 2024, 4,
                             "instant", calendar=cal)
    assert cell and cell["val"] == 18704, cell


# ---- face 라인 확장 + face_only Review ------------------------------
def test_new_face_lines_extracted():
    """새로 추가한 재무상태표 face 라인(운용리스자산 등)이 날짜로 잡힌다."""
    c = cf({
        "Revenues": _rev_fy2024(),
        "OperatingLeaseRightOfUseAsset": {"units": {"USD": [
            {"val": 4258, "fy": 2024, "fp": "Q1", "form": "10-Q",
             "filed": "2023-06-01", "end": NV["Q1"]},
        ]}},
    })
    cal = qt.fiscal_calendar(c, STATEMENTS)
    cell = qt.quarterly_cell(c, ["OperatingLeaseRightOfUseAsset"], 2024, 1,
                             "instant", calendar=cal)
    assert cell and cell["val"] == 4258, cell


def test_face_only_line_surfaced_as_review():
    """face_only 라인(비시장성증권)은 값 대신 REVIEW 마커 행으로 표면화된다."""
    c = cf({"Revenues": _rev_fy2024()})
    rows = rm.build_rows(c, STATEMENTS, [(2024, 1)])
    nms = [r for r in rows if r["key"] == "non_marketable_securities"]
    assert nms, "비시장성증권 REVIEW 행 없음"
    assert nms[0]["val"] is None
    assert nms[0]["flags"] and nms[0]["flags"][0][0] == "REVIEW", nms[0]


# ---- raw_model: 스케일·tidy 행 ---------------------------------------
def test_build_rows_scaled_and_keyed():
    """raw 달러 → 백만 단위 스케일, Canonical Key·한글 항목 부착."""
    c = cf({"Revenues": _usd([f(8288000000, "Q1", "Q1")])})  # raw $
    rows = rm.build_rows(c, STATEMENTS, [(2023, 1)])
    rev = [r for r in rows if r["key"] == "revenue"]
    assert rev, "revenue row 없음"
    r = rev[0]
    assert r["val"] == 8288.0, r["val"]            # /1e6
    assert r["item"] == "매출" and r["index"] == 2023 * 4 + 1


def test_scale_per_share_untouched():
    assert rm._scale(123456789, "USD") == 123.456789
    assert rm._scale(5.61, "USD/shares") == 5.61


def test_build_rows_attaches_orig_item():
    """label_map 이 주어지면 각 행에 공시 표시라벨(원본 항목명)을 붙인다."""
    c = cf({"Revenues": _usd([f(8288000000, "Q1", "Q1")])})
    lmap = {"us-gaap:Revenues": "Total net revenue"}
    rows = rm.build_rows(c, STATEMENTS, [(2023, 1)], label_map=lmap)
    r = next(row for row in rows if row["key"] == "revenue" and row["val"] is not None)
    assert r["orig_item"] == "Total net revenue"   # 공시 원문 라벨
    assert r["tag"] == "Revenues"                   # 채택된 us-gaap 태그도 기록


def test_build_rows_orig_item_blank_without_map():
    """label_map 없으면 원본 항목명은 공란(핵심 출력 불변)."""
    c = cf({"Revenues": _usd([f(8288000000, "Q1", "Q1")])})
    rows = rm.build_rows(c, STATEMENTS, [(2023, 1)])
    r = next(row for row in rows if row["key"] == "revenue" and row["val"] is not None)
    assert r["orig_item"] == ""


# ---- 분기 선택(--period) -------------------------------------------
def test_parse_period_token():
    assert qt.parse_period_token("2025Q1") == (2025, 1)
    assert qt.parse_period_token(" 2024q3 ") == (2024, 3)   # 공백/소문자 허용


def test_parse_period_token_bad_format():
    for bad in ["2025", "Q1", "2025Q5", "25Q1", "abc", ""]:
        try:
            qt.parse_period_token(bad)
        except ValueError:
            continue
        raise AssertionError(f"형식 오류여야 함: {bad!r}")


_AVAIL = [(2023, 4), (2024, 1), (2024, 2), (2024, 3), (2024, 4), (2025, 1)]


def test_select_periods_single():
    assert qt.select_periods(_AVAIL, ["2025Q1"]) == [(2025, 1)]


def test_select_periods_multiple_dedup_sorted():
    # 순서 뒤섞고 중복 줘도 정렬·중복제거
    assert qt.select_periods(_AVAIL, ["2025Q1", "2024Q1", "2025Q1"]) == [
        (2024, 1), (2025, 1)]


def test_select_periods_range_inclusive():
    assert qt.select_periods(_AVAIL, ["2024Q1:2024Q4"]) == [
        (2024, 1), (2024, 2), (2024, 3), (2024, 4)]


def test_select_periods_range_reversed_ok():
    # 큰:작은 순서로 줘도 정상화
    assert qt.select_periods(_AVAIL, ["2024Q4:2024Q1"]) == [
        (2024, 1), (2024, 2), (2024, 3), (2024, 4)]


def test_select_periods_unavailable_raises():
    for bad in ["2019Q1", "2025Q4"]:
        try:
            qt.select_periods(_AVAIL, [bad])
        except ValueError:
            continue
        raise AssertionError(f"미존재 분기여야 함: {bad}")


# ---- Raw Data 시트 쓰기(헤더·원본 열·단위 표시) -----------------------
def _read_sheet(z, idx):
    from xml.etree import ElementTree as ET
    ns = {"a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}

    def val(c):
        if c.get("t") == "inlineStr":
            return "".join(n.text or "" for n in c.iter() if n.tag.endswith('}t'))
        v = c.find("a:v", ns)
        return v.text if v is not None else ""
    t = ET.fromstring(z.read(f"xl/worksheets/sheet{idx}.xml"))
    return [[val(c) for c in r.findall("a:c", ns)] for r in t.findall(".//a:row", ns)]


def test_raw_data_sheet_has_orig_column_and_unit_note():
    import zipfile
    from xml.etree import ElementTree as ET
    from sec_extract.raw_model import write_raw_model_workbook, UNIT_NOTE
    c = cf({"Revenues": _usd([f(8288000000, "Q1", "Q1")])})
    lmap = {"us-gaap:Revenues": "Total net revenue"}
    rows = rm.build_rows(c, STATEMENTS, [(2023, 1)], label_map=lmap)
    path = os.path.join(os.path.dirname(__file__), "_smoke_raw.xlsx")
    write_raw_model_workbook([("T", rows, [(2023, 1)])], path)
    try:
        z = zipfile.ZipFile(path)
        names = [s.get("name")
                 for s in ET.fromstring(z.read("xl/workbook.xml")).iter()
                 if s.tag.endswith("}sheet")]
        idx = {nm: i + 1 for i, nm in enumerate(names)}
        sheet = _read_sheet(z, idx["Raw Data"])
        assert sheet[1] == ["년도", "분기", "Index", "항목(원본)", "항목", "값",
                            "Canonical Key", "기간"], sheet[1]
        rev = next(r for r in sheet[2:] if len(r) >= 5 and r[3] == "Total net revenue")
        assert rev[4] == "매출"                       # 항목(표준 한글) 그대로
        # 단위 안내가 시트 상단 어딘가에 존재
        flat = [cell for row in sheet for cell in row]
        assert UNIT_NOTE in flat, "단위 표시 없음"
    finally:
        os.remove(path)


# ---- 독립 실행 러너 ---------------------------------------------------
def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t(); print(f"  PASS {t.__name__}"); passed += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(_run_all())
