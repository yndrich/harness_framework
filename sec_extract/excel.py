"""엑셀 워크북 생성.

구성: 제표별 시트(다기업이면 기업 블록을 가로로 나란히) + Comparison(핵심지표/마진)
+ Review(검토 필요 플래그) + Provenance(모든 값의 출처 추적).
검토 플래그는 셀 배경색으로 하이라이트한다.
"""

from __future__ import annotations

from .xlsx import Workbook
from .canonical_map import line_fmt, KNOWN_AXES
from . import normalize as nz

# 플래그별 배경색 (ARGB 의 RGB 부분)
FLAG_FILL = {
    "AMBIGUOUS": "FFF2CC",   # 연노랑
    "RESTATED": "FCE4D6",    # 연주황
    "GAP": "F8CBAD",         # 연빨강
}
FLAG_PRIORITY = ["RESTATED", "AMBIGUOUS", "GAP"]
HEADER_FILL = "D9E1F2"
TICKER_FILL = "BDD7EE"
MONEY = "#,##0"
PCT = "0.0%"

# 분해(차원) 시트: group key -> 시트 라벨. group key 는 canonical_map.KNOWN_AXES
# 의 값(축→group)에서 파생한다(축 문자열·매핑은 canonical_map 단일 출처; 여기엔
# 표현용 라벨만 둔다). 새 축이 추가되면 자동으로 시트가 늘어난다.
_GROUP_LABELS = {"segment": "Segments", "geography": "Geography",
                 "product": "Products"}
DISAGG_GROUPS = [(g, _GROUP_LABELS.get(g, g.title()))
                 for g in dict.fromkeys(KNOWN_AXES.values())]
# group -> 대표 축(provenance 출처 표기용 역매핑).
GROUP_AXIS = {grp: axis for axis, grp in KNOWN_AXES.items()}
# 분해/KPI 검토(REVIEW) 행 하이라이트. 새 색을 만들지 않고 '검토 필요' 의미의
# 연노랑을 재사용한다(UI_GUIDE: 의미색 3개만). 자동 표준화가 불확실함을 표시.
REVIEW_FILL = FLAG_FILL["AMBIGUOUS"]


def _flag_fill(cell):
    if not cell or not cell.get("flags"):
        return None
    types = {f[0] for f in cell["flags"]}
    for t in FLAG_PRIORITY:
        if t in types:
            return FLAG_FILL[t]
    return None


def _get_val(company, skey, lkey, year):
    c = company.cell(skey, lkey, year)
    return c.get("val") if c else None


def write_workbook(companies, statements, path):
    wb = Workbook()
    for st in statements:
        _write_statement_sheet(wb.add_sheet(st["label"]), st, companies)
    # 분해(부문/지역/제품)는 데이터가 있을 때만 추가 — 없으면 기존 6시트 고정 유지.
    if any(_has_disagg(c) for c in companies):
        for group_key, label in DISAGG_GROUPS:
            _write_disagg_sheet(wb.add_sheet(label), group_key, label,
                                companies)
    _write_comparison_sheet(wb.add_sheet("Comparison"), statements, companies)
    _write_review_sheet(wb.add_sheet("Review"), statements, companies)
    _write_provenance_sheet(wb.add_sheet("Provenance"), statements, companies)
    wb.save(path)


def _write_statement_sheet(ws, st, companies):
    ws.write(1, 1, st["label"], bold=True)
    ws.set_col_width(1, 30)
    # 헤더: row2 = 기업명(병합), row3 = 연도
    col = 2
    for comp in companies:
        start = col
        for y in comp.years:
            ws.write(3, col, y, bold=True, fill=HEADER_FILL, align="center")
            ws.set_col_width(col, 15)
            col += 1
        if col > start:
            ws.write(2, start, comp.ticker, bold=True, fill=TICKER_FILL,
                     align="center")
            if col - 1 > start:
                ws.merge(2, start, 2, col - 1)
    # 본문
    r = 4
    for line in st["lines"]:
        ws.write(r, 1, line["label"])
        fmt = line_fmt(line)
        col = 2
        for comp in companies:
            for y in comp.years:
                cell = comp.cell(st["key"], line["key"], y)
                fill = _flag_fill(cell)
                val = cell.get("val") if cell else None
                if val is not None:
                    ws.write(r, col, val, num_format=fmt, fill=fill)
                elif fill:
                    ws.write(r, col, None, fill=fill)
                col += 1
        r += 1
    ws.freeze(4, 2)


