"""tidy Raw Data 출력 어댑터.

사용자의 엑셀 모델 스키마에 맞춰 분기 데이터를 떨군다(붙여넣기/링크용 별도 파일).
시트 구성:
- Raw Data : Raw_Financial 스키마
             [년도 | 분기 | Index | 항목(원본) | 항목 | 값 | Canonical Key | 기간]
             · 항목(원본) = 공시 label linkbase 표시라벨(예: "Net sales") — 실제
               재무제표와 매칭용. label_map 없으면 공란.
             · 항목 = 표준화 한글 라벨(예: 매출).
             주의: 항목(원본)을 항목 앞에 끼워 '값' 열이 한 칸 우측 이동한다 →
             기존 모델은 위치 대신 Canonical Key 기준 SUMIFS 사용을 권장.
- Meta Data: Period_Table [년도 | 분기 | Index | QuarterLabel]
- Event Log: [년도 | 분기 | INDEX | 구분 | 설명] 헤더만(정성 메모는 사람이 입력)
- Review   : 분기 추출에서 생긴 검토 플래그(있으면)

값 단위: 달러/주식은 백만 단위로 스케일(사용자 모델이 $M 기준). 각 값 시트 상단에
단위 안내(UNIT_NOTE)를 표기해 million/thousand 혼동을 막는다. Index = 년도×4 + 분기.
"""

from __future__ import annotations

from .xlsx import Workbook
from .canonical_map import line_ko, member_label, axis_label, STATEMENTS
from .labels import label_for
from . import quarterly as qt

HEADER_FILL = "D9E1F2"
SECTION_FILL = "E2EFDA"
TITLE = "Raw_Financial"
MONEY_FMT = "#,##0.##"
NOTE_FILL = "FCE4D6"
# 값 스케일 안내(모든 값 시트 상단에 표기 — million/thousand 혼동 방지).
UNIT_NOTE = "값 단위: 백만 USD ($M)  ·  주식수=백만 주  ·  주당값(EPS)=달러/주"
UNIT_NOTE_SEG = "값 단위: 백만 USD ($M)"


def _scale(val, unit):
    """달러·주식 수는 백만 단위로, 주당 값(USD/shares)은 그대로."""
    if unit in (None, "USD", "shares"):
        return val / 1_000_000
    return val


def _period_label(fy, q):
    """기간 라벨: 분기는 "26' Q1", 연간은 "26' FY" (Meta Data Period_Table 양식)."""
    if q == "FY":
        return f"{fy % 100:02d}' FY"
    return f"{fy % 100:02d}' Q{q}"


def build_rows(facts_obj, statements, periods, calendar=None, label_map=None):
    """tidy 행 리스트. 각 행: dict(year,q,index,item,orig_item,tag,val,key,...).

    calendar(매출 기준 회계 분기 달력)를 모든 항목에 공유해, fy 라벨이 비교표시로
    흩어진 값도 실제 날짜로 정확히 매핑한다(없으면 여기서 한 번 만든다).
    label_map: (선택) 공시 label linkbase 의 concept→표시라벨 맵. 채택된 us-gaap
        태그를 여기서 찾아 '원본' 항목명(예: "Net sales")을 붙인다. 없으면 "".
    """
    if calendar is None:
        calendar = qt.fiscal_calendar(facts_obj, statements)
    lmap = label_map or {}
    order = {p: i for i, p in enumerate(periods)}
    rows = []
    last = periods[-1] if periods else None
    for st in statements:
        ptype = st["period_type"]
        for line in st["lines"]:
            ko = line_ko(line)
            unit = line.get("unit")
            # companyfacts 에 단일 fact 가 없는 face 라인 → 값 대신 Review 로만 표면화
            if line.get("face_only"):
                if last is not None:
                    fy, q = last
                    rows.append({
                        "year": fy, "q": q, "index": fy * 4 + q, "item": ko,
                        "orig_item": "", "tag": None,
                        "val": None, "key": line["key"], "method": "",
                        "flags": [("REVIEW", line.get("note") or
                                   "companyfacts 에 단일 fact 없음 — inline-XBRL 필요")],
                        "fact": None,
                    })
                continue
            got = set()
            for (fy, q) in periods:
                cell = qt.quarterly_cell(facts_obj, line["tags"], fy, q, ptype,
                                         unit=unit, calendar=calendar)
                if not cell or cell.get("val") is None:
                    continue
                u = cell.get("unit") or unit
                got.add((fy, q))
                tag = cell.get("tag")
                rows.append({
                    "year": fy, "q": q, "index": fy * 4 + q,
                    "item": ko, "orig_item": label_for(lmap, tag), "tag": tag,
                    "val": _scale(cell["val"], u),
                    "key": line["key"], "method": cell.get("method"),
                    "flags": cell.get("flags", []), "fact": cell.get("fact"),
                })
            # 내부 결손(GAP): 앞뒤 분기엔 값이 있는데 중간이 비면 표면화한다.
            # (도구 누락이 아니라 SEC companyfacts 원본에 그 기간 값이 없음을 명시)
            rows.extend(_gap_rows(line, ko, periods, order, got))
    return rows


