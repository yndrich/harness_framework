"""공시의 label linkbase(`*_lab.xml`) 파서 — '재무제표에 실제 표시되는 이름' 취득.

companyfacts·XBRL 인스턴스는 us-gaap 태그(예: RevenueFromContractWithCustomer
ExcludingAssessedTax)만 준다. 하지만 사람이 재무제표에서 읽는 이름은 발행사가
붙인 표시 라벨(예: Apple "Net sales", NVDA "Data Center")이고, 그건 각 공시의
label linkbase 에만 있다. 이 모듈은 그 라벨을 concept QName → 표시라벨로 복원한다.

용도: Raw Data / Segment Detail 의 '항목(원본)' 열 — 표준화한 한글 항목과 별개로,
공시 원문 라벨을 나란히 보여줘 사람이 실제 재무제표와 매칭하기 쉽게 한다.

레이어: client 위 데이터 취득 계층(facts/submissions/xbrl_instance 와 형제). 네트
워크는 전부 주입받은 SecClient(.get_json/.get_text) 경유 — 직접 urllib 금지(SEC 는
연락처 담긴 UA 없으면 403, IP 당 10 req/s → SecClient 가 UA·레이트리밋·재시도·캐시).
파싱은 stdlib(xml.etree.ElementTree)만 사용한다. 부분 실패는 조용히 빈 결과로 —
'원본 라벨'은 편의 열이라 없어도 핵심 출력을 죽이지 않는다(공란 폴백).

label linkbase 구조(XLink extended link):
    <link:loc   xlink:href="...xsd#us-gaap_Revenues" xlink:label="loc_1"/>
    <link:labelArc xlink:from="loc_1" xlink:to="lab_1"/>
    <link:label xlink:label="lab_1"
                xlink:role="http://www.xbrl.org/2003/role/label">Net sales</link:label>
loc(개념 위치) → labelArc(연결) → label(텍스트) 로 체인을 따라간다. href 프래그먼트
`us-gaap_Revenues` 는 `us-gaap:Revenues` 로 되살린다(첫 '_' → ':').
"""

from __future__ import annotations

import re
import xml.etree.ElementTree as ET

from .submissions import ARCHIVES_BASE, filing_index_url

# 표시 라벨 역할 우선순위(작을수록 우선). standard > terse > verbose > 기타.
# documentation(개념 정의문)·negated(부호반전) 등은 '표시 이름'이 아니므로 뒤로.
_ROLE_PRIORITY = {
    "http://www.xbrl.org/2003/role/label": 0,
    "http://www.xbrl.org/2003/role/terseLabel": 1,
    "http://www.xbrl.org/2003/role/verboseLabel": 2,
}
_LABEL_LINKBASE_SUFFIX = "_lab.xml"


