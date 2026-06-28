"""분기 추출: companyfacts 에서 '이산 분기(discrete quarter)' 값을 만든다.

10-Q 의 손익/현금흐름은 YTD(연초 누적)로 보고되는 경우가 많다. 따라서:
- 직접 3개월 fact 가 있으면 그대로 사용(손익계산서는 보통 있음).
- 없으면 YTD 차분: 이산(Qn) = YTD(Qn) − YTD(Q n-1).  (현금흐름표 경로)
- Q4 는 10-Q 가 없으므로: 이산(Q4) = 연간(10-K) − 9개월 YTD(Q3).
재무상태표(시점)는 분기말 잔액을 그대로 사용한다(차분 불필요).

핵심(중요): companyfacts 의 fy/fp 는 '공시의 회계연도'라, 같은 달력 기간 값이
비교표시(comparative)로 여러 fy 에 흩어진다(예: capex 2024Q1 값이 fy2025 로
찍혀 있음). 또 회사가 태그를 바꾸면(PP&E→ProductiveAssets) 라벨도 흔들린다.
그래서 fy/fp 라벨로 매칭하면 멀쩡한 값을 놓친다.

해결: '매출(revenue)'은 깨끗하고 완전하므로, 매출로 **회계 분기 달력**(fy,q →
실제 start/end 날짜)을 만들고, 모든 항목을 fy/fp 가 아니라 **실제 날짜**로 그
달력에 매핑한다. 비교표시로 엉뚱한 fy 에 찍힌 값도 날짜로 정확히 회수된다.
달력이 주어지지 않으면(단위 테스트 등) 기존 fy/fp 기반 경로로 폴백한다.
"""

from __future__ import annotations

import re
from datetime import date, timedelta

from .normalize import REL_TOL, _rel_diff

# 기간 길이(일) 버킷 — 분기/반기/3분기/연간
_BUCKETS = (("Q", 80, 100), ("H", 170, 195), ("T", 260, 285), ("Y", 350, 380))
FP_TO_Q = {"Q1": 1, "Q2": 2, "Q3": 3}
Q_TO_FP = {1: "Q1", 2: "Q2", 3: "Q3", 4: "FY"}

DAY_TOL = 10            # 분기 경계 날짜 매칭 허용 오차(13주 회계달력 드리프트 흡수)
_QUARTER_DAYS = 91.3125  # 365.25 / 4


def _d(s: str) -> date:
    return date.fromisoformat(s)


def _dur(f: dict):
    if not f.get("start") or not f.get("end"):
        return None
    return (_d(f["end"]) - _d(f["start"])).days


def _bucket(f: dict):
    days = _dur(f)
    if days is None:
        return None
    for name, lo, hi in _BUCKETS:
        if lo <= days <= hi:
            return name
    return None


def _latest(facts: list):
    if not facts:
        return None
    return sorted(facts, key=lambda f: f.get("filed") or "", reverse=True)[0]


# ============================================================================
# 날짜 기반 경로 (달력이 주어졌을 때) — fy/fp 라벨에 의존하지 않는다.
# ============================================================================

def _within(a: date, b: date, tol: int = DAY_TOL) -> bool:
    return abs((a - b).days) <= tol


def fiscal_calendar(facts_obj, statements) -> dict:
    """매출(revenue) fact 로 회계 분기 달력을 만든다.

    반환: {(fy, q): {"start": fy_start(date), "end": q_end(date)}}.
    fy/q 라벨은 매출의 fy 그룹에서 가져오되, 분기 끝 날짜는 실제 end 날짜를,
    분기 인덱스는 (fy_start 로부터 경과 일수 / 분기길이) 로 정해 결측 분기에도
    안전하게 매핑한다.
    """
    rev = next((l for st in statements for l in st["lines"]
                if l["key"] == "revenue"), None)
    if rev is None:
        return {}
    facts = []
    for tag in rev["tags"]:
        for f in facts_obj.facts_for(tag):
            if (f.get("start") and f.get("end") and f.get("val") is not None
                    and f.get("fy") is not None):
                facts.append(f)
    cal: dict = {}
    for fy in sorted({int(f["fy"]) for f in facts}):
        ff = [f for f in facts if int(f["fy"]) == fy]
        if not ff:
            continue
        fy_end = max(_d(f["end"]) for f in ff)
        # fy_start = fy_end 까지 가는 가장 긴 기간(YTD/연간)의 start
        to_end = [f for f in ff if _within(_d(f["end"]), fy_end, 3)]
        longest = max(to_end, key=lambda f: _dur(f) or 0)
        fy_start = _d(longest["start"])
        # 이 회계연도 내(비교표시=이전연도 end 제외) 분기 끝 날짜들
        qends = sorted({_d(f["end"]) for f in ff
                        if fy_start < _d(f["end"]) <= fy_end + timedelta(days=3)})
        for qe in qends:
            qi = round((qe - fy_start).days / _QUARTER_DAYS)
            qi = min(4, max(1, qi))
            cal[(fy, qi)] = {"start": fy_start, "end": qe}
    return cal