# 분해(부문/지역/제품) 시트 ----------------------------------------------
def _has_disagg(comp) -> bool:
    seg = getattr(comp, "segments", None) or {}
    if seg.get("flags") or seg.get("reconcile") or seg.get("kpis"):
        return True
    return any(seg.get(g) for g, _ in DISAGG_GROUPS)


def _disagg_member_union(companies, group_key) -> list:
    """여러 기업의 해당 group 멤버 합집합(행 라벨). 결정적 순서."""
    members, seen = [], set()
    for comp in companies:
        gdict = (getattr(comp, "segments", None) or {}).get(group_key) or {}
        for m in gdict:
            if m not in seen:
                seen.add(m)
                members.append(m)
    return sorted(members)


def _write_disagg_sheet(ws, group_key, label, companies):
    """행=멤버, 열=연도. 다기업이면 기업 블록을 가로로(제표 시트와 동일 레이아웃)."""
    ws.write(1, 1, f"{label} — 매출 분해 (행=멤버, 열=연도)", bold=True)
    ws.set_col_width(1, 38)
    # 헤더: row2 = 기업명(병합), row3 = 연도.
    col = 2
    for comp in companies:
        start = col
        for y in comp.years:
            ws.write(3, col, y, bold=True, fill=HEADER_FILL, align="center")
            ws.set_col_width(col, 15)
            col += 1
        if col > start:
            ws.write(2, start, comp.ticker, bold=True, fill=TICKER_FILL,
                     align="center")
            if col - 1 > start:
                ws.merge(2, start, 2, col - 1)
    members = _disagg_member_union(companies, group_key)
    r = 4
    if not members:
        ws.write(r, 1, "분해 데이터 없음 — 이 공시에서 해당 축 fact 미검출.")
        r += 1
    for member in members:
        ws.write(r, 1, member)
        col = 2
        for comp in companies:
            gdict = (getattr(comp, "segments", None) or {}).get(group_key) or {}
            by_year = gdict.get(member) or {}
            for y in comp.years:
                v = by_year.get(y)
                if v is not None:
                    ws.write(r, col, v, num_format=MONEY)
                col += 1
        r += 1
    ws.freeze(4, 2)
    _write_disagg_reconcile(ws, r + 1, group_key, companies)


def _write_disagg_reconcile(ws, r, group_key, companies):
    """정보성: (group, year)별 멤버 합 vs 무차원 보고총계 — 시트 하단에 병기."""
    rows = []
    for comp in companies:
        seg = getattr(comp, "segments", None) or {}
        for rec in seg.get("reconcile", []):
            if rec.get("group") == group_key:
                rows.append((comp.ticker, rec))
    if not rows:
        return
    ws.write(r, 1, "Reconciliation — Σ members vs reported total (정보성)",
             bold=True)
    r += 1
    for i, h in enumerate(["Ticker", "Year", "Σ members", "Reported total",
                           "Diff"], start=1):
        ws.write(r, i, h, bold=True, fill=HEADER_FILL)
    r += 1
    for ticker, rec in rows:
        ws.write(r, 1, ticker)
        ws.write(r, 2, rec.get("year"))
        ws.write(r, 3, rec.get("computed_sum"), num_format=MONEY)
        ws.write(r, 4, rec.get("reported_total"), num_format=MONEY)
        ws.write(r, 5, rec.get("diff"), num_format=MONEY)
        r += 1


# Comparison: 핵심 지표 + 파생 마진/FCF -----------------------------------
_CORE_METRICS = [
    ("Revenue", "income_statement", "revenue", MONEY),
    ("Gross Profit", "income_statement", "gross_profit", MONEY),
    ("Operating Income", "income_statement", "operating_income", MONEY),
    ("Net Income", "income_statement", "net_income", MONEY),
    ("Total Assets", "balance_sheet", "total_assets", MONEY),
    ("Total Liabilities", "balance_sheet", "total_liabilities", MONEY),
    ("Total Equity", "balance_sheet", "total_equity", MONEY),
    ("Operating Cash Flow", "cash_flow", "cfo", MONEY),
    ("CapEx", "cash_flow", "capex", MONEY),
]


