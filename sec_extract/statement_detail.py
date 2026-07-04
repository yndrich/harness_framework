"""as-reported 전체 재무제표 추출 (표준화하지 않음).

segment_detail 이 '차원 있는' 매출 분해를 as-reported 로 보존하듯, 이 모듈은
'차원 없는'(본표 라인) 숫자 fact 를 3대 재무제표 전부에 대해 as-reported 로
펼친다. canonical_map 의 고정 표준 라인에 없는 항목도 놓치지 않는다:
- 회사 커스텀 확장 태그(예: COIN Transaction expense = coin:TransactionExpense)
  — companyfacts API 엔 없지만 inline-XBRL 엔 있다.
- 표준이지만 canonical_map 이 안 뽑던 태그(예: SellingAndMarketingExpense,
  OtherCostAndExpenseOperating).

한계(option A): presentation linkbase 를 파싱하지 않으므로 '소계 구조·라인 순서'는
재현하지 않는다. 각 개념의 '구분(IS/BS/CF)'은 canonical_map 소속을 우선(권위적)하고,
모르는 개념은 period-type + 이름 휴리스틱으로 '추정'한다(guessed=True 로 표기).

분기 값은 quarterly 의 날짜 기반 차분 로직을 재사용한다(10-Q 는 YTD 일 수 있음).
차원 있는 fact 는 여기서 제외한다(segment_detail 몫, 합산 중복 방지). dei/ecd
(표지·경영진보상) 네임스페이스는 재무제표가 아니므로 제외한다.
"""

from __future__ import annotations

from . import quarterly as qt
from .canonical_map import STATEMENTS
from .labels import label_for

# 재무제표가 아닌(표지/경영진보상) 네임스페이스 — 본표 추출에서 제외.
_SKIP_NAMESPACES = frozenset({"dei", "ecd"})

# 구분 한글 라벨.
STATEMENT_KO = {
    "income_statement": "손익계산서",
    "balance_sheet": "재무상태표",
    "cash_flow": "현금흐름표",
}

# 현금흐름표 개념 이름 휴리스틱(canonical 밖 duration 을 추정 분류할 때).
# 단·복수 모두 잡도록 어간(Payment/Proceeds)으로 둔다. 보충 비현금(Noncash)·
# 대출 원리금(Origination/Collection) 같은 현금흐름 부속 공시도 IS 에서 걷어낸다.
_CF_MARKERS = (
    "NetCash", "OperatingActivities", "InvestingActivities", "FinancingActivities",
    "Payment", "Proceeds", "Repayment", "IncreaseDecreaseIn", "Noncash",
    "CashAndCashEquivalents", "CashCashEquivalents", "OriginationLoans",
    "CollectionOfLoans", "DepreciationDepletion", "ShareBasedCompensation",
)


def _known_statement_map() -> dict:
    """canonical_map 태그(local-name) → 표준 구분(권위적 분류의 근거)."""
    out: dict[str, str] = {}
    for stmt in STATEMENTS:
        for line in stmt["lines"]:
            for tag in line.get("tags", []):
                out.setdefault(tag, stmt["key"])
    return out


_KNOWN = _known_statement_map()


def _local(qname: str) -> str:
    return qname.split(":", 1)[1] if ":" in qname else qname


def _namespace(qname: str) -> str:
    return qname.split(":", 1)[0] if ":" in qname else ""


def classify(concept: str, period_type: str) -> tuple:
    """(concept QName, period_type) → (구분 key, guessed).

    canonical_map 에 있으면 그 구분을 권위적으로(guessed=False) 쓰고, 없으면
    instant→재무상태표, 현금흐름형 이름→현금흐름표, 나머지 duration→손익 으로 추정.
    """
    local = _local(concept)
    if local in _KNOWN:
        return _KNOWN[local], False
    if period_type == "instant":
        return "balance_sheet", True
    if any(m in local for m in _CF_MARKERS):
        return "cash_flow", True
    return "income_statement", True


def _norm_fact(f: dict) -> dict:
    """인스턴스 fact → 분기 차분이 쓰는 모양({val,start,end,unit,filed,...})."""
    return {
        "val": f.get("value"),
        "start": f.get("start"),
        "end": f.get("end") or f.get("instant"),
        "unit": f.get("unit"),
        "filed": f.get("filed"),
        "accn": f.get("accn"),
        "form": f.get("form"),
        "concept": f.get("concept"),
    }


def _series_index(facts: list) -> dict:
    """차원 없는 숫자 fact 를 concept 별 시계열로 모은다(dei/ecd·차원 제외)."""
    series: dict = {}
    for f in facts:
        if f.get("dims"):                 # 차원 있는 건 segment_detail 몫
            continue
        if f.get("value") is None:
            continue
        concept = f.get("concept") or ""
        if not concept or _namespace(concept) in _SKIP_NAMESPACES:
            continue
        series.setdefault(concept, []).append(_norm_fact(f))
    return series


def _period_type(nfacts: list) -> str:
    """시계열이 duration(기간) 인지 instant(시점) 인지 — start 유무로 판별."""
    return "duration" if any(nf.get("start") for nf in nfacts) else "instant"


def _value_for(series, period_type, calendar, year, quarter):
    """quarter ∈ {1,2,3,4} 또는 'FY'. 구분(기간/시점)에 맞는 셀. 없으면 None."""
    if period_type == "instant":
        return qt.instant_from_facts(series, calendar, year, quarter)
    if quarter == "FY":
        return qt.annual_from_facts(series, calendar, year)
    return qt.discrete_from_facts(series, calendar, year, quarter)


def build_as_reported_statements(facts, calendar, periods, annual_years=None,
                                 label_map=None):
    """차원 없는 본표 fact 를 3대 재무제표 as-reported tidy 행으로 펼친다.

    facts: 인스턴스 fact 리스트(각 concept/value/dims/start/end/unit/accn/filed/form).
    calendar: qt.fiscal_calendar 결과.
    periods: [(fy, q)] 분기 목록.
    annual_years: 연간(FY) 행을 만들 회계연도들(기본 = periods 의 fy 집합).
    label_map: (선택) concept→공시 표시라벨 맵('원본' 항목명).

    반환 {rows}. 각 행: dict(statement, statement_ko, guessed, concept, orig,
    year, quarter, val, unit, method, accn, filed, form).
    """
    lmap = label_map or {}
    if annual_years is None:
        annual_years = sorted({fy for fy, _ in periods})
    cells = [(fy, q) for (fy, q) in periods] + [(fy, "FY") for fy in annual_years]

    rows = []
    for concept, series in _series_index(facts).items():
        ptype = _period_type(series)
        stmt, guessed = classify(concept, ptype)
        orig = label_for(lmap, concept)
        for (fy, q) in cells:
            cell = _value_for(series, ptype, calendar, fy, q)
            if cell is None or cell.get("val") is None:
                continue
            src = cell.get("fact") or {}
            rows.append({
                "statement": stmt,
                "statement_ko": STATEMENT_KO.get(stmt, "기타"),
                "guessed": guessed,
                "concept": concept,
                "orig": orig,
                "year": fy, "quarter": q,
                "val": cell["val"], "unit": src.get("unit"),
                "method": cell.get("method"),
                "accn": src.get("accn") or "", "filed": src.get("filed") or "",
                "form": src.get("form") or "",
            })
    return {"rows": rows}
