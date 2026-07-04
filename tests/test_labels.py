"""label linkbase 파서(labels) 테스트 — 네트워크 불필요.

`python3 tests/test_labels.py` 또는 `pytest tests/` 둘 다 동작.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sec_extract import labels as lb

# 합성 label linkbase — 실제 SEC `*_lab.xml` 축소판.
# - Revenue: standard 라벨 "Net sales" + documentation(무시돼야 함)
# - Cost: standard 라벨 "Cost of sales"
# - DataCenter 멤버: terseLabel 만 존재 "Data Center"(회사 고유 nvda:)
# - GrossProfit: 여러 역할(verbose + standard) → standard 우선
LAB_XML = """<?xml version="1.0" encoding="UTF-8"?>
<link:linkbase xmlns:link="http://www.xbrl.org/2003/linkbase"
               xmlns:xlink="http://www.w3.org/1999/xlink"
               xmlns:xml="http://www.w3.org/XML/1998/namespace">
 <link:labelLink xlink:type="extended"
                 xlink:role="http://www.xbrl.org/2003/role/link">
  <link:loc xlink:type="locator"
    xlink:href="aapl-20250329.xsd#us-gaap_RevenueFromContractWithCustomerExcludingAssessedTax"
    xlink:label="loc_rev"/>
  <link:labelArc xlink:type="arc" xlink:from="loc_rev" xlink:to="lab_rev"/>
  <link:label xlink:type="resource" xlink:label="lab_rev"
    xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en-US">Net sales</link:label>
  <link:label xlink:type="resource" xlink:label="lab_rev"
    xlink:role="http://www.xbrl.org/2003/role/documentation"
    xml:lang="en-US">Amount of revenue recognized from goods/services.</link:label>

  <link:loc xlink:type="locator"
    xlink:href="aapl-20250329.xsd#us-gaap_CostOfGoodsAndServicesSold"
    xlink:label="loc_cost"/>
  <link:labelArc xlink:from="loc_cost" xlink:to="lab_cost"/>
  <link:label xlink:label="lab_cost"
    xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en-US">Cost of sales</link:label>

  <link:loc xlink:href="nvda-20240128.xsd#nvda_DataCenterMember" xlink:label="loc_dc"/>
  <link:labelArc xlink:from="loc_dc" xlink:to="lab_dc"/>
  <link:label xlink:label="lab_dc"
    xlink:role="http://www.xbrl.org/2003/role/terseLabel" xml:lang="en-US">Data Center</link:label>

  <link:loc xlink:href="aapl-20250329.xsd#us-gaap_GrossProfit" xlink:label="loc_gp"/>
  <link:labelArc xlink:from="loc_gp" xlink:to="lab_gp_v"/>
  <link:labelArc xlink:from="loc_gp" xlink:to="lab_gp_s"/>
  <link:label xlink:label="lab_gp_v"
    xlink:role="http://www.xbrl.org/2003/role/verboseLabel"
    xml:lang="en-US">Gross Profit (verbose)</link:label>
  <link:label xlink:label="lab_gp_s"
    xlink:role="http://www.xbrl.org/2003/role/label" xml:lang="en-US">Gross margin</link:label>
 </link:labelLink>