def _gap_rows(line, ko, periods, order, got):
    """값이 잡힌 분기들 사이(내부)의 결손 분기를 GAP 마커 행으로 만든다.

    선행/후행 결손(태그가 최근 도입/폐지)은 제외하고, 양쪽에 값이 있는 중간
    결손만 GAP 으로 띄운다 — normalize 의 연간 GAP 과 같은 의미."""
    if not got:
        return []
    idxs = sorted(order[p] for p in got)
    lo, hi = idxs[0], idxs[-1]
    out = []
    for (fy, q) in periods:
        i = order[(fy, q)]
        if lo < i < hi and (fy, q) not in got:
            out.append({
                "year": fy, "q": q, "index": fy * 4 + q, "item": ko,
                "orig_item": "", "tag": None,
                "val": None, "key": line["key"], "method": "",
                "flags": [("GAP", "SEC companyfacts 에 해당 분기 값 없음 "
                           "(차분 불가/미보고)")],
                "fact": None,
            })
    return out


def write_raw_model_workbook(companies, path):
    """companies: [(ticker, rows, periods[, seg_detail])] -> 워크북 저장.

    seg_detail(as-reported 매출 분해)이 있으면 Segment Detail/Reconcile/Changes
    시트를 추가한다."""
    multi = len(companies) > 1
    wb = Workbook()
    _write_raw_data(wb.add_sheet("Raw Data"), companies, multi)
    _write_raw_pivot(wb.add_sheet("Raw Pivot"), companies, multi)
    _write_meta_data(wb.add_sheet("Meta Data"), companies)
    _write_event_log(wb.add_sheet("Event Log"))
    _write_review(wb.add_sheet("Review"), companies, multi)
    if any(_seg(c) for c in companies):
        _write_segment_detail(wb.add_sheet("Segment Detail"), companies, multi)
        _write_segment_pivot(wb.add_sheet("Segment Pivot"), companies, multi)
        _write_segment_reconcile(wb.add_sheet("Segment Reconcile"), companies, multi)
        _write_segment_changes(wb.add_sheet("Segment Changes"), companies, multi)
    wb.save(path)


def _seg(company):
    """company 튜플에서 seg_detail(없으면 None)."""
    return company[3] if len(company) > 3 else None


def _qlabel(q):
    return "FY" if q == "FY" else f"Q{q}"


def _write_raw_data(ws, companies, multi):
    ws.write(1, 1, TITLE, bold=True)
    ws.write(1, 3, UNIT_NOTE, bold=True, fill=NOTE_FILL)   # 값 단위 안내(상단)
    # 기존 모델 스키마(년도|분기|Index|항목|값) + '항목(원본)'(공시 표시라벨)을 항목
    # 앞에, Canonical Key·기간을 끝에 덧붙인다. 값/Key 는 여전히 뒤쪽이라 기존 모델의
    # 열 참조가 깨질 수 있으므로 SUMIFS 는 Canonical Key 기준 사용을 권장(문서화).
    headers = (["Ticker"] if multi else []) + \
        ["년도", "분기", "Index", "항목(원본)", "항목", "값", "Canonical Key", "기간"]
    for i, h in enumerate(headers, start=1):
        ws.write(2, i, h, bold=True, fill=HEADER_FILL)
    widths = ([10] if multi else []) + [8, 6, 8, 30, 20, 16, 22, 9]
    for i, w in enumerate(widths, start=1):
        ws.set_col_width(i, w)
    r = 3
    for ticker, rows, *_ in companies:
        for row in rows:
            if row.get("val") is None:   # GAP 마커 행은 Review 에만 표시
                continue
            c = 1
            if multi:
                ws.write(r, c, ticker); c += 1
            ws.write(r, c, row["year"]); c += 1
            ws.write(r, c, row["q"]); c += 1
            ws.write(r, c, row["index"]); c += 1
            ws.write(r, c, row.get("orig_item", "")); c += 1
            ws.write(r, c, row["item"]); c += 1
            ws.write(r, c, row["val"], num_format=MONEY_FMT); c += 1
            ws.write(r, c, row["key"]); c += 1
            ws.write(r, c, _period_label(row["year"], row["q"]))
            r += 1
    if r > 3:
        ws.auto_filter(2, 1, r - 1, len(headers))
    ws.freeze(3, 1)


