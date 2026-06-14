"""XBRL 인스턴스 파서 — companyfacts 가 버리는 '차원(축/멤버)' 컨텍스트를 복원한다.

companyfacts API 는 집계값만 주고 부문/지역/제품 같은 차원 분해를 담지 않는다
(ADR-001). 그 분해는 각 공시의 XBRL 인스턴스에만 있다(ADR-007). 이 모듈은
인스턴스 문서에서 **차원 포함** 숫자 사실(fact)을 뽑는다.

대상 두 형태:
- inline-XBRL 주 문서(.htm): 값이 ``<ix:nonFraction name="us-gaap:..." ...>`` 로
  XHTML 안에 박혀 있다. scale/sign/format 으로 표시값을 정규화해야 한다.
- 비-inline 별도 인스턴스(.xml): 값이 ``<us-gaap:Revenues contextRef="...">`` 처럼
  평범한 요소다(scale/sign/format 없음). prefix 를 복원해 concept 를 보존한다.

레이어: client 위에 얹히는 데이터 취득 계층(facts/submissions 와 형제). 네트워크는
전부 주입받은 SecClient(.get_text)를 경유한다 — 직접 urllib 호출 금지(이유: SEC 는
연락처 담긴 UA 없으면 403, IP 당 10 req/s 제한 → SecClient 가 UA·레이트리밋·재시도
·캐시를 담당). 파싱은 stdlib(xml.etree.ElementTree) 만 사용한다.

정규화 규칙(중요):
- raw_text 의 서식문자(콤마·공백)를 format(ixt 변환)에 맞게 제거 후 숫자 파싱.
- value = parsed * 10**scale (scale 기본 0). sign=='-' 이면 부호 반전.
- decimals 는 '정밀도 메타데이터'일 뿐 배율이 아니다 — 곱하지 않고 기록만 한다.
- 차원 없는(primary) fact 와 차원 있는 fact 를 **모두** 보존한다. 거르지 않는다.
- 회사 고유 네임스페이스(예: aapl:) concept/멤버도 버리지 않고 그대로 보존한다.
"""

from __future__ import annotations

import html
import re
import xml.etree.ElementTree as ET
from decimal import Decimal, InvalidOperation

# inline-XBRL / XBRL 구조 네임스페이스(값 fact 가 아니라 컨텍스트·링크 등 구조).
_INLINE_NS_MARK = "inlineXBRL"   # 2008/2013 ix 네임스페이스 모두 이 문자열을 포함
_STRUCTURAL_NS = frozenset({
    "http://www.xbrl.org/2003/instance",      # xbrli (context/unit/period/entity)
    "http://xbrl.org/2006/xbrldi",            # xbrldi (explicitMember 등)
    "http://www.xbrl.org/2003/linkbase",      # link (schemaRef 등)
    "http://www.w3.org/1999/xlink",           # xlink
    "http://www.w3.org/2001/XMLSchema-instance",  # xsi
})


# ---- 네트워크 경계 ----------------------------------------------------
def parse_instance_url(client, url) -> list[dict]:
    """SecClient 로 인스턴스 문서(텍스트)를 받아 parse_instance 를 호출한다.

    문서가 수 MB(XHTML)일 수 있으므로 텍스트 취득과 파싱을 분리한다. 네트워크는
    반드시 client.get_text 경유 — 직접 urllib 호출 금지.
    """
    return parse_instance(client.get_text(url))


# ---- 순수 파서(네트워크 없음) ----------------------------------------
def parse_instance(text: str) -> list[dict]:
    """XBRL 인스턴스 텍스트에서 숫자 fact 리스트를 반환한다.

    각 fact: {concept, value, raw_text, unit, decimals, context_ref,
              dims: {axis_qname: member_qname}, start, end, instant}.

    먼저 ElementTree 로 파싱한다. 인스턴스가 깨진 XHTML(미정의 엔티티 등)이라
    ET 가 실패하면 정규식 기반의 관대한 추출 경로로 폴백한다(실패해도 부분 결과를
    내야 하므로).
    """
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return _parse_lenient(text)

    prefixes = _build_prefix_map(text)
    contexts = _collect_contexts(root)
    facts: list[dict] = []
    for el in root.iter():
        ns, ln = _ns(el.tag), _local(el.tag)
        if ln == "nonFraction" and _INLINE_NS_MARK in ns:
            # inline: <ix:nonFraction name="us-gaap:..." scale=.. sign=.. format=..>
            f = _fact_from_ix(el, contexts)
        elif (_INLINE_NS_MARK not in ns and ns not in _STRUCTURAL_NS
              and el.get("contextRef")):
            # 비-inline 별도 인스턴스의 평범한 요소 fact.
            f = _fact_from_plain(el, contexts, prefixes)
        else:
            continue
        if f is not None:
            facts.append(f)
    return facts