def _dedup_period(facts: list) -> list:
    """(start, end) 별 최신 제출본만 남긴다(분기 재작성 dedup)."""
    best: dict = {}
    for f in facts:
        if f.get("val") is None or not f.get("end"):
            continue
        key = (f.get("start"), f.get("end"))
        cur = best.get(key)
        if cur is None or (f.get("filed") or "") > (cur.get("filed") or ""):
            best[key] = f
    return list(best.values())


def _pick(facts: list, end: date, start: date | None = None,
          dur_lo: int | None = None, dur_hi: int | None = None):
    """end(+선택적 start, 기간길이) 가 근사 일치하는 fact. 가장 근접한 것."""
    cand = []
    for f in facts:
        if not f.get("end") or not _within(_d(f["end"]), end):
            continue
        if start is not None:
            if not f.get("start") or not _within(_d(f["start"]), start):
                continue
        if dur_lo is not None:
            dd = _dur(f)
            if dd is None or not (dur_lo <= dd <= dur_hi):
                continue
        cand.append(f)
    if not cand:
        return None
    return min(cand, key=lambda f: abs((_d(f["end"]) - end).days))


def _discrete_by_dates(facts, fy_start, q, q_end, prev_q_end):
    """달력 날짜로 이산 분기 값 + 방법 + 소스. 불가하면 (None, None, None)."""
    pool = _dedup_period(facts)
    # 1) 직접 3개월 fact (시작 = 직전 분기 끝, 길이 ~90일)
    q_start = fy_start if q == 1 else prev_q_end
    direct = _pick(pool, q_end, start=q_start, dur_lo=80, dur_hi=100)
    if direct is not None:
        return direct["val"], "direct", direct
    # 2) YTD 차분 (시작 = 회계연도 시작)
    ytd_this = _pick(pool, q_end, start=fy_start)
    if ytd_this is None:
        return None, None, None
    if q == 1:
        return ytd_this["val"], "ytd", ytd_this
    ytd_prev = _pick(pool, prev_q_end, start=fy_start)
    if ytd_prev is None:
        return None, None, None
    method = "annual-minus-9mo" if q == 4 else "ytd-diff"
    return ytd_this["val"] - ytd_prev["val"], method, ytd_this


def _instant_by_dates(facts, q_end):
    """분기말 시점 잔액을 end 날짜로 매칭. 가장 근접한 end 중 최신 제출본."""
    cand = [f for f in facts
            if not f.get("start") and f.get("end") and f.get("val") is not None
            and _within(_d(f["end"]), q_end)]
    if not cand:
        return None, None, None
    best = min(abs((_d(f["end"]) - q_end).days) for f in cand)
    near = [f for f in cand if abs((_d(f["end"]) - q_end).days) == best]
    chosen = _latest(near)
    return chosen["val"], "instant", chosen


# ============================================================================
# 폴백 경로 (달력 없음) — 기존 fy/fp 라벨 기반. 깨끗한 단일 태그에 한해 정확.
# ============================================================================

def _dur_fact(facts, fy, fp, bucket):
    """(fy, fp, 기간버킷)에 맞는 duration fact.

    주의: companyfacts 의 fy/fp 는 '공시의 회계연도'라, 같은 (fy, fp) 버킷에
    현재 기간과 '전년 비교(comparative)' 값이 함께 들어온다(둘 다 end 만 다름).
    따라서 가장 늦은 end(=현재 기간)를 고른 뒤, 그 안에서 최신 제출본을 택한다.
    """
    cand = [f for f in facts
            if f.get("fy") == fy and f.get("fp") == fp
            and _bucket(f) == bucket and f.get("val") is not None and f.get("end")]
    if not cand:
        return None
    max_end = max(_d(f["end"]) for f in cand)
    return _latest([f for f in cand if _d(f["end"]) == max_end])


