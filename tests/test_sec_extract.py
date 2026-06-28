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
from sec_extract.canonical_map import STATEMENTS, KNOWN_AXES
from sec_extract.excel import write_workbook
from sec_extract import xlsx
from sec_extract import submissions as sub
from sec_extract import xbrl_instance as xi
from sec_extract import segments as seg
from sec_extract import cli


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


def test_financial_company_fallback_tags():
    """은행/거래소형 기업(COIN 등)이 쓰는 catch-all 태그를 표준 라인이 폴백으로
    잡는다: 이자이익=InterestIncomeOperating, 운전자본 변동=OtherOperating자산/부채.
    특정 태그가 없어 단일 후보 → AMBIGUOUS 없이 깔끔히 채택해야 한다."""
    cf = make_facts({
        "InterestIncomeOperating": _usd([dur(174, 2023, "a1", "2024-02-01")]),
        "IncreaseDecreaseInOtherOperatingAssets":
            _usd([dur(-28, 2023, "a1", "2024-02-01")]),
        "IncreaseDecreaseInOtherOperatingLiabilities":
            _usd([dur(109, 2023, "a1", "2024-02-01")]),
    })

    def line(skey, lkey):
        st = next(s for s in STATEMENTS if s["key"] == skey)
        return next(l for l in st["lines"] if l["key"] == lkey)

    for skey, lkey, exp, tag in [
        ("income_statement", "interest_income", 174, "InterestIncomeOperating"),
        ("cash_flow", "chg_prepaid_other", -28,
         "IncreaseDecreaseInOtherOperatingAssets"),
        ("cash_flow", "chg_accrued_liabilities", 109,
         "IncreaseDecreaseInOtherOperatingLiabilities"),
    ]:
        cell = nz.resolve_cell(cf, line(skey, lkey)["tags"], 2023, "duration")
        assert cell and cell["val"] == exp, (lkey, cell)
        assert cell["tag"] == tag, (lkey, cell["tag"])
        assert not any(f[0] == "AMBIGUOUS" for f in cell["flags"]), cell["flags"]


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


def test_xlsx_autofilter_and_colorscale_wellformed(tmp_path=None):
    """자동필터·색조가 well-formed 이고 스키마 요소 순서(autoFilter→mergeCells→
    conditionalFormatting)를 지킨다 — 순서 틀리면 Excel 이 복구 경고를 띄운다."""
    import xml.etree.ElementTree as ET
    wb = xlsx.Workbook()
    sh = wb.add_sheet("P")
    for c in range(1, 4):
        sh.write(2, c, f"h{c}", bold=True)
    sh.write(3, 1, "매출"); sh.write(3, 2, 100); sh.write(3, 3, 200)
    sh.merge(1, 1, 1, 3)
    sh.auto_filter(2, 1, 3, 3)
    sh.color_scale(3, 2, 3, 3)
    path = os.path.join(os.path.dirname(__file__), "_smoke_xlsx.xlsx")
    wb.save(path)
    z = zipfile.ZipFile(path)
    sx = z.read("xl/worksheets/sheet1.xml").decode()
    ET.fromstring(sx)                       # well-formed XML
    i_data = sx.index("</sheetData>")
    i_af = sx.index("<autoFilter")
    i_mc = sx.index("<mergeCells")
    i_cf = sx.index("<conditionalFormatting")
    assert i_data < i_af < i_mc < i_cf, "스키마 요소 순서 위반"
    assert "colorScale" in sx and 'type="colorScale"' in sx
    os.remove(path)


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


# ---- inline-xbrl-parser (phase 1-segments-kpi, step 1) ----------------
# 합성 inline-XBRL(주.htm 형태). 차원 없는 fact 와 차원 있는 fact 가 섞여 있다.
_INLINE_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<xhtml xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
       xmlns:xbrli="http://www.xbrl.org/2003/instance"
       xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
       xmlns:us-gaap="http://fasb.org/us-gaap/2024"
       xmlns:srt="http://fasb.org/srt/2024">
  <xbrli:context id="c-total">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-product">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000320193</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="srt:ProductOrServiceAxis">us-gaap:ProductMember</xbrldi:explicitMember>
      </xbrli:segment>
    </xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
                  contextRef="c-total" unitRef="usd" decimals="-6" scale="6"
                  format="ixt:num-dot-decimal">391,035</ix:nonFraction>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
                  contextRef="c-product" unitRef="usd" decimals="-6" scale="6"
                  format="ixt:num-dot-decimal">294,866</ix:nonFraction>