# ---- 순수 파서(네트워크 없음) ----------------------------------------
def parse_label_linkbase(text: str) -> dict:
    """label linkbase 텍스트 → {concept QName: 표시라벨}. 실패 시 {}.

    한 개념에 여러 역할의 라벨이 있으면 _ROLE_PRIORITY 로 하나를 고른다(영문 우선).
    documentation 역할만 있는 개념은 표시 이름이 없으므로 제외한다.
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return {}

    loc_concept: dict[str, str] = {}     # 로케이터 id → concept QName
    label_res: dict[str, list] = {}      # 리소스 id → [(role, lang, text), ...]
    arcs: list[tuple] = []               # (로케이터 id, 리소스 id)

    for el in root.iter():
        ln = _local(el.tag)
        if ln == "loc":
            lab = _xlink(el, "label")
            concept = _concept_from_href(_xlink(el, "href") or "")
            if lab and concept:
                loc_concept[lab] = concept
        elif ln == "labelArc":
            frm, to = _xlink(el, "from"), _xlink(el, "to")
            if frm and to:
                arcs.append((frm, to))
        elif ln == "label":
            lab = _xlink(el, "label")
            text_ = (el.text or "").strip()
            if lab and text_:
                label_res.setdefault(lab, []).append(
                    (_xlink(el, "role") or "", _xml_lang(el), text_))

    # concept → 후보 라벨 모으기(여러 arc/역할) → 역할 우선순위로 하나 선택.
    cands: dict[str, list] = {}
    for frm, to in arcs:
        concept = loc_concept.get(frm)
        if concept:
            cands.setdefault(concept, []).extend(label_res.get(to, []))
    out: dict[str, str] = {}
    for concept, lst in cands.items():
        best = _best_label(lst)
        if best is not None:
            out[concept] = _clean_label(best)
    return out


# 차원 멤버/도메인/축의 표준 라벨은 " [Member]"/" [Domain]"/" [Axis]" 등 역할
# 접미사가 붙는다(예: "Data Center [Member]"). 렌더링된 재무제표엔 안 나오므로
# 표시용으론 벗긴다(끝의 대괄호 한 덩어리).
_ROLE_SUFFIX_RE = re.compile(r"\s*\[[^\]]+\]\s*$")


def _clean_label(text: str) -> str:
    return _ROLE_SUFFIX_RE.sub("", text).strip() or text


def _best_label(cands: list):
    """[(role, lang, text)] 중 표시 이름으로 최적 텍스트. 없으면 None."""
    best_text, best_score = None, None
    for role, lang, text_ in cands:
        sc = _score(role, lang)
        if sc[0] >= 99:            # documentation 등 표시 이름 아님
            continue
        if best_score is None or sc < best_score:
            best_text, best_score = text_, sc
    return best_text


def _score(role: str, lang: str) -> tuple:
    role = role or ""
    base = 99 if "documentation" in role else _ROLE_PRIORITY.get(role, 5)
    lang_pen = 0 if (lang or "").lower().startswith("en") else 1
    return (base, lang_pen)


def label_for(label_map: dict, concept: str) -> str:
    """concept(태그 또는 멤버 QName)의 표시 라벨. 없으면 "".

    canonical_map 의 태그는 prefix 없는 local-name(예: Revenues)이고 멤버는 QName
    (예: nvda:DataCenterMember)이다. 둘 다 매칭되게: QName 직접 → us-gaap/srt/dei
    prefix 보강 → local-name 스캔 순으로 찾는다.
    """
    if not concept:
        return ""
    if concept in label_map:
        return label_map[concept]
    if ":" in concept:
        local = concept.split(":", 1)[1]
    else:
        local = concept
        for pfx in ("us-gaap", "srt", "dei"):
            hit = label_map.get(f"{pfx}:{local}")
            if hit:
                return hit
    for k, v in label_map.items():
        if k.split(":", 1)[-1] == local:
            return v
    return ""


# ---- 네트워크 경계 ----------------------------------------------------
def find_label_linkbase_url(client, cik: int, filing: dict) -> str | None:
    """공시 폴더 index.json 에서 label linkbase(`*_lab.xml`) URL. 없으면 None."""
    accn_nodash = filing["accn_nodash"]
    base = ARCHIVES_BASE.format(cik=cik, accn_nodash=accn_nodash)
    idx = client.get_json(filing_index_url(cik, accn_nodash)) or {}
    items = idx.get("directory", {}).get("item", []) or []
    for it in items:
        name = it.get("name", "") or ""
        if name.endswith(_LABEL_LINKBASE_SUFFIX):
            return base + name
    return None


def fetch_label_map(client, cik: int, filings: list, max_filings: int = 3) -> dict:
    """공시들(최신순)의 label linkbase 를 받아 concept→라벨 맵으로 병합한다.

    최신 라벨 우선(먼저 채운 값 유지). 네트워크·파싱 실패는 공시 단위로 건너뛴다
    (부분 결과 원칙). max_filings 개 성공 취득하면 멈춘다(비용 상한).
    """
    merged: dict = {}
    used = 0
    for filing in filings:
        if used >= max_filings:
            break
        try:
            url = find_label_linkbase_url(client, cik, filing)
            if not url:
                continue
            m = parse_label_linkbase(client.get_text(url))
        except Exception:  # noqa: BLE001 - 편의 열이라 실패는 조용히 공란 폴백
            continue
        if not m:
            continue
        used += 1
        for k, v in m.items():
            merged.setdefault(k, v)   # 최신(먼저 온) 공시 라벨 우선
    return merged


# ---- helpers ----------------------------------------------------------
_XLINK_NS = "http://www.w3.org/1999/xlink"
_XML_NS = "http://www.w3.org/XML/1998/namespace"


def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _xlink(el, name: str):
    """xlink:{name} 속성. 네임스페이스 유무 모두 허용."""
    v = el.get(f"{{{_XLINK_NS}}}{name}")
    return v if v is not None else el.get(name)


def _xml_lang(el):
    return el.get(f"{{{_XML_NS}}}lang") or el.get("lang")


def _concept_from_href(href: str) -> str | None:
    """href 프래그먼트(...xsd#us-gaap_Revenues) → concept QName(us-gaap:Revenues)."""
    if "#" not in href:
        return None
    frag = href.split("#", 1)[1]
    if not frag:
        return None
    # 프래그먼트는 `{prefix}_{LocalName}`. 첫 '_' 만 ':' 로(local-name 엔 '_' 없음).
    return frag.replace("_", ":", 1) if "_" in frag else frag