def _write_raw_pivot(ws, companies, multi):
    """항목 × 분기 행렬 (읽기용). tidy 와 같은 값, 보기 좋게 가로 배치 + 행별 색조."""
    ws.write(1, 1, "Raw Pivot — 항목 × 분기 (행별 값 색조)", bold=True)
    ws.write(1, 4, UNIT_NOTE, bold=True, fill=NOTE_FILL)
    periods = sorted({p for c in companies for p in c[2]})
    first_val = 2
    ncols = first_val + len(periods) - 1
    ws.write(2, 1, "항목", bold=True, fill=HEADER_FILL)
    ws.set_col_width(1, 24)
    for j, (fy, q) in enumerate(periods):
        ws.write(2, first_val + j, _period_label(fy, q), bold=True,
                 fill=HEADER_FILL, align="right")
        ws.set_col_width(first_val + j, 9)
    r = 3
    for ticker, rows, _periods, *_ in companies:
        if multi:
            ws.write(r, 1, f"▼ {ticker}", bold=True, fill=SECTION_FILL); r += 1
        lut = {(row["key"], (row["year"], row["q"])): row["val"]
               for row in rows if row.get("val") is not None}
        for st in STATEMENTS:
            keys = [ln["key"] for ln in st["lines"] if not ln.get("face_only")]
            if not any((k, p) in lut for k in keys for p in periods):
                continue
            ws.write(r, 1, st["label"], bold=True, fill=SECTION_FILL); r += 1
            for line in st["lines"]:
                if line.get("face_only"):
                    continue
                vals = [lut.get((line["key"], p)) for p in periods]
                if not any(v is not None for v in vals):
                    continue
                ws.write(r, 1, line_ko(line))
                for j, v in enumerate(vals):
                    if v is not None:
                        ws.write(r, first_val + j, v, num_format=MONEY_FMT)
                ws.color_scale(r, first_val, r, ncols)
                r += 1
    ws.freeze(3, first_val)


def _write_meta_data(ws, companies):
    ws.write(1, 1, "Period_Table", bold=True)
    for i, h in enumerate(["년도", "분기", "Index", "QuarterLabel"], start=1):
        ws.write(2, i, h, bold=True, fill=HEADER_FILL)
        ws.set_col_width(i, [8, 6, 8, 16][i - 1])
    periods = sorted({p for c in companies for p in c[2]})
    r = 3
    for (fy, q) in periods:
        ws.write(r, 1, fy)
        ws.write(r, 2, q)
        ws.write(r, 3, fy * 4 + q)
        ws.write(r, 4, f"{fy % 100:02d}' Q{q}")
        r += 1
    ws.freeze(3, 1)


def _write_event_log(ws):
    ws.write(1, 1, "EventLog (정성 메모 — 직접 입력)", bold=True)
    for i, h in enumerate(["년도", "분기", "INDEX", "구분", "설명"], start=1):
        ws.write(2, i, h, bold=True, fill=HEADER_FILL)
        ws.set_col_width(i, [8, 6, 8, 12, 50][i - 1])


def _write_review(ws, companies, multi):
    cols = (["Ticker"] if multi else []) + \
        ["년도", "분기", "항목", "Canonical Key", "Flag", "Detail", "Method"]
    for i, h in enumerate(cols, start=1):
        ws.write(1, i, h, bold=True, fill=HEADER_FILL)
    widths = ([10] if multi else []) + [8, 6, 18, 20, 12, 44, 16]
    for i, w in enumerate(widths, start=1):
        ws.set_col_width(i, w)
    r = 2
    any_flag = False
    for ticker, rows, *_ in companies:
        for row in rows:
            for ftype, detail in row.get("flags", []):
                any_flag = True
                c = 1
                if multi:
                    ws.write(r, c, ticker); c += 1
                ws.write(r, c, row["year"]); c += 1
                ws.write(r, c, row["q"]); c += 1
                ws.write(r, c, row["item"]); c += 1
                ws.write(r, c, row["key"]); c += 1
                ws.write(r, c, ftype, fill="FFF2CC"); c += 1
                ws.write(r, c, detail); c += 1
                ws.write(r, c, row.get("method") or "")
                r += 1
    if not any_flag:
        ws.write(2, 1, "검토 필요 항목 없음.")
    ws.freeze(2, 1)


# ---- as-reported 매출 분해 시트 (Segment Detail / Reconcile / Changes) ----