</xhtml>"""


def test_parse_instance_dims_and_period():
    """축/멤버(dims)·기간(start/end) 추출 + 차원 없는/있는 fact 모두 반환."""
    facts = xi.parse_instance(_INLINE_DOC)
    assert len(facts) == 2, facts
    by_ctx = {f["context_ref"]: f for f in facts}
    total, prod = by_ctx["c-total"], by_ctx["c-product"]
    # 차원 유무로 거르지 않는다 — 둘 다 보존.
    assert total["dims"] == {}
    assert prod["dims"] == {"srt:ProductOrServiceAxis": "us-gaap:ProductMember"}
    # 기간(duration).
    assert total["start"] == "2023-10-01" and total["end"] == "2024-09-28"
    assert total["instant"] is None
    # concept/unit/decimals 보존.
    assert total["concept"] == ("us-gaap:"
                                "RevenueFromContractWithCustomerExcludingAssessedTax")
    assert total["unit"] == "usd"
    assert total["decimals"] == "-6"
    # scale 적용(배율), decimals 는 곱하지 않음.
    assert total["value"] == 391035 * 10 ** 6
    assert prod["value"] == 294866 * 10 ** 6


def test_parse_instance_scale_sign_comma():
    """콤마 서식 + scale=6 + sign=- → 올바른 음수 큰 값. decimals 는 배율 아님."""
    doc = """<?xml version="1.0"?>
<xbrl xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024">
  <xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="s">x</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period></xbrli:context>
  <ix:nonFraction name="us-gaap:NetIncomeLoss" contextRef="c1" unitRef="usd"
      decimals="-6" scale="6" sign="-" format="ixt:num-dot-decimal">1,234,567</ix:nonFraction>
</xbrl>"""
    facts = xi.parse_instance(doc)
    assert len(facts) == 1
    f = facts[0]
    assert f["value"] == -1234567 * 10 ** 6, f["value"]
    assert f["instant"] == "2024-09-28"
    assert f["start"] is None and f["end"] is None
    assert f["decimals"] == "-6"          # 메타데이터일 뿐, 곱하지 않음
    assert f["raw_text"] == "1,234,567"   # 원본 표시 텍스트 보존


def test_parse_instance_comma_decimal_format():
    """유럽식(num-comma-decimal): 점=천단위, 콤마=소수점 → 1.234,56 == 1234.56."""
    doc = """<?xml version="1.0"?>
<xbrl xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
      xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:us-gaap="http://fasb.org/us-gaap/2024">
  <xbrli:context id="c1"><xbrli:entity><xbrli:identifier scheme="s">x</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:instant>2024-09-28</xbrli:instant></xbrli:period></xbrli:context>
  <ix:nonFraction name="us-gaap:EarningsPerShareDiluted" contextRef="c1"
      unitRef="usd-per-share" decimals="2" scale="0"
      format="ixt:num-comma-decimal">1.234,56</ix:nonFraction>
</xbrl>"""
    f = xi.parse_instance(doc)[0]
    assert f["value"] == 1234.56, f["value"]


def test_parse_instance_plain_xml_instance():
    """비-inline 별도 .xml 인스턴스의 plain fact 도 prefix 복원하여 보존(차원 포함)."""
    doc = """<?xml version="1.0"?>
<xbrl xmlns:xbrli="http://www.xbrl.org/2003/instance"
      xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
      xmlns:us-gaap="http://fasb.org/us-gaap/2020"
      xmlns:srt="http://fasb.org/srt/2020">
  <xbrli:context id="c-geo">
    <xbrli:entity><xbrli:identifier scheme="s">x</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">country:US</xbrldi:explicitMember>
      </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2019-09-29</xbrli:startDate><xbrli:endDate>2020-09-26</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax contextRef="c-geo" unitRef="usd" decimals="-6">100000000000</us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax>
