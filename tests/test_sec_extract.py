"""sec_extract 단위 테스트 (네트워크 불필요).

pytest 가 있으면 `pytest tests/`, 없으면 `python3 tests/test_sec_extract.py` 로
바로 실행된다 (둘 다 지원).
"""

import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sec_extract.facts import CompanyFacts
from sec_extract import normalize as nz
from sec_extract.canonical_map import STATEMENTS
from sec_extract.excel import write_workbook
from sec_extract import xlsx
from sec_extract import submissions as sub


# ---- 합성 companyfacts 빌더 -------------------------------------------
def dur(val, year, accn, filed, form="10-K"):
    return {"val": val, "accn": accn, "fy": year, "fp": "FY", "form": form,
            "filed": filed, "start": f"{year}-01-01", "end": f"{year}-12-31"}


def inst(val, year, accn, filed, form="10-K"):
    return {"val": val, "accn": accn, "fy": year, "fp": "FY", "form": form,
            "filed": filed, "end": f"{year}-12-31"}


def make_facts(usgaap):
    return CompanyFacts({"entityName": "Test Co", "cik": 1,
                         "facts": {"us-gaap": usgaap}})


def _usd(facts):
    return {"units": {"USD": facts}}


# ---- 테스트 -----------------------------------------------------------
def test_tag_change_over_years():
    """구 태그(Revenues) -> 신 태그로 바뀌어도 연도별로 올바른 값을 채택."""
    cf = make_facts({
        "Revenues": _usd([
            dur(100, 2019, "a1", "2020-02-01"),
            dur(110, 2020, "a2", "2021-02-01"),
        ]),
        "RevenueFromContractWithCustomerExcludingAssessedTax": _usd([
            dur(130, 2021, "a3", "2022-02-01"),
            dur(150, 2022, "a4", "2023-02-01"),
        ]),
    })
    line = STATEMENTS[0]["lines"][0]  # revenue
    for y, exp, exp_tag in [(2019, 100, "Revenues"), (2020, 110, "Revenues"),
                            (2021, 130, "RevenueFromContractWithCustomerExcludingAssessedTax"),
                            (2022, 150, "RevenueFromContractWithCustomerExcludingAssessedTax")]:
        cell = nz.resolve_cell(cf, line["tags"], y, "duration")
        assert cell is not None and cell["val"] == exp, (y, cell)
        assert cell["tag"] == exp_tag, (y, cell["tag"])


def test_restatement_flagged():
    """같은 2021 값을 두 공시가 다르게 보고 -> 최신 채택 + RESTATED 플래그."""
    cf = make_facts({"NetIncomeLoss": _usd([
        dur(100, 2021, "old", "2022-02-01"),   # 원 보고
        dur(115, 2021, "new", "2023-02-01"),   # 후속 10-K 비교란 (재작성)
    ])})
    cell = nz.resolve_cell(cf, ["NetIncomeLoss"], 2021, "duration")
    assert cell["val"] == 115, cell["val"]      # 최신 제출본
    assert any(f[0] == "RESTATED" for f in cell["flags"]), cell["flags"]


def test_ambiguous_flagged():
    """후보 태그 두 개가 서로 다른 값 -> AMBIGUOUS."""
    cf = make_facts({
        "RevenueFromContractWithCustomerExcludingAssessedTax": _usd([
            dur(200, 2022, "a", "2023-02-01")]),
        "Revenues": _usd([dur(180, 2022, "b", "2023-02-01")]),
    })
    line = STATEMENTS[0]["lines"][0]
    cell = nz.resolve_cell(cf, line["tags"], 2022, "duration")
    assert cell["val"] == 200       # 우선순위 1번 태그
    assert any(f[0] == "AMBIGUOUS" for f in cell["flags"]), cell["flags"]


def test_gap_marked():
    """값이 2019, 2022 만 있고 중간이 비면 GAP 표시."""
    cf = make_facts({"GrossProfit": _usd([
        dur(50, 2019, "a", "2020-02-01"),
        dur(80, 2022, "b", "2023-02-01"),
    ])})
    cells = {y: nz.resolve_cell(cf, ["GrossProfit"], y, "duration")
             for y in [2019, 2020, 2021, 2022]}
    nz._mark_gaps(cells, [2019, 2020, 2021, 2022])
    assert any(f[0] == "GAP" for f in cells[2020]["flags"])
    assert any(f[0] == "GAP" for f in cells[2021]["flags"])