def _write_segment_detail(ws, companies, multi):
    """as-reported 매출 분해 — Raw Data 와 동일한 tidy 양식.

    [Ticker?] 년도 | 분기 | Index | 항목 | 값 | Canonical Key.
    Raw Data 가 3대 제표를 Canonical Key 로 구분해 펼치듯, 여기선 축 멤버를
    Canonical Key(=멤버 QName)로 구분해 펼친다. 항목=별칭(없으면 멤버 QName),
    Index=년도×4+분기(Period_Table 과 동일 조인 키, FY 행은 분기 개념이 아니라 빈칸)."""
    ws.write(1, 1, "Segment_Financial", bold=True)
    ws.write(1, 3, UNIT_NOTE_SEG, bold=True, fill=NOTE_FILL)   # 값 단위 안내(상단)
    headers = (["Ticker"] if multi else []) + \
        ["년도", "분기", "Index", "항목(원본)", "항목", "값", "Canonical Key", "기간"]
    for i, h in enumerate(headers, start=1):
        ws.write(2, i, h, bold=True, fill=HEADER_FILL)
    widths = ([10] if multi else []) + [8, 6, 8, 26, 26, 16, 40, 9]
    for i, w in enumerate(widths, start=1):
        ws.set_col_width(i, w)
    r = 3
    for ticker, _rows, _periods, *rest in companies:
        seg = rest[0] if rest else None
        if not seg:
            continue
        for row in sorted(seg["rows"], key=lambda x: (
                x["axis"], x["member"], x["year"],
                99 if x["quarter"] == "FY" else x["quarter"])):
            q = row["quarter"]
            lab = row.get("label")
            orig = row.get("orig", "")
            c = 1
            if multi:
                ws.write(r, c, ticker); c += 1
            ws.write(r, c, row["year"]); c += 1
            # 분기 = Raw Data 와 동일하게 정수 1~4, 연간은 "FY".
            ws.write(r, c, q); c += 1
            # Index = 년도×4+분기 (분기행만), FY 는 빈칸.
            ws.write(r, c, "" if q == "FY" else row["year"] * 4 + q); c += 1
            # 항목(원본) = 공시 표시라벨(예: "Data Center"). 없으면 노란 강조(공시가
            # 이 멤버에 로컬 라벨을 안 붙였거나 표준 택소노미 멤버 → 라벨 미취득).
            ws.write(r, c, orig, fill=None if orig else "FFF2CC"); c += 1
            # 항목 = 별칭. 미정의면 멤버 QName 으로 채우고 노란 강조(채울 대상 표시).
            ws.write(r, c, lab or row["member"],
                     fill=None if lab else "FFF2CC"); c += 1
            ws.write(r, c, _scale(row["val"], None), num_format=MONEY_FMT); c += 1
            ws.write(r, c, row["member"]); c += 1   # Canonical Key = 멤버 QName
            ws.write(r, c, _period_label(row["year"], q))
            r += 1
    if r > 3:
        ws.auto_filter(2, 1, r - 1, len(headers))
    ws.freeze(3, 1)


def _write_segment_pivot(ws, companies, multi):
    """축·멤버 × 분기 행렬 (읽기용, FY 제외). 축별 섹션 + 행별 값 색조."""
    ws.write(1, 1, "Segment Pivot — 축·멤버 × 분기 (행별 값 색조)", bold=True)
    ws.write(1, 4, UNIT_NOTE_SEG, bold=True, fill=NOTE_FILL)
    periods = sorted({(row["year"], row["quarter"])
                      for c in companies if _seg(c)
                      for row in _seg(c)["rows"] if row["quarter"] != "FY"})
    first_val = 2
    ncols = first_val + len(periods) - 1
    ws.write(2, 1, "항목", bold=True, fill=HEADER_FILL)
    ws.set_col_width(1, 28)
    for j, (fy, q) in enumerate(periods):
        ws.write(2, first_val + j, _period_label(fy, q), bold=True,
                 fill=HEADER_FILL, align="right")
        ws.set_col_width(first_val + j, 9)
    r = 3
    for ticker, _rows, _periods, *rest in companies:
        seg = rest[0] if rest else None
        if not seg:
            continue
        if multi:
            ws.write(r, 1, f"▼ {ticker}", bold=True, fill=SECTION_FILL); r += 1
        lut, members = {}, {}
        for row in seg["rows"]:
            if row["quarter"] == "FY":
                continue
            lut[(row["axis"], row["member"], (row["year"], row["quarter"]))] = \
                _scale(row["val"], None)
            members.setdefault(row["axis"], {})[row["member"]] = row.get("label")
        for axis in sorted(members):
            ws.write(r, 1, axis_label(axis), bold=True, fill=SECTION_FILL); r += 1
            for member in sorted(members[axis]):
                vals = [lut.get((axis, member, p)) for p in periods]
                if not any(v is not None for v in vals):
                    continue
                ws.write(r, 1, members[axis][member] or member)
                for j, v in enumerate(vals):
                    if v is not None:
                        ws.write(r, first_val + j, v, num_format=MONEY_FMT)
                ws.color_scale(r, first_val, r, ncols)
                r += 1
    ws.freeze(3, first_val)


