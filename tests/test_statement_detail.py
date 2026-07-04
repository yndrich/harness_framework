"""as-reported 전체 재무제표 추출(statement_detail) 테스트 — 네트워크 불필요.

`python3 tests/test_statement_detail.py` 또는 `pytest tests/` 둘 다 동작.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sec_extract import statement_detail as st

FY_START = date(2023, 1, 30)
Q = {1: date(2023, 4, 30), 2: date(2023, 7, 30),
     3: date(2023, 10, 29), 4: date(2024, 1, 28)}
CAL = {(2024, q): {"start": FY_START, "end": Q[q]} for q in (1, 2, 3, 4)}
GEO = "srt:StatementGeographicalAxis"


def dur(concept, val, start, end, form="10-Q", accn="a1", filed="2023-06-01",
        dims=None):
    return {"concept": concept, "value": val, "dims": dims or {},
            "start": start.isoformat(), "end": end.isoformat(),
            "unit": "usd", "form": form, "accn": accn, "filed": filed}


def inst(concept, val, end, unit="usd", form="10-Q", accn="a1", filed="2023-06-01"):
    return {"concept": concept, "value": val, "dims": {},
            "start": None, "end": end.isoformat(), "instant": end.isoformat(),
            "unit": unit, "form": form, "accn": accn, "filed": filed}


def _facts():
    f = []
    # 손익(duration): 회사 커스텀 태그(Transaction expense) — companyfacts 엔 없지만
    # inline-XBRL 엔 있다. Q1 직접 100, 6M 210(→ Q2=110 차분).
    f += [dur("coin:TransactionExpense", 100, FY_START, Q[1]),
          dur("coin:TransactionExpense", 210, FY_START, Q[2])]
    # 손익 표준 태그(canonical 소속 → 권위적 분류)
    f += [dur("us-gaap:ResearchAndDevelopmentExpense", 50, FY_START, Q[1])]
    # 손익 미지의 표준 태그(canonical 밖 → 추정)
    f += [dur("us-gaap:SellingAndMarketingExpense", 30, FY_START, Q[1])]
    # 현금흐름(duration, 이름 휴리스틱)
    f += [dur("us-gaap:NetCashProvidedByUsedInOperatingActivities", 500,
              FY_START, Q[1])]
    # 재무상태(instant): 표준(권위적). Q1/Q2 분기말 + 연말(FY 잔액용)
    f += [inst("us-gaap:Assets", 9000, Q[1]),
          inst("us-gaap:Assets", 9500, Q[2]),
          inst("us-gaap:Assets", 9800, Q[4], form="10-K")]
    # 차원 있는 fact(=segment_detail 몫) → 본표 추출에서 제외
    f += [dur("us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax", 70,
              FY_START, Q[1], dims={GEO: "country:US"})]
    # dei(표지 정보) → 재무제표 아님 → 제외
    f += [inst("dei:EntityCommonStockSharesOutstanding", 250, Q[1], unit="shares")]
    return f


def _build(label_map=None):
    return st.build_as_reported_statements(
        _facts(), CAL, periods=[(2024, 1), (2024, 2)], annual_years=[2024],
        label_map=label_map)


def test_custom_tag_captured():
    """companyfacts 엔 없는 회사 커스텀 태그도 as-reported 로 잡힌다."""
    out = _build()
    tx = [r for r in out["rows"] if r["concept"] == "coin:TransactionExpense"]
    assert tx, "Transaction expense(커스텀 태그) 누락"
    q1 = next(r for r in tx if r["quarter"] == 1)
    assert q1["val"] == 100
    q2 = next(r for r in tx if r["quarter"] == 2)
    assert q2["val"] == 110          # 210 − 100 (6M YTD 차분)
    assert q1["statement"] == "income_statement"
    assert q1["guessed"] is True     # canonical 밖 → 추정


def test_known_tag_authoritative_classification():
    out = _build()
    rd = next(r for r in out["rows"]
              if r["concept"] == "us-gaap:ResearchAndDevelopmentExpense")
    assert rd["statement"] == "income_statement"
    assert rd["guessed"] is False    # canonical 소속 → 권위적


def test_balance_sheet_instant_and_cashflow():
    out = _build()
    a = next(r for r in out["rows"]
             if r["concept"] == "us-gaap:Assets" and r["quarter"] == 1)
    assert a["statement"] == "balance_sheet" and a["val"] == 9000
    cfo = next(r for r in out["rows"]
               if r["concept"].endswith("OperatingActivities"))
    assert cfo["statement"] == "cash_flow"


def test_unknown_duration_defaults_income_guessed():
    out = _build()
    sm = next(r for r in out["rows"]
              if r["concept"] == "us-gaap:SellingAndMarketingExpense")
    assert sm["statement"] == "income_statement"
    assert sm["guessed"] is True


def test_dimensional_and_dei_excluded():
    """차원 있는 fact 와 dei(표지) 는 본표 추출에서 제외한다."""
    out = _build()
    concepts = {r["concept"] for r in out["rows"]}
    assert "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax" \
        not in concepts                                   # 차원 있음 → 제외
    assert not any(c.startswith("dei:") for c in concepts)  # 표지 → 제외


def test_orig_label_attached():
    out = _build(label_map={"coin:TransactionExpense": "Transaction expense"})
    tx = next(r for r in out["rows"] if r["concept"] == "coin:TransactionExpense")
    assert tx["orig"] == "Transaction expense"


def test_annual_fy_row():
    out = _build()
    fy = next((r["val"] for r in out["rows"]
               if r["concept"] == "us-gaap:Assets" and r["quarter"] == "FY"), None)
    assert fy == 9800     # 회계연도 말(Q4) 잔액


def test_classify_helper():
    assert st.classify("us-gaap:Assets", "instant") == ("balance_sheet", False)
    assert st.classify("us-gaap:NetCashProvidedByUsedInFinancingActivities",
                       "duration") == ("cash_flow", False)
    # 미지의 instant → 재무상태표(추정)
    assert st.classify("xx:SomethingBalance", "instant") == ("balance_sheet", True)
    # 미지의 현금흐름형 이름 → 현금흐름표(추정)
    assert st.classify("xx:PaymentsToAcquireWidgets", "duration") == \
        ("cash_flow", True)
    # 미지의 duration → 손익(추정)
    assert st.classify("xx:MysteryExpense", "duration") == ("income_statement", True)


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


def test_as_reported_sheet_written():
    """As-Reported 시트: 헤더·단위표시·커스텀 태그 행이 워크북에 실제로 쓰인다."""
    import zipfile
    from xml.etree import ElementTree as ET
    from sec_extract.raw_model import write_raw_model_workbook, UNIT_NOTE_ASREP
    out = _build(label_map={"coin:TransactionExpense": "Transaction expense"})
    path = os.path.join(os.path.dirname(__file__), "_smoke_asrep.xlsx")
    # company 튜플: (ticker, rows, periods, seg_detail=None, stmt_detail)
    write_raw_model_workbook(
        [("COIN", [], [(2024, 1), (2024, 2)], None, out)], path)
    try:
        z = zipfile.ZipFile(path)
        names = [s.get("name")
                 for s in ET.fromstring(z.read("xl/workbook.xml")).iter()
                 if s.tag.endswith("}sheet")]
        idx = {nm: i + 1 for i, nm in enumerate(names)}
        assert "As-Reported" in idx, names
        rows = _read_sheet(z, idx["As-Reported"])
        assert rows[1] == ["구분", "년도", "분기", "Index", "항목(원본)",
                           "us-gaap 태그", "값", "기간"], rows[1]
        tx = next(r for r in rows[2:] if len(r) >= 6
                  and r[5] == "coin:TransactionExpense" and r[2] == "1")
        assert tx[0] == "손익계산서"          # 구분
        assert tx[4] == "Transaction expense"  # 항목(원본)
        assert float(tx[6]) == 0.0001          # 100 / 1e6 ($M 스케일)
        flat = [c for row in rows for c in row]
        assert UNIT_NOTE_ASREP in flat
    finally:
        os.remove(path)


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
