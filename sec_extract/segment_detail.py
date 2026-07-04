"""as-reported 충실 매출 분해 (표준화하지 않음).

기존 segments.build_disaggregation 은 멤버를 표준 그룹(segment/geography/product)에
'묶으려' 한다. 그건 기업 비교용 표준화 레이어다. 반면 이 모듈은 정반대 목표다:

  공시가 태깅한 **그대로**(축 QName · 멤버 QName · 기간 · 값 · 출처)를 손실 없이
  tidy 로 펼치고, 분기/연간 모두, 그리고 기간에 따른 **변경(신규/중단/재작성)**까지
  잡아서 보여준다.

설계 원칙:
- 표준 축(KNOWN_AXES)으로 거르지 않는다. 어떤 축·어떤 멤버든 전부 보존한다.
  (회사 고유 nvda:DataCenterMember, KPI 축 등도 그대로 — 자동 표준화는 본질적으로
   불가하므로 시도하지 않고 충실히 보존만 한다. 표준 라벨은 별도 별칭 레이어의 몫.)
- 분기 값은 quarterly 의 날짜 기반 차분 로직을 재사용한다(10-Q 는 YTD 일 수 있음).
- 한 축에 여러 분류가 겹쳐 멤버합 > 총계가 되면(예: NVDA Product 축) reconcile 에
  overlap=True 로 표면화한다(조용히 합치지 않는다).
- 다축(교차표) fact 는 합산 중복이라 멤버 행에서 제외한다.
"""

from __future__ import annotations

from . import quarterly as qt
from .canonical_map import axis_label, member_label
from .labels import label_for
from .normalize import REL_TOL, _rel_diff

OVERLAP_RATIO = 1.5   # 멤버합/총계 가 이보다 크면 '한 축에 분류가 겹침'으로 본다.


def _local(qname: str) -> str:
    return qname.split(":", 1)[1] if ":" in qname else qname


def _norm_fact(f: dict) -> dict:
    """인스턴스 fact → 분기 차분이 쓰는 모양({val,start,end,filed,...})."""
    return {
        "val": f.get("value"),
        "start": f.get("start"),
        "end": f.get("end") or f.get("instant"),
        "filed": f.get("filed"),
        "accn": f.get("accn"),
        "form": f.get("form"),
        "concept": f.get("concept"),
    }


def _series_index(facts: list, concept_tags) -> tuple[dict, list, dict]:
    """fact 들을 (axis,member) 시계열 / 무차원 총계 시계열로 가른다.

    반환: (members, totals, restated)
      members  : {(axis, member): [norm_fact, ...]}
      totals   : [norm_fact, ...]  (무차원 매출 = 총계)
      restated : {(axis, member, start, end): set(val)}  재작성 감지용
    """
    tagset = set(concept_tags)
    members: dict = {}
    totals: list = []
    restated: dict = {}
    for f in facts:
        if _local(f.get("concept") or "") not in tagset:
            continue
        if f.get("value") is None:
            continue
        dims = f.get("dims") or {}
        nf = _norm_fact(f)
        if not dims:
            totals.append(nf)
            continue
        if len(dims) != 1:          # 다축(교차표)은 합산 중복 → 멤버 행 제외
            continue
        axis, member = next(iter(dims.items()))
        members.setdefault((axis, member), []).append(nf)
        rk = (axis, member, nf["start"], nf["end"])
        restated.setdefault(rk, set()).add(round(float(nf["val"]), 2))
    return members, totals, restated


def _value_for(series, calendar, year, quarter):
    """quarter ∈ {1,2,3,4} → 이산 분기, 'FY' → 연간. 없으면 None."""
    if quarter == "FY":
        return qt.annual_from_facts(series, calendar, year)
    return qt.discrete_from_facts(series, calendar, year, quarter)