def _write_segment_reconcile(ws, companies, multi):
    """(축, 기간)별 멤버합 vs 보고총계. overlap=True 면 한 축에 분류가 겹친 것."""
    ws.write(1, 1, "Reconciliation — Σmembers vs 보고총계 (정보성)", bold=True)
    cols = (["Ticker"] if multi else []) + \
        ["축(Axis)", "년도", "분기", "Σmembers($M)", "총계($M)", "Diff($M)",
         "Overlap", "일치"]
    for i, h in enumerate(cols, start=1):
        ws.write(2, i, h, bold=True, fill=HEADER_FILL)
    widths = ([10] if multi else []) + [34, 8, 6, 16, 16, 14, 10, 8]
    for i, w in enumerate(widths, start=1):
        ws.set_col_width(i, w)
    r = 3
    for ticker, _rows, _periods, *rest in companies:
        seg = rest[0] if rest else None
        if not seg:
            continue
        for rc in seg["reconcile"]:
            c = 1
            if multi:
                ws.write(r, c, ticker); c += 1
            ws.write(r, c, rc["axis"]); c += 1
            ws.write(r, c, rc["year"]); c += 1
            ws.write(r, c, _qlabel(rc["quarter"])); c += 1
            ws.write(r, c, _scale(rc["computed_sum"], None), num_format="#,##0.##"); c += 1
            tot = rc["reported_total"]
            ws.write(r, c, _scale(tot, None) if tot is not None else "",
                     num_format="#,##0.##"); c += 1
            diff = rc["diff"]
            ws.write(r, c, _scale(diff, None) if diff is not None else "",
                     num_format="#,##0.##"); c += 1
            ws.write(r, c, "겹침" if rc["overlap"] else "",
                     fill="FFF2CC" if rc["overlap"] else None); c += 1
            ws.write(r, c, "✓" if rc["reconciles"] else "")
            r += 1
    ws.freeze(3, 1)


def _write_segment_changes(ws, companies, multi):
    """멤버의 신규 등장 / 중단 / 재작성 (분기에 따른 보고 변경 추적)."""
    ws.write(1, 1, "Change Log — 분해 멤버의 신규/중단/재작성 + 별칭 미정의", bold=True)
    cols = (["Ticker"] if multi else []) + \
        ["축(Axis)", "멤버(Member)", "별칭", "이벤트", "시점", "상세"]
    for i, h in enumerate(cols, start=1):
        ws.write(2, i, h, bold=True, fill=HEADER_FILL)
    widths = ([10] if multi else []) + [34, 40, 22, 12, 22, 46]
    for i, w in enumerate(widths, start=1):
        ws.set_col_width(i, w)
    r = 3
    any_ev = False
    for ticker, _rows, _periods, *rest in companies:
        seg = rest[0] if rest else None
        if not seg:
            continue
        for ev in seg["changes"]:
            any_ev = True
            c = 1
            if multi:
                ws.write(r, c, ticker); c += 1
            ws.write(r, c, ev["axis"]); c += 1
            ws.write(r, c, ev["member"]); c += 1
            ws.write(r, c, member_label(ev["member"]) or ""); c += 1
            ws.write(r, c, ev["event"], fill="FFF2CC"); c += 1
            ws.write(r, c, ev["period"]); c += 1
            ws.write(r, c, ev["detail"])
            r += 1
        # 별칭 미정의 멤버 — canonical_map.MEMBER_ALIASES 에 추가하면 별칭 열이 채워진다.
        for axis, member in seg.get("unaliased", []):
            any_ev = True
            c = 1
            if multi:
                ws.write(r, c, ticker); c += 1
            ws.write(r, c, axis); c += 1
            ws.write(r, c, member); c += 1
            ws.write(r, c, "", fill="FFF2CC"); c += 1
            ws.write(r, c, "별칭미정의", fill="FFF2CC"); c += 1
            ws.write(r, c, ""); c += 1
            ws.write(r, c, "canonical_map.MEMBER_ALIASES 에 추가 권장")
            r += 1
    if not any_ev:
        ws.write(3, 1, "변경 이벤트 없음.")
    ws.freeze(3, 1)
