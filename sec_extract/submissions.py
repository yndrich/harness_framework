"""공시 위치 탐색(submissions API) + 실제 XBRL 인스턴스 문서 URL 해석.

부문/지역/KPI 데이터는 companyfacts 에 없다(ADR-001). 이를 얻으려면 공시별
inline-XBRL 인스턴스를 파싱해야 하고(ADR-007), 그러려면 먼저 각 회계연도 10-K 의
공시 폴더 위치와 **실제 인스턴스 문서 URL** 을 찾아야 한다. 이 모듈은 그 위치
탐색만 담당한다(파싱은 다음 step).

레이어: client 위에 얹히는 데이터 취득 계층(facts/resolve 와 형제). 네트워크는
전부 주입받은 SecClient(.get_json)를 경유한다 — 직접 urllib 호출 금지(이유:
SEC 는 연락처 담긴 UA 없으면 403, IP 당 10 req/s 제한 → SecClient 가 UA·레이트
리밋·재시도·캐시를 담당).

accession 두 형태:
- 대시 포함: 0000320193-24-000123  (submissions/Provenance 표시용)
- 대시 제거: 000032019324000123    (Archives 폴더명)
Archives 경로의 {cik} 는 0 패딩 없는 정수다.
"""

from __future__ import annotations

SUBMISSIONS_URL = "https://data.sec.gov/submissions/CIK{cik10}.json"
ARCHIVES_BASE = "https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/"

# 추릴 연차 공시 form (정정본 10-K/A 포함).
_ANNUAL_FORMS = ("10-K", "10-K/A")

# 비-inline 공시 폴더에서 인스턴스(.xml)와 구분해야 하는 링크베이스 접미사.
_LINKBASE_SUFFIXES = ("_cal.xml", "_def.xml", "_lab.xml", "_pre.xml", "_ref.xml")


def select_annual_filings(submissions: dict, n_years: int = 5) -> list[dict]:
    """(순수 함수, 네트워크 없음) 파싱된 submissions JSON 에서 10-K 공시를 추린다.

    filings.recent 의 병렬 배열(accessionNumber/form/filingDate/reportDate/
    primaryDocument/isXBRL/isInlineXBRL)을 dict 행으로 zip 한다.
    - form 이 '10-K' 또는 '10-K/A' 인 것만.
    - 같은 report_date 는 최신 filing_date 1건으로 dedup(정정본 10-K/A 가 원본보다
      늦게 제출되므로 자연히 정정본이 채택된다).
    - report_date 내림차순 상위 n_years.

    각 행: {accn, accn_nodash, form, filing_date, report_date,
            primary_document, is_inline_xbrl, is_xbrl}.
    """
    recent = (submissions or {}).get("filings", {}).get("recent", {}) or {}

    def col(name: str) -> list:
        return recent.get(name, []) or []

    accns = col("accessionNumber")
    forms = col("form")
    filing_dates = col("filingDate")
    report_dates = col("reportDate")
    primary_docs = col("primaryDocument")
    is_xbrl = col("isXBRL")
    is_inline = col("isInlineXBRL")

    def at(arr: list, i: int, default=None):
        return arr[i] if i < len(arr) else default

    rows: list[dict] = []
    for i, accn in enumerate(accns):
        if at(forms, i) not in _ANNUAL_FORMS:
            continue
        accn = accn or ""
        rows.append({
            "accn": accn,
            "accn_nodash": accn.replace("-", ""),
            "form": at(forms, i),
            "filing_date": at(filing_dates, i, "") or "",
            "report_date": at(report_dates, i, "") or "",
            "primary_document": at(primary_docs, i, "") or "",
            "is_inline_xbrl": bool(at(is_inline, i, 0)),
            "is_xbrl": bool(at(is_xbrl, i, 0)),
        })

    # report_date 별로 최신 filing_date 1건만 남긴다(ISO 날짜라 문자열 비교로 충분).
    by_report: dict[str, dict] = {}
    for r in rows:
        cur = by_report.get(r["report_date"])
        if cur is None or r["filing_date"] > cur["filing_date"]:
            by_report[r["report_date"]] = r

    deduped = sorted(by_report.values(),
                     key=lambda r: r["report_date"], reverse=True)
    return deduped[:n_years]


def list_annual_filings(client, cik10: str, n_years: int = 5) -> list[dict]:
    """SecClient 로 submissions 를 받아 select_annual_filings 를 호출한다."""
    url = SUBMISSIONS_URL.format(cik10=cik10)
    return select_annual_filings(client.get_json(url), n_years)


def filing_index_url(cik: int, accn_nodash: str) -> str:
    """공시 폴더 index.json URL.

    https://www.sec.gov/Archives/edgar/data/{cik}/{accn_nodash}/index.json
    ({cik} 는 0 패딩 없는 정수, {accn_nodash} 는 대시 없는 accession).
    """
    return ARCHIVES_BASE.format(cik=cik, accn_nodash=accn_nodash) + "index.json"


def find_instance_url(client, cik: int, filing: dict) -> str:
    """공시 폴더 index.json 을 받아 실제 XBRL 인스턴스 문서 URL 을 해석한다.

    - is_inline_xbrl 이면 inline 주 문서(primary_document, .htm)를 인스턴스로 사용.
    - 아니면 index 의 파일 목록에서 별도 인스턴스(.xml)를 찾는다:
      type 이 'EX-101.INS' → '_htm.xml' → 링크베이스/스키마가 아닌 .xml 순.

    primary_document 하나에 의존하지 않고 반드시 index 로 확인한다(이유: 정정본·
    구형 공시·예외 케이스에서 primary_document 가 인스턴스가 아닐 수 있다).
    """
    accn_nodash = filing["accn_nodash"]
    base = ARCHIVES_BASE.format(cik=cik, accn_nodash=accn_nodash)
    idx = client.get_json(filing_index_url(cik, accn_nodash)) or {}
    items = idx.get("directory", {}).get("item", []) or []
    names = {it.get("name", "") for it in items}

    # inline-XBRL: 주 문서(.htm) 자체가 인스턴스다.
    if filing.get("is_inline_xbrl"):
        primary = filing.get("primary_document") or ""
        if primary and primary in names:
            return base + primary
        # index 에 primary 가 없으면 폴더의 10-K 본문 .htm 으로 폴백.
        for it in items:
            name = it.get("name", "")
            if name.endswith(".htm") and (it.get("type") or "") in _ANNUAL_FORMS:
                return base + name
        if primary:
            return base + primary
        raise ValueError(f"inline 인스턴스를 찾지 못함: {accn_nodash}")

    # 비-inline: 별도 .xml 인스턴스. primary_document 에 의존하지 않는다.
    for it in items:                                    # 1) 표준 인스턴스 타입
        if (it.get("type") or "").upper() == "EX-101.INS":
            return base + it.get("name", "")
    for it in items:                                    # 2) inline 파생 인스턴스
        name = it.get("name", "")
        if name.endswith("_htm.xml"):
            return base + name
    for it in items:                                    # 3) 링크베이스/스키마 제외 .xml
        name = it.get("name", "")
        if name.endswith(".xml") and not name.endswith(_LINKBASE_SUFFIXES):
            return base + name
    raise ValueError(f"XBRL 인스턴스를 찾지 못함: {accn_nodash}")