def _write_comparison_sheet(ws, statements, companies):
    ws.write(1, 1, "Comparison — Key Metrics & Margins", bold=True)
    ws.set_col_width(1, 26)
    col = 2
    for comp in companies:
        start = col
        for y in comp.years:
            ws.write(3, col, y, bold=True, fill=HEADER_FILL, align="center")
            ws.set_col_width(col, 15)
            col += 1
        if col > start:
            ws.write(2, start, comp.ticker, bold=True, fill=TICKER_FILL,
                     align="center")
            if col - 1 > start:
                ws.merge(2, start, 2, col - 1)
    r = 4
    for label, skey, lkey, fmt in _CORE_METRICS:
        ws.write(r, 1, label)
        col = 2
        for comp in companies:
            for y in comp.years:
                v = _get_val(comp, skey, lkey, y)
                if v is not None:
                    ws.write(r, col, v, num_format=fmt)
                col += 1
        r += 1
    # 파생: FCF, 마진
    r += 1
    ws.write(r, 1, "Free Cash Flow (CFO − CapEx)", bold=True)
    col = 2
    for comp in companies:
        for y in comp.years:
            cfo = _get_val(comp, "cash_flow", "cfo", y)
            capex = _get_val(comp, "cash_flow", "capex", y)
            if cfo is not None and capex is not None:
                ws.write(r, col, cfo - capex, num_format=MONEY)
            col += 1
    r += 1
    for label, num, den in [
        ("Gross Margin", "gross_profit", "revenue"),
        ("Operating Margin", "operating_income", "revenue"),
        ("Net Margin", "net_income", "revenue"),
    ]:
        ws.write(r, 1, label)
        col = 2
        for comp in companies:
            for y in comp.years:
                n = _get_val(comp, "income_statement", num, y)
                d = _get_val(comp, "income_statement", den, y)
                if n is not None and d not in (None, 0):
                    ws.write(r, col, n / d, num_format=PCT)
                col += 1
        r += 1
    ws.freeze(4, 2)


def _write_review_sheet(ws, statements, companies):
    ws.write(1, 1, "Review — 사람 검토 필요 항목", bold=True)
    # 범례
    ws.write(2, 1, "AMBIGUOUS: 후보 태그 충돌", fill=FLAG_FILL["AMBIGUOUS"])
    ws.write(2, 2, "RESTATED: 재작성됨", fill=FLAG_FILL["RESTATED"])
    ws.write(2, 3, "GAP: 중간연도 누락", fill=FLAG_FILL["GAP"])
    ws.write(3, 1, "REVIEW: 분해 미인식 축·회사 고유 태그·정합성·KPI",
             fill=REVIEW_FILL)
    headers = ["Ticker", "Statement", "Line", "Year", "Flag", "Detail",
               "Tag", "Form", "Filed", "Accession"]
    for i, h in enumerate(headers, start=1):
        ws.write(4, i, h, bold=True, fill=HEADER_FILL)
    widths = [10, 18, 22, 8, 12, 48, 34, 10, 12, 22]
    for i, w in enumerate(widths, start=1):
        ws.set_col_width(i, w)
    # 제표 정규화 플래그 + 분해/KPI 검토 행을 한 시트에 합류시킨다(별도 시트 아님).
    rows = []
    for comp in companies:
        rows.extend(nz.collect_flags(comp, statements))
    for comp in companies:
        rows.extend(_segment_review_rows(comp))
    r = 5
    for row in rows:
        fill = FLAG_FILL.get(row["flag"]) or (
            REVIEW_FILL if row["flag"] == "REVIEW" else None)
        ws.write(r, 1, row["ticker"])
        ws.write(r, 2, row["statement"])
        ws.write(r, 3, row["line"])
        ws.write(r, 4, row["year"])
        ws.write(r, 5, row["flag"], fill=fill)
        ws.write(r, 6, row["detail"])
        ws.write(r, 7, row["tag"])
        ws.write(r, 8, row["form"])
        ws.write(r, 9, row["filed"])
        ws.write(r, 10, row["accn"])
        r += 1
    if not rows:
        ws.write(5, 1, "검토 필요 항목 없음 — 모든 매핑이 명확합니다.")
    ws.freeze(5, 1)


