"""차원(부문/지역/제품) 분해 집계 + 검토 플래그.

xbrl_instance 가 뽑은 '차원 포함 fact'(축/멤버)를 표준 그룹으로 묶는다. 매핑 지식
(어느 축이 어느 그룹인지, 무엇이 표준 네임스페이스인지, 무엇이 조정 멤버인지)은
전부 canonical_map.py 에 있다 — 이 모듈은 축 문자열을 하드코딩하지 않는다(CRITICAL:
표준화 매핑 단일 출처).

자동 표준화가 불확실한 것은 조용히 추측하지 않고 검토(REVIEW)로 보낸다(ADR-006):
- 미인식 축(KNOWN_AXES 에 없음)      -> REVIEW: unknown-axis (어떤 그룹에도 넣지 않음)
- 회사 고유 네임스페이스 멤버/개념    -> REVIEW: custom-tag (축은 표준이면 그룹엔 보존)

재무 정합성은 정보성으로 'reconcile' 에 병기한다(같은 (group, year)의 멤버 합 vs
무차원 총계 = computed_sum/reported_total/diff). 사업부간 제거·Corporate/Other·조정
항목 때문에 합≠총계는 정상이라, '조정 멤버 부재 + |diff|/total > 허용오차'일 때만
REVIEW: does-not-reconcile 로 띄운다(전부 띄우면 거짓양성 폭탄).

플래그는 normalize.py 와 같은 (TYPE, detail) 튜플 관례를 따른다. 연도 라벨도
normalize 와 동일하게 기간 end(시점 개념이면 instant)의 연도를 쓴다. 입력 fact 는
연간 공시(10-K) 인스턴스에서 온다고 가정하되, 비-연간 기간(분기 등)은 합산에서
배제해 정합성 거짓양성을 막는다(연간 창은 normalize 와 동일).
"""

from __future__ import annotations

from datetime import date

from .canonical_map import (
    KNOWN_AXES,
    RECONCILING_MEMBER_HINTS,
    STANDARD_PREFIXES,
)

RECONCILE_TOL = 0.02   # |diff|/total 이 2% 초과 + 조정멤버 부재일 때만 플래그
_ANNUAL_MIN_DAYS = 340
_ANNUAL_MAX_DAYS = 380


def _local(qname: str) -> str:
    return qname.split(":", 1)[1] if ":" in qname else qname


def _prefix(qname: str) -> str:
    return qname.split(":", 1)[0] if ":" in qname else ""


def _is_custom(qname: str) -> bool:
    """회사 고유(비표준) 네임스페이스인가 — prefix 가 표준 목록에 없으면 True."""
    p = _prefix(qname)
    return bool(p) and p not in STANDARD_PREFIXES


def _is_reconciling_member(member: str) -> bool:
    low = member.lower()
    return any(h in low for h in RECONCILING_MEMBER_HINTS)


def _year_of(f: dict):
    d = f.get("end") or f.get("instant")
    if not d:
        return None
    try:
        return int(str(d)[:4])
    except ValueError:
        return None


def _is_annual(f: dict) -> bool:
    """duration fact 가 연간(약 1년)인가. 기간정보 없으면(instant 등) 통과."""
    start, end = f.get("start"), f.get("end")
    if not start or not end:
        return True
    try:
        days = (date.fromisoformat(end) - date.fromisoformat(start)).days
    except ValueError:
        return True
    return _ANNUAL_MIN_DAYS <= days <= _ANNUAL_MAX_DAYS


def build_disaggregation(facts: list[dict], years: list[int],
                         concept_tags: list[str]) -> dict:
    """concept_tags 에 해당하는 차원 fact 를 표준 그룹으로 집계한다.

    반환: {group: {member_label: {year: value}}} 형태의 group 키(데이터 있는 것만)에
    더해
      - 'flags'   : 검토 (TYPE, detail) 튜플 목록 (unknown-axis / custom-tag /
                    does-not-reconcile). TYPE 은 항상 'REVIEW'.
      - 'reconcile': (group, year)별 {group, year, computed_sum, reported_total,
                    diff} 정보성 목록.
    자세한 규칙은 모듈 docstring 참조.
    """
    tagset = set(concept_tags)
    yearset = set(years)
    # 후보 태그 우선순위(작을수록 우선). 같은 (group, member, year)/연도 총계가 여러
    # 후보 태그로 잡히면 우선순위 높은 값을 채택한다.
    priority = {t: i for i, t in enumerate(concept_tags)}
    rank = len(concept_tags)

    members: dict = {}   # (group, member, year) -> (priority, value)
    totals: dict = {}    # year -> (priority, value)  (무차원 총계)
    flags: list = []
    reconcile: list = []
    seen_detail: set = set()

    def add_flag(detail: str) -> None:
        if detail not in seen_detail:
            seen_detail.add(detail)
            flags.append(("REVIEW", detail))

    for f in facts:
        local = _local(f.get("concept") or "")
        if local not in tagset:
            continue
        year = _year_of(f)
        if year is None or year not in yearset:
            continue
        if not _is_annual(f):
            continue
        val = f.get("value")
        prio = priority.get(local, rank)
        dims = f.get("dims") or {}

        if not dims:
            # 무차원(primary) 총계 — 우선순위 높은 후보 태그 값 채택.
            if val is None:
                continue
            cur = totals.get(year)
            if cur is None or prio < cur[0]:
                totals[year] = (prio, val)
            continue

        # 단일 축만 그룹 집계한다(교차표=다축 fact 는 합산 중복이라 제외).
        if len(dims) != 1:
            continue
        axis, member = next(iter(dims.items()))

        if axis not in KNOWN_AXES:
            add_flag(f"unknown-axis: {axis}")   # 임의 그룹에 넣지 않는다.
            continue

        group = KNOWN_AXES[axis]
        # 회사 고유 멤버/개념은 검토로(축은 표준이므로 그룹에는 보존).
        if _is_custom(member):
            add_flag(f"custom-tag: {member}")
        concept = f.get("concept") or ""
        if _is_custom(concept):
            add_flag(f"custom-tag: {concept}")

        if val is None:
            continue
        key = (group, member, year)
        cur = members.get(key)
        if cur is None or prio < cur[0]:
            members[key] = (prio, val)

    # 중첩 dict + (group, year) 묶음 재구성.
    out: dict = {}
    grouped: dict = {}
    for (group, member, year), (_p, val) in members.items():
        out.setdefault(group, {}).setdefault(member, {})[year] = val
        grouped.setdefault((group, year), {})[member] = val

    total_by_year = {y: v for y, (_p, v) in totals.items()}

    # 정합성: (group, year)별 멤버 합 vs 무차원 총계(정보성). 플래그는 조건부.
    for gy in sorted(grouped):
        group, year = gy
        mem = grouped[gy]
        computed = sum(mem.values())
        total = total_by_year.get(year)
        if total is None:
            continue   # 비교할 총계가 없으면 정보성 항목도 의미 없음.
        diff = computed - total
        reconcile.append({
            "group": group, "year": year,
            "computed_sum": computed, "reported_total": total, "diff": diff,
        })
        has_adjust = any(_is_reconciling_member(m) for m in mem)
        denom = abs(total)
        if not has_adjust and denom and abs(diff) / denom > RECONCILE_TOL:
            add_flag(
                f"does-not-reconcile: {group} {year} "
                f"sum={computed:,.0f} vs total={total:,.0f} (diff {diff:,.0f})"
            )

    out["flags"] = flags
    out["reconcile"] = reconcile
    return out