# ---- ET 경로 헬퍼 -----------------------------------------------------
def _local(tag: str) -> str:
    return tag.split("}", 1)[1] if tag.startswith("{") else tag


def _ns(tag: str) -> str:
    return tag[1:].split("}", 1)[0] if tag.startswith("{") else ""


def _collect_contexts(root) -> dict:
    """id → {dims, start, end, instant} 맵. (xbrli:context 들)"""
    out: dict[str, dict] = {}
    for el in root.iter():
        if _local(el.tag) == "context":
            cid = el.get("id")
            if cid:
                out[cid] = _parse_context(el)
    return out


def _parse_context(ctx_el) -> dict:
    dims: dict[str, str] = {}
    start = end = instant = None
    for el in ctx_el.iter():
        ln = _local(el.tag)
        if ln == "explicitMember":
            axis = el.get("dimension")
            if axis:
                dims[axis] = (el.text or "").strip()
        elif ln == "startDate":
            start = (el.text or "").strip() or None
        elif ln == "endDate":
            end = (el.text or "").strip() or None
        elif ln == "instant":
            instant = (el.text or "").strip() or None
    return {"dims": dims, "start": start, "end": end, "instant": instant}


def _text_content(el) -> str:
    return "".join(el.itertext()).strip()


def _fact_from_ix(el, contexts: dict) -> dict | None:
    name = el.get("name")
    if not name:
        return None
    ctx = contexts.get(el.get("contextRef"), {})
    raw = _text_content(el)
    return {
        "concept": name,
        "value": _normalize_value(raw, _int_attr(el.get("scale"), 0),
                                  el.get("sign"), el.get("format")),
        "raw_text": raw,
        "unit": el.get("unitRef"),
        "decimals": el.get("decimals"),
        "context_ref": el.get("contextRef"),
        "dims": dict(ctx.get("dims", {})),
        "start": ctx.get("start"),
        "end": ctx.get("end"),
        "instant": ctx.get("instant"),
    }


def _fact_from_plain(el, contexts: dict, prefixes: dict) -> dict | None:
    # 평범한 인스턴스 요소는 scale/sign/format 이 없다(값이 이미 완전). prefix 복원.
    ctx = contexts.get(el.get("contextRef"), {})
    raw = _text_content(el)
    return {
        "concept": _qname(el.tag, prefixes),
        "value": _normalize_value(raw, 0, None, None),
        "raw_text": raw,
        "unit": el.get("unitRef"),
        "decimals": el.get("decimals"),
        "context_ref": el.get("contextRef"),
        "dims": dict(ctx.get("dims", {})),
        "start": ctx.get("start"),
        "end": ctx.get("end"),
        "instant": ctx.get("instant"),
    }


# ET 는 요소 태그의 prefix 를 {uri}local 로 풀어버린다. 문서의 xmlns 선언으로
# uri→prefix 를 복원해 'us-gaap:Revenues' 같은 qname 을 되살린다(첫 선언 우선).
_XMLNS_RE = re.compile(r'xmlns:([\w.\-]+)\s*=\s*"([^"]+)"')


def _build_prefix_map(text: str) -> dict:
    out: dict[str, str] = {}
    for prefix, uri in _XMLNS_RE.findall(text):
        out.setdefault(uri, prefix)
    return out


def _qname(tag: str, prefixes: dict) -> str:
    if tag.startswith("{"):
        uri, local = tag[1:].split("}", 1)
        prefix = prefixes.get(uri)
        return f"{prefix}:{local}" if prefix else local
    return tag