def test_instant_ignores_quarterly():
    """재무상태표(시점)는 10-K 연말 잔액만, 10-Q 분기값은 무시."""
    cf = make_facts({"Assets": {"units": {"USD": [
        inst(1000, 2022, "k", "2023-02-01", form="10-K"),
        {"val": 950, "accn": "q", "fy": 2022, "fp": "Q3", "form": "10-Q",
         "filed": "2022-10-01", "end": "2022-09-30"},
    ]}}})
    cell = nz.resolve_cell(cf, ["Assets"], 2022, "instant")
    assert cell["val"] == 1000, cell
    # 분기 9/30 값은 그 연도 시점값으로 잡히면 안 됨 (10-K 만 채택)


def test_available_years_and_normalize():
    cf = make_facts({
        "Revenues": _usd([dur(100, 2020, "a", "2021-02-01"),
                          dur(110, 2021, "b", "2022-02-01")]),
        "Assets": {"units": {"USD": [inst(500, 2020, "a", "2021-02-01"),
                                     inst(550, 2021, "b", "2022-02-01")]}},
    })
    years = nz.available_years(cf, STATEMENTS)
    assert years == [2020, 2021], years
    data = nz.normalize_company(cf, STATEMENTS, years)
    assert data["income_statement"]["revenue"][2021]["val"] == 110
    assert data["balance_sheet"]["total_assets"][2020]["val"] == 500


