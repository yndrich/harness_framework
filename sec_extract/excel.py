"""엑셀 워크북 생성.

구성: 제표별 시트(다기업이면 기업 블록을 가로로 나란히) + Comparison(핵심지표/마진)
+ Review(검토 필요 플래그) + Provenance(모든 값의 출처 추적).
검토 플래그는 셀 배경색으로 하이라이트한다.
"""

from __future__ import annotations

from .xlsx import Workbook
from .canonical_map import line_fmt
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
    headers = ["Ticker", "Statement", "Line", "Year", "Flag", "Detail",
               "Tag", "Form", "Filed", "Accession"]
    for i, h in enumerate(headers, start=1):
        ws.write(4, i, h, bold=True, fill=HEADER_FILL)
    widths = [10, 18, 22, 8, 12, 48, 34, 10, 12, 22]
    for i, w in enumerate(widths, start=1):
        ws.set_col_width(i, w)
    r = 5
    any_flag = False
    for comp in companies:
        for row in nz.collect_flags(comp, statements):
            any_flag = True
            fill = FLAG_FILL.get(row["flag"])
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
    if not any_flag:
        ws.write(5, 1, "검토 필요 항목 없음 — 모든 매핑이 명확합니다.")
    ws.freeze(5, 1)


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
    ws.freeze(4, 1)
