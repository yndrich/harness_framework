"""as-reported 충실 매출 분해(segment_detail) 테스트 — 네트워크 불필요.

`python3 tests/test_segment_detail.py` 또는 `pytest tests/` 둘 다 동작.
"""

import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from sec_extract import segment_detail as sd

# NVDA 회계 2024 분기 경계
FY_START = date(2023, 1, 30)
Q = {1: date(2023, 4, 30), 2: date(2023, 7, 30),
     3: date(2023, 10, 29), 4: date(2024, 1, 28)}
CAL = {(2024, q): {"start": FY_START, "end": Q[q]} for q in (1, 2, 3, 4)}
GEO = "srt:StatementGeographicalAxis"
PROD = "srt:ProductOrServiceAxis"
REV = "us-gaap:RevenueFromContractWithCustomerExcludingAssessedTax"


def fact(val, member, start, end, axis=GEO, accn="a1", filed="2023-06-01",
         concept=REV, form="10-Q"):
    dims = {axis: member} if member else {}
    return {"concept": concept, "value": val, "dims": dims,
            "start": start.isoformat() if start else None,
            "end": end.isoformat(), "accn": accn, "filed": filed, "form": form}


def _facts():
    f = []
    # 지역: US, TW — 분기 직접 + 6M YTD(차분 검증)
    f += [fact(100, "country:US", FY_START, Q[1]),
          fact(210, "country:US", FY_START, Q[2]),
          fact(40, "country:TW", FY_START, Q[1]),
          fact(90, "country:TW", FY_START, Q[2])]
    # US 연간(FY 행 검증)
    f += [fact(450, "country:US", FY_START, date(2024, 1, 28), form="10-K")]
    # SG: Q2 에만 등장(신규 이벤트)
    f += [fact(30, "country:SG", date(2023, 5, 1), Q[2])]
    # JP: Q1 을 다른 공시가 55 로 재보고(재작성 이벤트, 차분과 분리)
    f += [fact(50, "country:JP", FY_START, Q[1], accn="a1", filed="2023-06-01"),
          fact(55, "country:JP", FY_START, Q[1], accn="a2", filed="2023-09-01")]
    # 무차원 총계(reconcile 기준): Q1=140, 6M=300
    f += [fact(140, None, FY_START, Q[1]), fact(300, None, FY_START, Q[2])]
    # 제품 축: 두 분류가 겹쳐 멤버합 > 총계(overlap)
    f += [fact(120, "nvda:DataCenterMember", FY_START, Q[1], axis=PROD),
          fact(20, "nvda:GamingMember", FY_START, Q[1], axis=PROD),
          fact(100, "nvda:ComputeMember", FY_START, Q[1], axis=PROD),
          fact(40, "nvda:NetworkingMember", FY_START, Q[1], axis=PROD)]
    return f


def _build():
    return sd.build_as_reported(_facts(), [sd._local(REV)], CAL,
                                periods=[(2024, 1), (2024, 2)], annual_years=[2024])


def test_members_preserved_verbatim():
    """축·멤버 QName 을 표준화 없이 그대로 보존한다."""
    out = _build()
    members = {(r["axis"], r["member"]) for r in out["rows"]}
    assert (GEO, "country:US") in members
    assert (GEO, "nvda:OtherCountriesMember") not in members  # 없는 건 안 만든다
    assert (PROD, "nvda:DataCenterMember") in members          # 회사 고유도 보존


def test_quarterly_ytd_differenced_per_member():
    """멤버별 분기값: 직접 분기 + 6M−Q1 차분."""
    out = _build()

    def v(member, q):
        return next((r["val"] for r in out["rows"]
                     if r["member"] == member and r["quarter"] == q), None)
    assert v("country:US", 1) == 100      # 직접 3개월
    assert v("country:US", 2) == 110      # 210 − 100 (6M YTD 차분)
    assert v("country:TW", 2) == 50       # 90 − 40


def test_annual_fy_row():
    out = _build()
    fy = next((r["val"] for r in out["rows"]
               if r["member"] == "country:US" and r["quarter"] == "FY"), None)
    assert fy == 450, fy


def test_overlap_flagged_not_merged():
    """한 축에 분류가 겹치면 reconcile 에 overlap=True (조용히 합치지 않음)."""
    out = _build()
    prod_q1 = next(r for r in out["reconcile"]
                   if r["axis"] == PROD and r["quarter"] == 1)
    assert prod_q1["overlap"] is True, prod_q1
    # 지역축 Q1 은 합(105+40=145)≈총계(140) 범위 밖일 수 있으나 overlap 은 아님
    geo_q1 = next(r for r in out["reconcile"]
                  if r["axis"] == GEO and r["quarter"] == 1)
    assert geo_q1["overlap"] is False