</xbrl>"""
    facts = xi.parse_instance(doc)
    assert len(facts) == 1, facts
    f = facts[0]
    assert f["concept"] == ("us-gaap:"
                            "RevenueFromContractWithCustomerExcludingAssessedTax")
    assert f["value"] == 100000000000
    assert f["dims"] == {"srt:StatementGeographicalAxis": "country:US"}
    assert f["start"] == "2019-09-29" and f["end"] == "2020-09-26"


def test_parse_instance_lenient_on_broken_xhtml():
    """미정의 엔티티(&nbsp;)로 ET 가 깨져도 관대한 경로로 부분 결과를 낸다."""
    doc = """<html xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
       xmlns:xbrli="http://www.xbrl.org/2003/instance"
       xmlns:xbrldi="http://xbrl.org/2006/xbrldi">
  <body>
    <p>Revenue&nbsp;by&nbsp;geography</p>
    <xbrli:context id="c1">
      <xbrli:entity><xbrli:segment>
        <xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">srt:AmericasMember</xbrldi:explicitMember>
      </xbrli:segment></xbrli:entity>
      <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
    </xbrli:context>
    <ix:nonFraction name="us-gaap:Revenues" contextRef="c1" unitRef="usd"
        scale="6" sign="-" format="ixt:num-dot-decimal">12,345</ix:nonFraction>&nbsp;
  </body>