def _discrete_duration(facts, fy, q):
    """이산 분기 값 + 방법 + 소스 fact. 불가하면 (None, None, None)."""
    if q in (1, 2, 3):
        fp = f"Q{q}"
        direct = _dur_fact(facts, fy, fp, "Q")
        if direct is not None:
            return direct["val"], "direct", direct
        # YTD 차분 경로 (현금흐름표 등)
        ytd_bucket = {1: "Q", 2: "H", 3: "T"}[q]
        ytd = _dur_fact(facts, fy, fp, ytd_bucket)
        if ytd is None:
            return None, None, None
        if q == 1:
            return ytd["val"], "ytd", ytd
        prev = _dur_fact(facts, fy, f"Q{q-1}", {2: "Q", 3: "H"}[q])
        if prev is None:
            return None, None, None
        return ytd["val"] - prev["val"], "ytd-diff", ytd
    # q == 4: 연간 − 9개월 YTD
    annual = _dur_fact(facts, fy, "FY", "Y")
    if annual is None:
        return None, None, None
    ytd9 = _dur_fact(facts, fy, "Q3", "T")
    if ytd9 is None:
        return None, None, None
    return annual["val"] - ytd9["val"], "annual-minus-9mo", annual


def _instant_value(facts, fy, q):
    """분기말 시점 잔액(재무상태표). 현재기 잔액 = 같은 fy/fp 중 가장 늦은 end."""
    fp = Q_TO_FP[q]
    cand = [f for f in facts
            if f.get("fy") == fy and f.get("fp") == fp
            and not f.get("start") and f.get("end") and f.get("val") is not None]
    if not cand:
        return None, None, None
    max_end = max(_d(f["end"]) for f in cand)
    chosen = _latest([f for f in cand if _d(f["end"]) == max_end])
    return chosen["val"], "instant", chosen


# ============================================================================
# 공통 조립 + 진입점
# ============================================================================

def _assemble(hits, unit):
    """후보 태그 hit 들에서 우선순위 1번 채택 + 충돌 시 AMBIGUOUS 플래그."""
    if not hits:
        return None
    primary = hits[0]
    flags = []
    for other in hits[1:]:
        if _rel_diff(primary["val"], other["val"]) > REL_TOL:
            flags.append(("AMBIGUOUS",
                          f"{other['tag']}={other['val']:,.0f} vs "
                          f"{primary['tag']}={primary['val']:,.0f}"))
    return {"val": primary["val"], "tag": primary["tag"],
            "method": primary["method"], "fact": primary["fact"],
            "unit": unit, "flags": flags}


def quarterly_cell(facts_obj, candidate_tags, fy, q, period_type, unit=None,
                   calendar=None):
    """(표준항목, fy, 분기) 한 칸을 이산 분기 값으로 해석. 없으면 None.

    calendar 가 주어지면 날짜 기반(권장, fy 라벨 흩어짐에 강건)으로, 없으면 기존
    fy/fp 라벨 기반으로 해석한다.
    """
    if calendar is not None:
        win = calendar.get((fy, q))
        if win is None:
            return None
        fy_start, q_end = win["start"], win["end"]
        prev = calendar.get((fy, q - 1))
        prev_q_end = prev["end"] if prev else fy_start
        hits = []
        for idx, tag in enumerate(candidate_tags):
            facts = facts_obj.facts_for(tag, unit=unit)
            if not facts:
                continue
            if period_type == "instant":
                val, method, src = _instant_by_dates(facts, q_end)
            else:
                val, method, src = _discrete_by_dates(
                    facts, fy_start, q, q_end, prev_q_end)
            if val is not None:
                hits.append({"priority": idx, "tag": tag, "val": val,
                             "method": method, "fact": src})
        return _assemble(hits, unit)

    # --- 폴백: 달력 없음 → 기존 fy/fp 라벨 기반 ---
    hits = []
    for idx, tag in enumerate(candidate_tags):
        facts = facts_obj.facts_for(tag, unit=unit)
        if not facts:
            continue
        if period_type == "instant":
            val, method, src = _instant_value(facts, fy, q)
        else:
            val, method, src = _discrete_duration(facts, fy, q)
        if val is not None:
            hits.append({"priority": idx, "tag": tag, "val": val,
                         "method": method, "fact": src})
    return _assemble(hits, unit)