def build_as_reported(facts, concept_tags, calendar, periods,
                      annual_years=None, label_map=None):
    """충실 as-reported 매출 분해.

    facts: 인스턴스 fact 리스트(각 concept/value/dims/start/end/accn/filed/form).
    concept_tags: 분해 대상 개념(매출 후보 태그, local-name).
    calendar: qt.fiscal_calendar 결과.
    periods: [(fy, q)] 분기 목록.
    annual_years: 연간(FY) 행을 만들 회계연도들(기본 = periods 의 fy 집합).
    label_map: (선택) 공시 label linkbase 의 concept→표시라벨 맵. 각 행의 멤버
        QName 을 여기서 찾아 '원본' 표시라벨(예: "Data Center")을 붙인다. 없으면 "".

    반환 {rows, reconcile, changes} — 자세한 필드는 모듈/raw_model 참조.
    """
    lmap = label_map or {}
    members, totals, restated = _series_index(facts, concept_tags)
    if annual_years is None:
        annual_years = sorted({fy for fy, _ in periods})
    # 만들 (year, quarter) 셀 목록: 분기 + 연간
    cells = [(fy, q) for (fy, q) in periods] + [(fy, "FY") for fy in annual_years]

    rows = []
    # (axis, period) -> {member: val}  (reconcile 용)
    grouped: dict = {}
    # axis -> {member: set(periods with value)}  (change-log 용)
    seen: dict = {}
    for (axis, member), series in members.items():
        for (fy, q) in cells:
            cell = _value_for(series, calendar, fy, q)
            if cell is None:
                continue
            rows.append({
                "year": fy, "quarter": q, "axis": axis, "member": member,
                # 별칭 레이어(선택적 표시 라벨) — 원본 axis/member 는 그대로 유지.
                "axis_label": axis_label(axis),
                "label": member_label(member),   # 미정의면 None(빈칸)
                # '원본' = 공시 label linkbase 의 멤버 표시라벨(예: "Data Center").
                # 별칭(사람이 만든 한글)과 별개로 공시 원문 이름을 나란히 보존한다.
                "orig": label_for(lmap, member),
                "concept": _local((cell["fact"] or {}).get("concept") or ""),
                "val": cell["val"], "method": cell["method"],
                "accn": (cell["fact"] or {}).get("accn") or "",
                "filed": (cell["fact"] or {}).get("filed") or "",
                "form": (cell["fact"] or {}).get("form") or "",
            })
            grouped.setdefault((axis, fy, q), {})[member] = cell["val"]
            seen.setdefault(axis, {}).setdefault(member, set()).add((fy, q))

    reconcile = _reconcile(grouped, totals, calendar, cells)
    changes = _changes(seen, restated, periods)
    # 값이 잡힌 멤버 중 별칭이 아직 없는 것 — 사람이 canonical_map 에 채울 후보.
    valued = {(r["axis"], r["member"]) for r in rows}
    unaliased = sorted((ax, m) for (ax, m) in valued if member_label(m) is None)
    return {"rows": rows, "reconcile": reconcile, "changes": changes,
            "unaliased": unaliased}


def _reconcile(grouped, totals, calendar, cells):
    """(axis, period)별 멤버합 vs 무차원 총계 + overlap 플래그(정보성)."""
    total_by = {}
    for (fy, q) in cells:
        cell = _value_for(totals, calendar, fy, q)
        if cell is not None:
            total_by[(fy, q)] = cell["val"]
    out = []
    for (axis, fy, q), mem in sorted(grouped.items(),
                                     key=lambda kv: (kv[0][1], str(kv[0][2]), kv[0][0])):
        computed = sum(mem.values())
        total = total_by.get((fy, q))
        overlap = bool(total) and computed > abs(total) * OVERLAP_RATIO
        reconciles = (total is not None
                      and _rel_diff(computed, total) <= REL_TOL)
        out.append({
            "axis": axis, "year": fy, "quarter": q,
            "computed_sum": computed, "reported_total": total,
            "diff": (computed - total) if total is not None else None,
            "overlap": overlap, "reconciles": reconciles,
        })
    return out


def _pkey(fy, q):
    """정렬용 기간 키. 분기는 fy*4+q, FY 는 연말 직후로."""
    return fy * 4 + (4.5 if q == "FY" else q)


def _changes(seen, restated, periods):
    """축별 멤버의 신규 등장 / 중단 / 재작성을 이벤트로 표면화."""
    events = []
    qperiods = sorted(periods, key=lambda p: _pkey(*p))
    if qperiods:
        first_all = qperiods[0]
        last_all = qperiods[-1]
    for axis, mem in seen.items():
        for member, pset in sorted(mem.items()):
            qs = sorted((p for p in pset if p[1] != "FY"),
                        key=lambda p: _pkey(*p))
            if not qs:
                continue
            if qs[0] != first_all:
                events.append({
                    "axis": axis, "member": member, "event": "신규",
                    "period": f"{qs[0][0]}Q{qs[0][1]}",
                    "detail": "이 분기에 처음 등장",
                })
            if qs[-1] != last_all:
                events.append({
                    "axis": axis, "member": member, "event": "중단",
                    "period": f"{qs[-1][0]}Q{qs[-1][1]}",
                    "detail": "이후 분기에 보고 안 됨",
                })
    # 재작성: 같은 (axis, member, 기간)에 서로 다른 값이 두 번 이상
    for (axis, member, start, end), vals in restated.items():
        if len(vals) > 1:
            events.append({
                "axis": axis, "member": member, "event": "재작성",
                "period": f"{start}~{end}",
                "detail": "공시별 값 상이: " + " / ".join(f"{v:,.0f}" for v in sorted(vals)),
            })
    events.sort(key=lambda e: (e["axis"], e["member"], e["event"]))
    return events
