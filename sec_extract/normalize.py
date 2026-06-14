"""정규화: 표준 항목 x 연도 단위로 값을 해석하고 검토 플래그를 생성한다.

핵심 동작
- 연도별로 후보 태그를 우선순위대로 시도, 첫 값 채택 (태그 변경 자동 흡수).
- 같은 (태그, 연도)가 여러 공시에 나오면 최신 제출본 채택 = restatement 처리.
- 사람이 확인해야 하는 상황을 플래그로 표면화:
    AMBIGUOUS  : 후보 태그가 둘 이상 값이 있고 서로 불일치
    RESTATED   : 같은 기간을 다른 공시가 다른 값으로 보고 (재작성)
    GAP        : 다른 연도엔 값이 있는데 중간 연도가 비어 있음 (태그 누락 의심)
"""

from __future__ import annotations

from datetime import date

ANNUAL_MIN_DAYS = 340
ANNUAL_MAX_DAYS = 380
REL_TOL = 0.005   # 0.5% 이내 차이는 동일값으로 간주 (반올림 노이즈)
ANNUAL_FORMS = ("10-K", "10-K/A")


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _days(start: str, end: str) -> int:
    return (_d(end) - _d(start)).days


def _is_annual_duration(f: dict) -> bool:
    if not f.get("start") or not f.get("end"):
        return False
    return ANNUAL_MIN_DAYS <= _days(f["start"], f["end"]) <= ANNUAL_MAX_DAYS


def _year_of(f: dict) -> int:
    return _d(f["end"]).year


def _rel_diff(a: float, b: float) -> float:
    denom = max(abs(a), abs(b), 1.0)
    return abs(a - b) / denom


def _annual_facts_for_year(facts_obj, tag, year, period_type, unit):
    """해당 태그/연도/기간유형에 맞는 fact 리스트(같은 연도 내 재작성 포함)."""
    out = []
    for f in facts_obj.facts_for(tag, unit=unit):
        if not f.get("end") or _year_of(f) != year:
            continue
        if period_type == "duration":
            if not _is_annual_duration(f):
                continue
        else:  # instant: 시점 잔액 -> 회계연도 말, 10-K 기준
            if f.get("start"):
                continue
            if f.get("form") not in ANNUAL_FORMS:
                continue
        out.append(f)
    return out


def _dedup_latest(year_facts):
    """최신 제출본 채택. 값이 갈리면 재작성 내역 반환."""
    srt = sorted(year_facts, key=lambda f: f.get("filed") or "", reverse=True)
    chosen = srt[0]
    restated = []
    for f in srt[1:]:
        if (f.get("val") is not None and chosen.get("val") is not None
                and _rel_diff(chosen["val"], f["val"]) > REL_TOL):
            restated.append({
                "val": f["val"], "filed": f["filed"],
                "accn": f["accn"], "form": f["form"],
            })
    return chosen, restated


def resolve_cell(facts_obj, candidate_tags, year, period_type, unit=None):
    """(표준항목, 연도) 한 칸을 해석. 값이 전혀 없으면 None."""
    hits = []
    for idx, tag in enumerate(candidate_tags):
        yf = _annual_facts_for_year(facts_obj, tag, year, period_type, unit)
        if yf:
            chosen, restated = _dedup_latest(yf)
            hits.append({"priority": idx, "tag": tag, "fact": chosen,
                         "restated": restated})
    if not hits:
        return None
    primary = hits[0]
    flags = []
    for other in hits[1:]:
        pv, ov = primary["fact"].get("val"), other["fact"].get("val")
        if pv is not None and ov is not None and _rel_diff(pv, ov) > REL_TOL:
            flags.append(("AMBIGUOUS",
                          f"{other['tag']}={ov:,.0f} vs {primary['tag']}={pv:,.0f}"))
    if primary["restated"]:
        detail = "; ".join(
            f"{r['val']:,.0f} (filed {r['filed']}, {r['form']})"
            for r in primary["restated"]
        )
        flags.append(("RESTATED", f"prior: {detail}"))
    return {
        "val": primary["fact"].get("val"),
        "tag": primary["tag"],
        "unit": primary["fact"].get("unit"),
        "fact": primary["fact"],
        "flags": flags,
        "alt_hits": hits[1:],
    }