def _segment_review_rows(comp) -> list:
    """분해 검토 플래그(REVIEW: unknown-axis/custom-tag/does-not-reconcile)와
    회사 고유 KPI 후보를 Review 행 dict 으로 변환(collect_flags 와 같은 키 모양).

    회사 고유 KPI 는 표준 택소노미에 없어 자동 표준화가 불가능하다(ADR-007) →
    표준 항목인 척 섞지 않고 원본 태그/멤버/값 그대로 검토 큐에 나열한다.
    """
    seg = getattr(comp, "segments", None) or {}
    rows = []
    for ftype, detail in seg.get("flags", []):
        rows.append({
            "ticker": comp.ticker, "statement": "Disaggregation",
            "line": "", "year": "", "flag": ftype, "detail": detail,
            "tag": "", "form": "", "filed": "", "accn": "",
        })
    for kpi in seg.get("kpis", []):
        rows.append({
            "ticker": comp.ticker, "statement": "KPI (review)",
            "line": kpi.get("member") or "", "year": kpi.get("year") or "",
            "flag": "REVIEW", "detail": _kpi_detail(kpi),
            "tag": kpi.get("concept") or kpi.get("tag") or "",
            "form": kpi.get("form") or "", "filed": kpi.get("filed") or "",
            "accn": kpi.get("accn") or "",
        })
    return rows


def _kpi_detail(kpi) -> str:
    """회사 고유 KPI: 자동 표준화하지 않고 원본 값/단위 그대로 표기."""
    bits = ["company-specific KPI — 표준 택소노미 외, 자동 표준화 불가"]
    if kpi.get("value") is not None:
        bits.append(f"value={kpi['value']}")
    if kpi.get("unit"):
        bits.append(f"unit={kpi['unit']}")
    return "; ".join(bits)


def _write_provenance_sheet(ws, statements, companies):
    ws.write(1, 1, "Provenance — 모든 값의 출처(태그/공시) 추적", bold=True)
    headers = ["Ticker", "Statement", "Line", "Year", "Value", "us-gaap Tag",
               "Unit", "Form", "Filed", "Period End", "Accession"]
    for i, h in enumerate(headers, start=1):
        ws.write(3, i, h, bold=True, fill=HEADER_FILL)
    widths = [10, 18, 22, 8, 18, 34, 12, 8, 12, 12, 22]
    for i, w in enumerate(widths, start=1):
        ws.set_col_width(i, w)
    r = 4
    for comp in companies:
        for row in nz.collect_provenance(comp, statements):
            ws.write(r, 1, row["ticker"])
            ws.write(r, 2, row["statement"])
            ws.write(r, 3, row["line"])
            ws.write(r, 4, row["year"])
            ws.write(r, 5, row["value"], num_format=MONEY)
            ws.write(r, 6, row["tag"])
            ws.write(r, 7, row["unit"])
            ws.write(r, 8, row["form"])
            ws.write(r, 9, row["filed"])
            ws.write(r, 10, row["period_end"])
            ws.write(r, 11, row["accn"])
            r += 1
    # 분해 값 출처(축/멤버/group)도 같은 시트에 이어서 기록 — 출처 없는 값 금지.
    for comp in companies:
        for row in _segment_provenance_rows(comp):
            ws.write(r, 1, row["ticker"])
            ws.write(r, 2, row["statement"])
            ws.write(r, 3, row["line"])
            ws.write(r, 4, row["year"])
            ws.write(r, 5, row["value"], num_format=MONEY)
            ws.write(r, 6, row["tag"])
            ws.write(r, 7, row["unit"])
            ws.write(r, 8, row["form"])
            ws.write(r, 9, row["filed"])
            ws.write(r, 10, row["period_end"])
            ws.write(r, 11, row["accn"])
            r += 1
    ws.freeze(4, 1)


def _segment_provenance_rows(comp) -> list:
    """분해 값의 출처(축/멤버/group). step-2 출력엔 공시 accession 이 없으므로
    축·멤버·group·연도를 출처로 기록한다(unit/form/filed/accn 은 cli-integration
    이 채워 넣으면 함께 표기, 없으면 공란)."""
    seg = getattr(comp, "segments", None) or {}
    rows = []
    for group_key, label in DISAGG_GROUPS:
        gdict = seg.get(group_key) or {}
        axis = GROUP_AXIS.get(group_key, "")
        for member, by_year in gdict.items():
            for year in sorted(by_year):
                rows.append({
                    "ticker": comp.ticker, "statement": label, "line": member,
                    "year": year, "value": by_year[year], "tag": axis,
                    "unit": seg.get("unit") or "", "form": seg.get("form") or "",
                    "filed": seg.get("filed") or "", "period_end": "",
                    "accn": seg.get("accn") or "",
                })
    return rows