</link:linkbase>
"""


def test_parse_standard_label():
    m = lb.parse_label_linkbase(LAB_XML)
    assert m["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"] == "Net sales"
    assert m["us-gaap:CostOfGoodsAndServicesSold"] == "Cost of sales"


def test_documentation_role_ignored():
    """documentation(정의문)은 표시 이름이 아니므로 라벨로 채택하지 않는다."""
    m = lb.parse_label_linkbase(LAB_XML)
    assert "recognized" not in m[
        "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"]


def test_terse_label_for_custom_member():
    m = lb.parse_label_linkbase(LAB_XML)
    assert m["nvda:DataCenterMember"] == "Data Center"


def test_standard_beats_verbose():
    """한 개념에 여러 역할이면 standard 라벨을 우선한다."""
    m = lb.parse_label_linkbase(LAB_XML)
    assert m["us-gaap:GrossProfit"] == "Gross margin"


def test_bad_xml_returns_empty():
    assert lb.parse_label_linkbase("<not xml <<<") == {}


def test_label_for_localname_fallback():
    """canonical_map 태그는 prefix 없는 local-name → us-gaap 보강으로 매칭."""
    m = lb.parse_label_linkbase(LAB_XML)
    assert lb.label_for(m, "RevenueFromContractWithCustomerExcludingAssessedTax") == \
        "Net sales"
    assert lb.label_for(m, "CostOfGoodsAndServicesSold") == "Cost of sales"


def test_label_for_qname_direct():
    m = lb.parse_label_linkbase(LAB_XML)
    assert lb.label_for(m, "nvda:DataCenterMember") == "Data Center"


def test_label_for_missing_returns_empty():
    m = lb.parse_label_linkbase(LAB_XML)
    assert lb.label_for(m, "us-gaap:DefinitelyNotAConcept") == ""
    assert lb.label_for(m, "") == ""
    assert lb.label_for({}, "us-gaap:Revenues") == ""


# ---- 네트워크 경계: 가짜 client 로 fetch 경로 검증 --------------------
class _FakeClient:
    """index.json + _lab.xml 텍스트를 메모리에서 돌려주는 테스트용 client."""

    def __init__(self, index_map, text_map):
        self._index = index_map
        self._text = text_map
        self.text_calls = []

    def get_json(self, url, refresh=False):
        return self._index.get(url, {})

    def get_text(self, url, refresh=False):
        self.text_calls.append(url)
        return self._text.get(url, "")


def _index(names):
    return {"directory": {"item": [{"name": n} for n in names]}}


def test_find_label_linkbase_url():
    cik = 320193
    accn = "000032019325000001"
    idx_url = (f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/index.json")
    base = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/"
    client = _FakeClient(
        {idx_url: _index(["aapl-20250329.htm", "aapl-20250329_lab.xml",
                          "aapl-20250329_pre.xml"])}, {})
    filing = {"accn_nodash": accn}
    assert lb.find_label_linkbase_url(client, cik, filing) == \
        base + "aapl-20250329_lab.xml"


def test_find_label_linkbase_url_missing():
    cik = 1
    accn = "a"
    idx_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accn}/index.json"
    client = _FakeClient({idx_url: _index(["only.htm", "only_pre.xml"])}, {})
    assert lb.find_label_linkbase_url(client, cik, {"accn_nodash": accn}) is None


def test_fetch_label_map_merges_latest_first():
    cik = 5
    a1, a2 = "acc1", "acc2"   # a1 = 최신(먼저), a2 = 구공시
    b1 = f"https://www.sec.gov/Archives/edgar/data/{cik}/{a1}/"
    b2 = f"https://www.sec.gov/Archives/edgar/data/{cik}/{a2}/"
    idx = {
        b1 + "index.json": _index(["x_lab.xml"]),
        b2 + "index.json": _index(["y_lab.xml"]),
    }
    # 최신 공시는 Revenue 라벨을 "Net sales", 구공시는 "Total revenues"(다름) + 구공시
    # 에만 있는 개념 하나. 병합 시 최신 라벨 우선 + 구개념도 채워짐.
    new_lab = LAB_XML
    old_lab = LAB_XML.replace("Net sales", "Total revenues").replace(
        "nvda_DataCenterMember", "nvda_LegacyMember")
    text = {b1 + "x_lab.xml": new_lab, b2 + "y_lab.xml": old_lab}
    client = _FakeClient(idx, text)
    filings = [{"accn_nodash": a1}, {"accn_nodash": a2}]
    m = lb.fetch_label_map(client, cik, filings)
    assert m["us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"] == \
        "Net sales"                       # 최신 우선
    assert m["nvda:LegacyMember"] == "Data Center"   # 구공시에만 있는 개념도 병합


def test_fetch_label_map_best_effort_on_failure():
    """일부 공시 실패해도 성공한 것만으로 결과를 낸다(부분 결과)."""
    cik = 9
    good = "good"
    bad = "bad"
    bg = f"https://www.sec.gov/Archives/edgar/data/{cik}/{good}/"
    idx = {bg + "index.json": _index(["g_lab.xml"])}
    # bad 공시는 index.json 도 없음(빈 dict) → _lab 없음 → 건너뜀
    client = _FakeClient(idx, {bg + "g_lab.xml": LAB_XML})
    filings = [{"accn_nodash": bad}, {"accn_nodash": good}]
    m = lb.fetch_label_map(client, cik, filings)
    assert m["us-gaap:CostOfGoodsAndServicesSold"] == "Cost of sales"


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