# ---- 숫자 정규화 ------------------------------------------------------
def _int_attr(value, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_number(raw: str, fmt: str | None) -> str | None:
    """서식문자 제거. ixt format 에 따라 천단위/소수점 구분문자를 해석한다.

    - num-comma-decimal 계열: 점/공백 = 천단위, 콤마 = 소수점.
    - 그 외(num-dot-decimal 기본): 콤마/공백 = 천단위, 점 = 소수점.
    """
    s = (raw or "").strip()
    if not s:
        return None
    fmt = (fmt or "").lower()
    # 천단위 공백 서식문자 제거: 일반/비분리(\u00a0=&nbsp;)/얇은(\u2009,\u202f) 공백·탭.
    for _ws in (" ", "\u00a0", "\u2009", "\u202f", "\t"):
        s = s.replace(_ws, "")
    if "comma-decimal" in fmt or "commadecimal" in fmt:
        s = s.replace(".", "").replace(",", ".")
    else:
        s = s.replace(",", "")
    return s if s not in ("", "-", ".", "+") else None


def _normalize_value(raw: str, scale: int, sign: str | None, fmt: str | None):
    """표시값 → 실제값. value = parsed * 10**scale, sign=='-' 면 부호 반전.

    Decimal 로 계산해 부동소수 오차를 피하고, 정수면 int 로 좁힌다(decimals 는
    여기서 쓰지 않는다 — 배율이 아니라 정밀도 메타데이터일 뿐).
    """
    cleaned = _clean_number(raw, fmt)
    if cleaned is None:
        return None
    try:
        num = Decimal(cleaned)
    except InvalidOperation:
        return None
    num *= Decimal(10) ** scale
    if sign == "-":
        num = -num
    return int(num) if num == num.to_integral_value() else float(num)


# ---- 관대한 폴백(ET 실패 시) ------------------------------------------
# 깨진 XHTML(미정의 엔티티·비정형 마크업)에서도 ix:nonFraction 과 컨텍스트를
# 정규식으로 긁는다. prefix 는 (어차피 name 속성에 문자열로 박혀 있으므로) 불필요.
_NONFRACTION_RE = re.compile(
    r"<(?:[\w.\-]+:)?nonFraction\b(?P<attrs>[^>]*)>"
    r"(?P<inner>.*?)</(?:[\w.\-]+:)?nonFraction>", re.DOTALL)
_CONTEXT_RE = re.compile(
    r"<(?:[\w.\-]+:)?context\b(?P<attrs>[^>]*)>"
    r"(?P<inner>.*?)</(?:[\w.\-]+:)?context>", re.DOTALL)
_MEMBER_RE = re.compile(
    r'<(?:[\w.\-]+:)?explicitMember\b[^>]*\bdimension="(?P<axis>[^"]+)"[^>]*>'
    r"(?P<member>.*?)</(?:[\w.\-]+:)?explicitMember>", re.DOTALL)
_START_RE = re.compile(
    r"<(?:[\w.\-]+:)?startDate\b[^>]*>(.*?)</(?:[\w.\-]+:)?startDate>", re.DOTALL)
_END_RE = re.compile(
    r"<(?:[\w.\-]+:)?endDate\b[^>]*>(.*?)</(?:[\w.\-]+:)?endDate>", re.DOTALL)
_INSTANT_RE = re.compile(
    r"<(?:[\w.\-]+:)?instant\b[^>]*>(.*?)</(?:[\w.\-]+:)?instant>", re.DOTALL)
_ATTR_RE = re.compile(r'([\w:.\-]+)\s*=\s*"([^"]*)"')
_TAG_RE = re.compile(r"<[^>]+>")


def _parse_attrs(s: str) -> dict:
    return {k: html.unescape(v) for k, v in _ATTR_RE.findall(s or "")}


def _strip_tags(s: str) -> str:
    return html.unescape(_TAG_RE.sub("", s or "")).strip()


def _lenient_contexts(text: str) -> dict:
    out: dict[str, dict] = {}
    for m in _CONTEXT_RE.finditer(text):
        attrs = _parse_attrs(m.group("attrs"))
        cid = attrs.get("id")
        if not cid:
            continue
        inner = m.group("inner")
        dims = {mm.group("axis"): _strip_tags(mm.group("member"))
                for mm in _MEMBER_RE.finditer(inner)}

        def first(rx, blk=inner):
            mm = rx.search(blk)
            return (_strip_tags(mm.group(1)) or None) if mm else None

        out[cid] = {"dims": dims, "start": first(_START_RE),
                    "end": first(_END_RE), "instant": first(_INSTANT_RE)}
    return out


def _parse_lenient(text: str) -> list[dict]:
    contexts = _lenient_contexts(text)
    facts: list[dict] = []
    for m in _NONFRACTION_RE.finditer(text):
        attrs = _parse_attrs(m.group("attrs"))
        name = attrs.get("name")
        if not name:
            continue
        ctx = contexts.get(attrs.get("contextRef"), {})
        raw = _strip_tags(m.group("inner"))
        facts.append({
            "concept": name,
            "value": _normalize_value(raw, _int_attr(attrs.get("scale"), 0),
                                      attrs.get("sign"), attrs.get("format")),
            "raw_text": raw,
            "unit": attrs.get("unitRef"),
            "decimals": attrs.get("decimals"),
            "context_ref": attrs.get("contextRef"),
            "dims": dict(ctx.get("dims", {})),
            "start": ctx.get("start"),
            "end": ctx.get("end"),
            "instant": ctx.get("instant"),
        })
    return facts
