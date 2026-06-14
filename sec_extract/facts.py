"""companyfacts API 래퍼.

data.sec.gov/api/xbrl/companyfacts/CIK##########.json 한 번 호출이면 한 기업의
모든 us-gaap XBRL 사실(fact)을 연도/분기별로 전부 받는다. 별도 XBRL 파싱 불필요.

주의(설계상 한계): companyfacts 는 '차원(dimension)' 정보를 담지 않는다.
즉 사업부문별/지역별 매출 같은 분해 데이터는 여기 없다(다음 단계에서
inline-XBRL 인스턴스를 파싱해야 함). 3대 재무제표의 집계값은 모두 여기 있다.

각 fact 필드: accn(공시 접수번호), fy(보고 회계연도), fp(회계기간), form(10-K/10-Q),
filed(제출일), start/end(실제 보고 기간), val(값), frame(달력 프레임, 있을 때만).
"""

from __future__ import annotations

COMPANYFACTS_URL = "https://data.sec.gov/api/xbrl/companyfacts/CIK{cik10}.json"


class CompanyFacts:
    def __init__(self, data: dict) -> None:
        self.data = data
        self.entity = data.get("entityName")
        self.cik = data.get("cik")
        self._usgaap = data.get("facts", {}).get("us-gaap", {})

    @classmethod
    def fetch(cls, client, cik10: str, refresh: bool = False) -> "CompanyFacts":
        url = COMPANYFACTS_URL.format(cik10=cik10)
        return cls(client.get_json(url, refresh=refresh))

    def has_tag(self, tag: str) -> bool:
        return tag in self._usgaap

    def units(self, tag: str) -> dict:
        node = self._usgaap.get(tag)
        return node.get("units", {}) if node else {}

    def facts_for(self, tag: str, unit: str | None = None) -> list:
        """한 태그의 정규화된 fact 리스트 (지정 단위, 없으면 가장 많은 단위)."""
        units = self.units(tag)
        if not units:
            return []
        if unit is None or unit not in units:
            unit = max(units, key=lambda u: len(units[u]))
        out = []
        for f in units.get(unit, []):
            out.append({
                "val": f.get("val"),
                "accn": f.get("accn"),
                "fy": f.get("fy"),
                "fp": f.get("fp"),
                "form": f.get("form"),
                "filed": f.get("filed"),
                "start": f.get("start"),
                "end": f.get("end"),
                "frame": f.get("frame"),
                "unit": unit,
                "tag": tag,
            })
        return out