def test_workbook_is_valid_xlsx(tmp_path=None):
    """엑셀 생성 스모크 테스트: 유효한 zip + 기대 시트 존재."""
    cf = make_facts({
        "Revenues": _usd([dur(100, 2021, "a", "2022-02-01"),
                          dur(120, 2022, "b", "2023-02-01")]),
        "NetIncomeLoss": _usd([dur(10, 2021, "a", "2022-02-01"),
                               dur(15, 2022, "b", "2023-02-01")]),
        "Assets": {"units": {"USD": [inst(500, 2021, "a", "2022-02-01"),
                                     inst(600, 2022, "b", "2023-02-01")]}},
    })
    years = nz.available_years(cf, STATEMENTS)
    data = nz.normalize_company(cf, STATEMENTS, years)
    comp = nz.CompanyResult("TEST", "Test Co", "0000000001", "Test Co",
                            years, data)
    out = os.path.join(os.path.dirname(__file__), "_smoke.xlsx")
    write_workbook([comp], STATEMENTS, out)
    assert zipfile.is_zipfile(out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "xl/workbook.xml" in names
        assert "[Content_Types].xml" in names
        wb = z.read("xl/workbook.xml").decode()
        for sheet in ["Income Statement", "Balance Sheet", "Cash Flow",
                      "Comparison", "Review", "Provenance"]:
            assert sheet in wb, sheet
    os.remove(out)


def test_xlsx_cell_ref():
    assert xlsx.cell_ref(1, 1) == "A1"
    assert xlsx.cell_ref(3, 27) == "AA3"
    assert xlsx.cell_ref(10, 28) == "AB10"


# ---- submissions-locator (phase 1-segments-kpi, step 0) ---------------
def _synthetic_submissions():
    """합성 submissions JSON: 10-K · 10-K/A · 10-Q 가 섞여 있고,
    report_date 2022-09-24 는 원본 10-K + 정정본 10-K/A 두 건."""
    return {
        "cik": "320193",
        "filings": {
            "recent": {
                "accessionNumber": [
                    "0000320193-24-000123",   # 10-K   FY2024
                    "0000320193-24-000010",   # 10-Q   (제외 대상)
                    "0000320193-23-000106",   # 10-K   FY2023
                    "0000320193-23-000050",   # 10-K/A FY2022 (정정본, 최신 filing)
                    "0000320193-22-000108",   # 10-K   FY2022 (원본)
                    "0000320193-21-000105",   # 10-K   FY2021
                    "0000320193-20-000096",   # 10-K   FY2020 (비-inline)
                ],
                "form": ["10-K", "10-Q", "10-K", "10-K/A", "10-K", "10-K", "10-K"],
                "filingDate": ["2024-11-01", "2024-08-02", "2023-11-03",
                               "2023-06-15", "2022-10-28", "2021-10-29",
                               "2020-10-30"],
                "reportDate": ["2024-09-28", "2024-06-29", "2023-09-30",
                               "2022-09-24", "2022-09-24", "2021-09-25",
                               "2020-09-26"],
                "primaryDocument": ["aapl-20240928.htm", "aapl-20240629.htm",
                                    "aapl-20230930.htm", "aapl-20220924a.htm",
                                    "aapl-20220924.htm", "aapl-20210925.htm",
                                    "aapl-20200926.htm"],
                "isXBRL": [1, 1, 1, 1, 1, 1, 1],
                "isInlineXBRL": [1, 1, 1, 1, 1, 1, 0],
            }
        },
    }


class _FakeClient:
    """SecClient 의 get_json 만 흉내내는 스텁 (네트워크 없음)."""

    def __init__(self, responses):
        self.responses = responses
        self.requested = []

    def get_json(self, url, refresh=False):
        self.requested.append(url)
        return self.responses[url]


def test_select_annual_filings_filters_and_dedups():
    """10-Q 제외, report_date 내림차순, 같은 report_date 는 최신 filing 1건."""
    rows = sub.select_annual_filings(_synthetic_submissions(), n_years=5)
    assert [r["report_date"] for r in rows] == [
        "2024-09-28", "2023-09-30", "2022-09-24", "2021-09-25", "2020-09-26"]
    assert all(r["form"] in ("10-K", "10-K/A") for r in rows)
    # 2022 는 정정본(10-K/A, 더 늦게 제출)으로 dedup 되어야 한다.
    r2022 = next(r for r in rows if r["report_date"] == "2022-09-24")
    assert r2022["form"] == "10-K/A", r2022
    assert r2022["filing_date"] == "2023-06-15", r2022
    assert r2022["accn"] == "0000320193-23-000050", r2022


def test_select_annual_filings_n_years_limit():
    """report_date 내림차순 상위 n_years 만."""
    rows = sub.select_annual_filings(_synthetic_submissions(), n_years=2)
    assert [r["report_date"] for r in rows] == ["2024-09-28", "2023-09-30"]


def test_select_annual_filings_row_shape():
    """각 행의 키/형 변환(대시 제거 accession, bool 플래그)을 검증."""
    rows = sub.select_annual_filings(_synthetic_submissions(), n_years=5)
    r = rows[0]
    assert r["accn"] == "0000320193-24-000123"
    assert r["accn_nodash"] == "000032019324000123"
    assert r["primary_document"] == "aapl-20240928.htm"
    assert r["is_inline_xbrl"] is True
    assert r["is_xbrl"] is True
    r2020 = next(x for x in rows if x["report_date"] == "2020-09-26")
    assert r2020["is_inline_xbrl"] is False


def test_filing_index_url():
    """Archives 경로: cik 는 0 패딩 없는 정수, 폴더명은 대시 없는 accession."""
    url = sub.filing_index_url(320193, "000032019324000123")
    assert url == ("https://www.sec.gov/Archives/edgar/data/"
                   "320193/000032019324000123/index.json")


def test_find_instance_url_inline_uses_primary_htm():
    """inline-XBRL: 주 문서(.htm) 자체가 인스턴스. SecClient 경유로 index 확인."""
    filing = {"accn_nodash": "000032019324000123",
              "primary_document": "aapl-20240928.htm",
              "is_inline_xbrl": True}
    idx_url = sub.filing_index_url(320193, "000032019324000123")
    base = "https://www.sec.gov/Archives/edgar/data/320193/000032019324000123/"
    client = _FakeClient({idx_url: {"directory": {"item": [
        {"name": "aapl-20240928.htm", "type": "10-K"},
        {"name": "aapl-20240928_htm.xml", "type": "XML"},
        {"name": "Financial_Report.xlsx", "type": "EXCEL"},
    ]}}})
    url = sub.find_instance_url(client, 320193, filing)
    assert url == base + "aapl-20240928.htm", url
    assert client.requested == [idx_url]   # 직접 urllib 금지, SecClient 만


def test_find_instance_url_non_inline_finds_xml_instance():
    """비-inline: primary_document 가 아니라 index 의 별도 .xml 인스턴스를 찾는다."""
    filing = {"accn_nodash": "000032019320000096",
              "primary_document": "a10-k20200926.htm",
              "is_inline_xbrl": False}
    idx_url = sub.filing_index_url(320193, "000032019320000096")
    base = "https://www.sec.gov/Archives/edgar/data/320193/000032019320000096/"
    client = _FakeClient({idx_url: {"directory": {"item": [
        {"name": "aapl-20200926.xsd", "type": "EX-101.SCH"},
        {"name": "aapl-20200926_cal.xml", "type": "EX-101.CAL"},
        {"name": "aapl-20200926_def.xml", "type": "EX-101.DEF"},
        {"name": "aapl-20200926_lab.xml", "type": "EX-101.LAB"},
        {"name": "aapl-20200926_pre.xml", "type": "EX-101.PRE"},
        {"name": "aapl-20200926.xml", "type": "EX-101.INS"},
        {"name": "a10-k20200926.htm", "type": "10-K"},
    ]}}})
    url = sub.find_instance_url(client, 320193, filing)
    assert url == base + "aapl-20200926.xml", url


# ---- 독립 실행 러너 (pytest 없이도 동작) -------------------------------
def _run_all():
    tests = [v for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"  PASS {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"  FAIL {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"  ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    return 0 if passed == len(tests) else 1


if __name__ == "__main__":
    raise SystemExit(_run_all())