def available_quarters(facts_obj, statements):
    """매출(revenue) 기준 회계 분기 달력의 (fy, 분기) 목록(오름차순)."""
    return sorted(fiscal_calendar(facts_obj, statements).keys())


# ============================================================================
# 분기 선택 (--period) — 사용자가 특정 분기/범위만 뽑을 때 periods 필터
# ============================================================================

_PERIOD_RE = re.compile(r"^(\d{4})\s*Q([1-4])$", re.IGNORECASE)


def parse_period_token(tok):
    """'2025Q1' → (2025, 1). 형식이 아니면 ValueError.

    공백·대소문자를 허용한다(' 2024q3 '). fy 는 '회계연도' 번호(companyfacts 의
    fy 와 동일 기준)이고 분기는 1–4 이다.
    """
    m = _PERIOD_RE.match((tok or "").strip())
    if not m:
        raise ValueError(
            f"분기 형식 오류: {tok!r} — 'YYYYQn'(예: 2025Q1) 형식이어야 함")
    return (int(m.group(1)), int(m.group(2)))


def select_periods(available, specs):
    """available((fy,q) 목록)에서 specs 에 맞는 분기만 정렬·중복제거하여 반환.

    각 spec 은 단일 'YYYYQn' 또는 범위 'YYYYQn:YYYYQm'(양끝 포함, 순서 무관).
    형식 오류 → ValueError. 매칭되는 분기가 없으면 → ValueError(가능 범위 안내).
    available 은 매출 기준 회계 분기 달력의 키라, 여기에 없는 분기는 도구가
    값을 만들 수 없으므로(날조 금지) 명시적 오류로 표면화한다.
    """
    avail = sorted(available)
    if not avail:
        raise ValueError("선택할 분기 데이터가 없습니다")
    span = f"{avail[0][0]}Q{avail[0][1]}–{avail[-1][0]}Q{avail[-1][1]}"
    chosen = set()
    for spec in specs:
        s = (spec or "").strip()
        if ":" in s:
            lo_s, hi_s = s.split(":", 1)
            lo, hi = parse_period_token(lo_s), parse_period_token(hi_s)
            if lo > hi:
                lo, hi = hi, lo
            matched = [p for p in avail if lo <= p <= hi]
            if not matched:
                raise ValueError(f"{s}: 해당 범위에 분기 없음 (가능: {span})")
            chosen.update(matched)
        else:
            p = parse_period_token(s)
            if p not in avail:
                raise ValueError(f"{s}: 분기 데이터 없음 (가능: {span})")
            chosen.add(p)
    return sorted(chosen)


def discrete_from_facts(facts, calendar, fy, q):
    """플랫 fact 리스트(각 {val,start,end,filed})에서 (fy,q) 이산 분기값.

    segment_detail 등 facts_obj 가 아닌 단일 시계열(예: 한 축·멤버의 매출)에 쓰려고
    quarterly_cell 의 날짜 기반 차분 로직을 재사용한다. 없으면 None."""
    win = calendar.get((fy, q))
    if win is None:
        return None
    fy_start, q_end = win["start"], win["end"]
    prev = calendar.get((fy, q - 1))
    prev_q_end = prev["end"] if prev else fy_start
    val, method, src = _discrete_by_dates(facts, fy_start, q, q_end, prev_q_end)
    if val is None:
        return None
    return {"val": val, "method": method, "fact": src}


def annual_from_facts(facts, calendar, fy):
    """플랫 fact 리스트에서 회계연도 연간값(start≈fy_start, end≈fy_end, ~1년). 없으면 None."""
    win = calendar.get((fy, 4)) or calendar.get((fy, 3)) or calendar.get((fy, 2)) \
        or calendar.get((fy, 1))
    if win is None:
        return None
    fy_start = win["start"]
    # fy_end = 이 회계연도 마지막 분기 끝
    q4 = calendar.get((fy, 4))
    fy_end = q4["end"] if q4 else win["end"]
    pool = _dedup_period(facts)
    hit = _pick(pool, fy_end, start=fy_start, dur_lo=340, dur_hi=380)
    if hit is None:
        return None
    return {"val": hit["val"], "method": "annual", "fact": hit}