</html>"""
    facts = xi.parse_instance(doc)
    assert len(facts) == 1, facts
    f = facts[0]
    assert f["concept"] == "us-gaap:Revenues"
    assert f["value"] == -12345 * 10 ** 6
    assert f["dims"] == {"srt:StatementGeographicalAxis": "srt:AmericasMember"}
    assert f["start"] == "2023-10-01" and f["end"] == "2024-09-28"


class _FakeTextClient:
    """SecClient.get_text 만 흉내내는 스텁 (네트워크 없음)."""

    def __init__(self, text):
        self.text = text
        self.requested = []

    def get_text(self, url, refresh=False):
        self.requested.append(url)
        return self.text


def test_parse_instance_url_uses_client_get_text():
    """네트워크 경계: parse_instance_url 은 SecClient.get_text 경유로만 받는다."""
    client = _FakeTextClient(_INLINE_DOC)
    url = ("https://www.sec.gov/Archives/edgar/data/320193/"
           "000032019324000123/aapl-20240928.htm")
    facts = xi.parse_instance_url(client, url)
    assert client.requested == [url]   # 직접 urllib 금지, SecClient 만
    assert len(facts) == 2


# ---- segment-mapping (phase 1-segments-kpi, step 2) -------------------
# 합성 차원 fact (xbrl_instance.parse_instance 출력 형태). 매출(revenue) 후보
# 태그는 canonical_map 의 revenue 항목과 공유한다.
_REVENUE_TAGS = STATEMENTS[0]["lines"][0]["tags"]
_REV = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def seg_fact(concept, value, year, dims):
    """xbrl_instance fact 모양의 연간(duration) 합성 fact."""
    return {"concept": concept, "value": value, "raw_text": str(value),
            "unit": "usd", "decimals": "-6", "context_ref": "c",
            "dims": dims, "start": f"{year}-01-01", "end": f"{year}-12-31",
            "instant": None}


def test_segments_known_axes_aggregate():
    """알려진 축(geography/product) → 올바른 group, 멤버×연도 집계 정확, 플래그 없음."""
    geo, prod = "srt:StatementGeographicalAxis", "srt:ProductOrServiceAxis"
    facts = [
        seg_fact(_REV, 391035, 2024, {}),                 # 무차원 총계
        seg_fact(_REV, 383285, 2023, {}),
        seg_fact(_REV, 167045, 2024, {geo: "country:US"}),
        seg_fact(_REV, 223990, 2024, {geo: "us-gaap:NonUsMember"}),
        seg_fact(_REV, 294866, 2024, {prod: "us-gaap:ProductMember"}),
        seg_fact(_REV, 96169, 2024, {prod: "us-gaap:ServiceMember"}),
    ]
    out = seg.build_disaggregation(facts, [2023, 2024], _REVENUE_TAGS)
    assert KNOWN_AXES[geo] == "geography" and KNOWN_AXES[prod] == "product"
    assert out["geography"]["country:US"][2024] == 167045
    assert out["geography"]["us-gaap:NonUsMember"][2024] == 223990
    assert out["product"]["us-gaap:ProductMember"][2024] == 294866
    assert out["product"]["us-gaap:ServiceMember"][2024] == 96169
    # 표준 네임스페이스 멤버 + 합=총계 → REVIEW 플래그 전혀 없음.
    assert out["flags"] == [], out["flags"]


def test_segments_unknown_axis_review():
    """미인식 축 → unknown-axis REVIEW, 임의 그룹에 넣지 않는다."""
    unk = "us-gaap:SomeUnrecognizedAxis"
    assert unk not in KNOWN_AXES
    facts = [seg_fact(_REV, 100, 2024, {unk: "us-gaap:FooMember"})]
    out = seg.build_disaggregation(facts, [2024], _REVENUE_TAGS)
    assert any(t == "REVIEW" and d.startswith("unknown-axis") and unk in d
               for t, d in out["flags"]), out["flags"]
    # 모르는 축은 어떤 표준 그룹에도 욱여넣지 않는다.
    assert "segment" not in out and "geography" not in out and "product" not in out


def test_segments_custom_member_review_and_aggregated():
    """회사 고유 네임스페이스 멤버 → custom-tag REVIEW. 단, 축은 표준이라 그룹엔 보존."""
    seg_axis = "us-gaap:StatementBusinessSegmentsAxis"
    facts = [
        seg_fact(_REV, 1000, 2024, {}),
        seg_fact(_REV, 600, 2024, {seg_axis: "aapl:RetailMember"}),
        seg_fact(_REV, 400, 2024, {seg_axis: "aapl:WholesaleMember"}),
    ]
    out = seg.build_disaggregation(facts, [2024], _REVENUE_TAGS)
    assert KNOWN_AXES[seg_axis] == "segment"
    assert out["segment"]["aapl:RetailMember"][2024] == 600
    assert out["segment"]["aapl:WholesaleMember"][2024] == 400
    customs = [d for t, d in out["flags"]
               if t == "REVIEW" and d.startswith("custom-tag")]
    assert any("aapl:RetailMember" in d for d in customs), out["flags"]
    assert any("aapl:WholesaleMember" in d for d in customs), out["flags"]


def test_segments_reconcile_fields_within_tolerance():
    """reconcile 에 computed_sum/reported_total/diff 병기. 허용오차 내면 플래그 없음."""
    prod = "srt:ProductOrServiceAxis"
    facts = [
        seg_fact("us-gaap:Revenues", 1000, 2024, {}),
        seg_fact("us-gaap:Revenues", 600, 2024, {prod: "us-gaap:ProductMember"}),
        seg_fact("us-gaap:Revenues", 410, 2024, {prod: "us-gaap:ServiceMember"}),
    ]
    out = seg.build_disaggregation(facts, [2024], _REVENUE_TAGS)
    rec = [r for r in out["reconcile"]
           if r["group"] == "product" and r["year"] == 2024]
    assert len(rec) == 1, out["reconcile"]
    assert rec[0]["computed_sum"] == 1010
    assert rec[0]["reported_total"] == 1000
    assert rec[0]["diff"] == 10                      # 합 1010 vs 총계 1000
    # 1% < 2% 허용오차 → does-not-reconcile 뜨지 않음(거짓양성 방지).
    assert not any(d.startswith("does-not-reconcile") for _t, d in out["flags"])


def test_segments_reconcile_adjustment_member_suppresses_flag():
    """조정 멤버(Corporate/Eliminations 등)가 있으면 합≠총계라도 플래그 안 뜬다."""
    seg_axis = "us-gaap:StatementBusinessSegmentsAxis"
    facts = [
        seg_fact("us-gaap:Revenues", 1000, 2024, {}),
        seg_fact("us-gaap:Revenues", 700, 2024,
                 {seg_axis: "us-gaap:ProductMember"}),
        seg_fact("us-gaap:Revenues", 500, 2024,
                 {seg_axis: "us-gaap:CorporateNonSegmentMember"}),
    ]
    out = seg.build_disaggregation(facts, [2024], _REVENUE_TAGS)
    # 합 1200 vs 총계 1000 (20% 차이)지만 조정 멤버 존재 → does-not-reconcile 없음.
    assert not any(d.startswith("does-not-reconcile") for _t, d in out["flags"])
    rec = [r for r in out["reconcile"]
           if r["group"] == "segment" and r["year"] == 2024]
    assert rec and rec[0]["computed_sum"] == 1200 and rec[0]["diff"] == 200


def test_segments_reconcile_flag_when_unbalanced_no_adjustment():
    """조정 멤버 부재 + |diff|/total > 허용오차일 때만 does-not-reconcile."""
    geo = "srt:StatementGeographicalAxis"
    facts = [
        seg_fact("us-gaap:Revenues", 1000, 2024, {}),
        seg_fact("us-gaap:Revenues", 500, 2024, {geo: "country:US"}),
        seg_fact("us-gaap:Revenues", 300, 2024, {geo: "country:CN"}),
    ]
    out = seg.build_disaggregation(facts, [2024], _REVENUE_TAGS)
    # 합 800 vs 총계 1000 (20% 차이), 조정 멤버 없음 → REVIEW does-not-reconcile.
    assert any(t == "REVIEW" and d.startswith("does-not-reconcile")
               for t, d in out["flags"]), out["flags"]


# ---- excel-segments (phase 1-segments-kpi, step 3) -------------------
def _sheet_xml_by_name(z, name):
    """workbook.xml 의 시트 순서로 해당 이름의 sheetN.xml 을 찾아 디코드."""
    import re
    wb_xml = z.read("xl/workbook.xml").decode()
    order = re.findall(r'<sheet name="([^"]+)"', wb_xml)
    idx = order.index(name) + 1
    return z.read(f"xl/worksheets/sheet{idx}.xml").decode()


def test_workbook_with_segments():
    """분해 데이터(step 2 출력 형태) → Segments/Geography/Products 시트 추가 +
    Review 에 segment REVIEW 플래그·KPI 합류(별도 시트 아님) + Provenance 에
    분해 출처(축/멤버) 기록. 네트워크 없음."""
    cf = make_facts({
        "Revenues": _usd([dur(100, 2023, "a", "2024-02-01"),
                          dur(120, 2024, "b", "2025-02-01")]),
    })
    years = nz.available_years(cf, STATEMENTS)
    data = nz.normalize_company(cf, STATEMENTS, years)
    geo = "srt:StatementGeographicalAxis"
    seg_axis = "us-gaap:StatementBusinessSegmentsAxis"
    unknown = "us-gaap:SomeUnrecognizedAxis"
    facts = [
        seg_fact(_REV, 120, 2024, {}),                       # 무차원 총계
        seg_fact(_REV, 70, 2024, {geo: "country:US"}),       # geography
        seg_fact(_REV, 50, 2024, {geo: "us-gaap:NonUsMember"}),
        seg_fact(_REV, 80, 2024, {seg_axis: "aapl:RetailMember"}),    # custom-tag
        seg_fact(_REV, 40, 2024, {seg_axis: "aapl:WholesaleMember"}),
        seg_fact(_REV, 100, 2024, {unknown: "us-gaap:FooMember"}),    # unknown-axis
    ]
    disagg = seg.build_disaggregation(facts, years, _REVENUE_TAGS)
    # 회사 고유 KPI 후보(step 4 cli-integration 이 채울 형태) — 자동 표준화 금지.
    disagg["kpis"] = [{"concept": "aapl:ActiveInstalledBase", "member": "",
                       "year": 2024, "value": 2200000000, "unit": "devices"}]
    comp = nz.CompanyResult("TEST", "Test Co", "0000000001", "Test Co",
                            years, data, segments=disagg)
    out = os.path.join(os.path.dirname(__file__), "_smoke_seg.xlsx")
    write_workbook([comp], STATEMENTS, out)
    assert zipfile.is_zipfile(out)
    with zipfile.ZipFile(out) as z:
        names = z.namelist()
        assert "[Content_Types].xml" in names and "xl/workbook.xml" in names
        wb = z.read("xl/workbook.xml").decode()
        # 기존 6시트 + 분해 3시트가 모두 존재.
        for sheet in ["Income Statement", "Balance Sheet", "Cash Flow",
                      "Segments", "Geography", "Products",
                      "Comparison", "Review", "Provenance"]:
            assert sheet in wb, sheet
        # 분해 멤버가 해당 group 시트에 들어갔는지 (행=멤버).
        assert "country:US" in _sheet_xml_by_name(z, "Geography")
        assert "aapl:RetailMember" in _sheet_xml_by_name(z, "Segments")
        # Review 에 segment REVIEW 플래그·KPI 가 합류 (별도 시트가 아니라 Review).
        review = _sheet_xml_by_name(z, "Review")
        assert "REVIEW" in review
        assert "unknown-axis" in review
        assert "custom-tag" in review
        assert "KPI (review)" in review
        assert "aapl:ActiveInstalledBase" in review
        # 분해 값도 Provenance 에 출처(축/멤버)와 함께 기록.
        prov = _sheet_xml_by_name(z, "Provenance")
        assert "country:US" in prov          # 멤버
        assert geo in prov                   # 축 = 출처
    os.remove(out)


# ---- cli-integration (phase 1-segments-kpi, step 4) ------------------
# 합성 inline-XBRL(주.htm). 무차원 총계 + geography(표준 멤버) + segment(회사 고유
# 멤버) 차원 fact 가 섞여 있다. 모든 컨텍스트 기간 end=2024-09-28(연도 라벨=2024).
_CLI_INLINE_DOC = """<?xml version="1.0" encoding="UTF-8"?>
<xhtml xmlns:ix="http://www.xbrl.org/2013/inlineXBRL"
       xmlns:xbrli="http://www.xbrl.org/2003/instance"
       xmlns:xbrldi="http://xbrl.org/2006/xbrldi"
       xmlns:us-gaap="http://fasb.org/us-gaap/2024"
       xmlns:srt="http://fasb.org/srt/2024">
  <xbrli:context id="c-total">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-us">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">country:US</xbrldi:explicitMember>
      </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-nonus">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="srt:StatementGeographicalAxis">us-gaap:NonUsMember</xbrldi:explicitMember>
      </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-retail">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">aapl:RetailMember</xbrldi:explicitMember>
      </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <xbrli:context id="c-wholesale">
    <xbrli:entity><xbrli:identifier scheme="http://www.sec.gov/CIK">0000000001</xbrli:identifier>
      <xbrli:segment>
        <xbrldi:explicitMember dimension="us-gaap:StatementBusinessSegmentsAxis">aapl:WholesaleMember</xbrldi:explicitMember>
      </xbrli:segment></xbrli:entity>
    <xbrli:period><xbrli:startDate>2023-10-01</xbrli:startDate><xbrli:endDate>2024-09-28</xbrli:endDate></xbrli:period>
  </xbrli:context>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
                  contextRef="c-total" unitRef="usd" decimals="-6" scale="6"
                  format="ixt:num-dot-decimal">120</ix:nonFraction>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
                  contextRef="c-us" unitRef="usd" decimals="-6" scale="6"
                  format="ixt:num-dot-decimal">70</ix:nonFraction>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
                  contextRef="c-nonus" unitRef="usd" decimals="-6" scale="6"
                  format="ixt:num-dot-decimal">50</ix:nonFraction>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
                  contextRef="c-retail" unitRef="usd" decimals="-6" scale="6"
                  format="ixt:num-dot-decimal">80</ix:nonFraction>
  <ix:nonFraction name="us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"
                  contextRef="c-wholesale" unitRef="usd" decimals="-6" scale="6"
                  format="ixt:num-dot-decimal">40</ix:nonFraction>