def test_change_log_new_member_and_restatement():
    out = _build()
    evs = out["changes"]
    assert any(e["member"] == "country:SG" and e["event"] == "신규" for e in evs), evs
    assert any(e["member"] == "country:JP" and e["event"] == "재작성" for e in evs), evs


def test_alias_layer_optional_and_preserves_raw():
    """별칭은 별도 열로만 붙고, 원본 멤버 QName 은 그대로 보존된다."""
    from sec_extract.canonical_map import member_label
    out = _build()
    dc = next(r for r in out["rows"] if r["member"] == "nvda:DataCenterMember")
    assert dc["member"] == "nvda:DataCenterMember"   # 원본 보존(손실 없음)
    assert dc["label"] == "데이터센터"                  # 별칭 부착
    assert dc["axis_label"] == "제품/서비스"
    # unaliased 불변식: 별칭 있는 멤버는 빠지고, 들어간 건 모두 별칭이 없다.
    assert ("srt:ProductOrServiceAxis", "nvda:DataCenterMember") not in out["unaliased"]
    assert all(member_label(m) is None for _ax, m in out["unaliased"])
    assert member_label("nvda:DefinitelyNotAMember") is None


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


def test_segment_detail_uses_raw_data_tidy_schema():
    """Segment Detail 이 Raw Data 와 동일한 tidy 양식(년도|분기|Index|항목|값|Key)."""
    import zipfile
    from xml.etree import ElementTree as ET
    from sec_extract.raw_model import write_raw_model_workbook
    out = _build()
    path = os.path.join(os.path.dirname(__file__), "_smoke_seg.xlsx")
    write_raw_model_workbook([("NVDA", [], [(2024, 1), (2024, 2)], out)], path)
    z = zipfile.ZipFile(path)
    names = [s.get("name") for s in ET.fromstring(z.read("xl/workbook.xml")).iter()
             if s.tag.endswith("}sheet")]
    idx = {nm: i + 1 for i, nm in enumerate(names)}
    for nm in ("Segment Detail", "Segment Reconcile", "Segment Changes"):
        assert nm in idx, f"{nm} 시트 없음"
    rows = _read_sheet(z, idx["Segment Detail"])
    assert rows[1] == ["년도", "분기", "Index", "항목", "값", "Canonical Key",
                       "기간"], rows[1]
    # 데이터센터 2024 Q1: 항목=별칭, Key=멤버 QName, Index=년도×4+분기, 기간 라벨
    dc = next(r for r in rows[2:] if len(r) >= 6
              and r[5] == "nvda:DataCenterMember" and r[1] == "1")
    assert dc[0] == "2024" and dc[2] == str(2024 * 4 + 1)   # Index
    assert dc[3] == "데이터센터"                              # 항목=별칭
    assert dc[6] == "24' Q1"                                # 기간 라벨
    # Segment Pivot / Raw Pivot 시트도 생성된다
    assert "Segment Pivot" in idx and "Raw Pivot" in idx
    os.remove(path)


def test_coin_member_aliases_filled():
    """COIN 매출 분해 멤버 19개의 한글 별칭이 모두 정의됨(별칭미정의 0).
    표준 us-gaap 멤버(NonUs/RelatedParty/SubscriptionAndCirculation 등)도 함께
    라벨링되어 다른 기업에도 재사용된다. 특수관계자 축 라벨도 정의."""
    from sec_extract.canonical_map import member_label, axis_label
    coin_members = [
        "coin:BankServicingAndSubscriptionAndCirculationMember",
        "us-gaap:BankServicingMember",
        "coin:BankServicingConsumerNetMember",
        "coin:BankServicingInstitutionalMember",
        "coin:BankServicingRetailNetMember",
        "coin:BankServicingOtherMember",
        "us-gaap:SubscriptionAndCirculationMember",
        "coin:SubscriptionAndCirculationStablecoinMember",
        "coin:SubscriptionAndCirculationBlockchainInfrastructureServiceMember",
        "coin:SubscriptionAndCirculationCustodialFeeMember",
        "coin:SubscriptionAndCirculationEarnCampaignMember",
        "coin:SubscriptionAndCirculationOtherMember",
        "coin:LearningRewardsMember",
        "coin:OtherCryptoSalesMember",
        "coin:ProductAndServiceOtherCryptoAssetSalesMember",
        "coin:OtherRevenueMember",
        "coin:RestOfTheWorldMember",
        "us-gaap:NonUsMember",
        "us-gaap:RelatedPartyMember",
    ]
    missing = [m for m in coin_members if member_label(m) is None]
    assert not missing, f"별칭 미정의: {missing}"
    assert member_label(
        "coin:SubscriptionAndCirculationStablecoinMember") == "구독·서비스-스테이블코인"
    assert member_label("us-gaap:NonUsMember") == "미국 외"
    assert axis_label(
        "us-gaap:RelatedPartyTransactionsByRelatedPartyAxis") == "특수관계자"


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