def available_years(facts_obj, statements) -> list:
    """설정에 있는 태그들로부터 사용 가능한 회계연도 집합을 수집."""
    years = set()
    for st in statements:
        ptype = st["period_type"]
        for line in st["lines"]:
            unit = line.get("unit")
            for tag in line["tags"]:
                for f in facts_obj.facts_for(tag, unit=unit):
                    if not f.get("end"):
                        continue
                    if ptype == "duration":
                        if _is_annual_duration(f):
                            years.add(_year_of(f))
                    else:
                        if not f.get("start") and f.get("form") in ANNUAL_FORMS:
                            years.add(_year_of(f))
    return sorted(years)


def _mark_gaps(line_cells: dict, years: list) -> None:
    """값이 있는 최소/최대 연도 사이의 빈 칸을 GAP 으로 표시."""
    present = [y for y in years
               if line_cells.get(y) and line_cells[y].get("val") is not None]
    if len(present) < 2:
        return
    lo, hi = min(present), max(present)
    for y in years:
        if lo <= y <= hi and (line_cells.get(y) is None
                              or line_cells[y].get("val") is None):
            line_cells[y] = {
                "val": None, "tag": None, "unit": None, "fact": None,
                "flags": [("GAP", "interior year missing — 태그 변경/누락 의심")],
                "alt_hits": [],
            }


def normalize_company(facts_obj, statements, years: list) -> dict:
    """{statement_key: {line_key: {year: cell|None}}} 형태로 정규화."""
    result = {}
    for st in statements:
        skey = st["key"]
        lines = {}
        for line in st["lines"]:
            cells = {}
            for y in years:
                cells[y] = resolve_cell(
                    facts_obj, line["tags"], y, st["period_type"],
                    unit=line.get("unit"),
                )
            _mark_gaps(cells, years)
            lines[line["key"]] = cells
        result[skey] = lines
    return result


class CompanyResult:
    """한 기업의 정규화 결과 + 식별 정보."""

    def __init__(self, ticker, title, cik10, entity, years, data,
                 segments=None):
        self.ticker = ticker
        self.title = title
        self.cik10 = cik10
        self.entity = entity
        self.years = years
        self.data = data   # {statement_key: {line_key: {year: cell}}}
        # segments.build_disaggregation 출력(분해 group + flags + reconcile,
        # 선택적으로 kpis). 비어 있으면 {} — excel 은 분해 시트를 생략한다.
        self.segments = segments or {}

    def cell(self, statement_key, line_key, year):
        return self.data.get(statement_key, {}).get(line_key, {}).get(year)


def collect_flags(company: CompanyResult, statements) -> list:
    """검토 시트용 플래그 행 목록."""
    label = {st["key"]: st["label"] for st in statements}
    line_label = {
        (st["key"], ln["key"]): ln["label"]
        for st in statements for ln in st["lines"]
    }
    rows = []
    for skey, lines in company.data.items():
        for lkey, cells in lines.items():
            for year, cell in cells.items():
                if not cell or not cell.get("flags"):
                    continue
                fact = cell.get("fact") or {}
                for ftype, detail in cell["flags"]:
                    rows.append({
                        "ticker": company.ticker,
                        "statement": label.get(skey, skey),
                        "line": line_label.get((skey, lkey), lkey),
                        "year": year,
                        "flag": ftype,
                        "detail": detail,
                        "tag": cell.get("tag") or "",
                        "accn": fact.get("accn") or "",
                        "form": fact.get("form") or "",
                        "filed": fact.get("filed") or "",
                    })
    return rows


def collect_provenance(company: CompanyResult, statements) -> list:
    """모든 값 채워진 칸의 출처(태그/공시) 추적 행."""
    label = {st["key"]: st["label"] for st in statements}
    line_label = {
        (st["key"], ln["key"]): ln["label"]
        for st in statements for ln in st["lines"]
    }
    rows = []
    for skey, lines in company.data.items():
        for lkey, cells in lines.items():
            for year, cell in cells.items():
                if not cell or cell.get("val") is None:
                    continue
                fact = cell.get("fact") or {}
                rows.append({
                    "ticker": company.ticker,
                    "statement": label.get(skey, skey),
                    "line": line_label.get((skey, lkey), lkey),
                    "year": year,
                    "value": cell.get("val"),
                    "tag": cell.get("tag") or "",
                    "unit": cell.get("unit") or "",
                    "accn": fact.get("accn") or "",
                    "form": fact.get("form") or "",
                    "filed": fact.get("filed") or "",
                    "period_end": fact.get("end") or "",
                })
    return rows