</xhtml>"""


class _FakePipelineClient:
    """SecClient(get_json/get_text) 둘 다 흉내내는 스텁 (네트워크 없음)."""

    def __init__(self, json_map, text_map):
        self.json_map = json_map
        self.text_map = text_map
        self.requested = []

    def get_json(self, url, refresh=False):
        self.requested.append(url)
        return self.json_map[url]

    def get_text(self, url, refresh=False):
        self.requested.append(url)
        return self.text_map[url]


def _cli_pipeline_maps():
    """resolve→facts→submissions→index→instance 전 구간 합성 응답(URL→데이터)."""
    cik10 = "0000000001"
    accn = "0000000001-24-000001"
    accn_nodash = accn.replace("-", "")
    base = f"https://www.sec.gov/Archives/edgar/data/1/{accn_nodash}/"
    json_map = {
        "https://www.sec.gov/files/company_tickers.json": {
            "0": {"cik_str": 1, "ticker": "TEST", "title": "Test Co"}},
        f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json": {
            "entityName": "Test Co", "cik": 1, "facts": {"us-gaap": {
                "Revenues": _usd([dur(100, 2023, "x", "2024-02-01"),
                                  dur(120, 2024, "y", "2025-02-01")]),
            }}},
        f"https://data.sec.gov/submissions/CIK{cik10}.json": {
            "cik": "1", "filings": {"recent": {
                "accessionNumber": [accn],
                "form": ["10-K"],
                "filingDate": ["2024-11-01"],
                "reportDate": ["2024-09-28"],
                "primaryDocument": ["test-20240928.htm"],
                "isXBRL": [1],
                "isInlineXBRL": [1],
            }}},
        base + "index.json": {"directory": {"item": [
            {"name": "test-20240928.htm", "type": "10-K"},
            {"name": "test-20240928_htm.xml", "type": "XML"},
        ]}},
    }
    text_map = {base + "test-20240928.htm": _CLI_INLINE_DOC}
    return json_map, text_map


def test_cli_segments_pipeline_offline():
    """--segments: 가짜 client 로 cli 파이프라인 끝까지 → 분해 시트/값/플래그/출처.

    실제 SEC 호출 없음. 분해 값이 normalize 와 동일 기준(기간 end=2024)으로 열에
    정렬되는지, REVIEW(회사 고유 멤버)와 출처(축)가 기존 시트에 합류하는지 검증."""
    json_map, text_map = _cli_pipeline_maps()
    client = _FakePipelineClient(json_map, text_map)
    out = os.path.join(os.path.dirname(__file__), "_smoke_cli_seg.xlsx")
    rc = cli.main(["TEST", "--segments", "-o", out], client=client)
    assert rc == 0, rc
    assert zipfile.is_zipfile(out)
    with zipfile.ZipFile(out) as z:
        wb = z.read("xl/workbook.xml").decode()
        for sheet in ["Income Statement", "Balance Sheet", "Cash Flow",
                      "Segments", "Geography", "Products",
                      "Comparison", "Review", "Provenance"]:
            assert sheet in wb, sheet
        geo = _sheet_xml_by_name(z, "Geography")
        assert "country:US" in geo
        assert "70000000" in geo          # 70 * 10^6, 기간 end=2024 열에 정렬
        segs = _sheet_xml_by_name(z, "Segments")
        assert "aapl:RetailMember" in segs
        review = _sheet_xml_by_name(z, "Review")
        assert "REVIEW" in review and "custom-tag" in review
        prov = _sheet_xml_by_name(z, "Provenance")
        assert "country:US" in prov                       # 멤버
        assert "srt:StatementGeographicalAxis" in prov    # 축 = 출처
    os.remove(out)
    # 인스턴스는 SecClient.get_text 경유로만 취득(직접 urllib 금지).
    assert any(u.endswith("test-20240928.htm") for u in client.requested)


def test_cli_segments_off_is_regression_safe():
    """--segments 꺼짐: 분해 시트 없음 + submissions/인스턴스 네트워크 호출 없음."""
    json_map, text_map = _cli_pipeline_maps()
    client = _FakePipelineClient(json_map, text_map)
    out = os.path.join(os.path.dirname(__file__), "_smoke_cli_noseg.xlsx")
    rc = cli.main(["TEST", "-o", out], client=client)
    assert rc == 0, rc
    with zipfile.ZipFile(out) as z:
        wb = z.read("xl/workbook.xml").decode()
        for sheet in ["Income Statement", "Balance Sheet", "Cash Flow",
                      "Comparison", "Review", "Provenance"]:
            assert sheet in wb, sheet
        for sheet in ["Segments", "Geography", "Products"]:
            assert sheet not in wb, sheet
    os.remove(out)
    # 회귀: 꺼짐이면 submissions/인스턴스 네트워크를 전혀 건드리지 않는다.
    assert not any("submissions" in u for u in client.requested)
    assert not any(u.endswith(".htm") for u in client.requested)


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
