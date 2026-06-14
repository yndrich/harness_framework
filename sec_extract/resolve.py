"""티커 -> CIK 변환.

SEC 의 company_tickers.json 을 받아 티커를 10자리 zero-pad CIK 로 변환한다.
다른 모든 SEC API 는 'CIK' + 10자리 0채움 형식을 요구한다.
"""

from __future__ import annotations

TICKERS_URL = "https://www.sec.gov/files/company_tickers.json"


def load_ticker_map(client, refresh: bool = False) -> dict:
    """{TICKER: {'cik': int, 'title': str}} 매핑을 반환한다."""
    data = client.get_json(TICKERS_URL, refresh=refresh)
    out = {}
    # 형태: {"0": {"cik_str": 320193, "ticker": "AAPL", "title": "Apple Inc."}, ...}
    for row in data.values():
        ticker = str(row["ticker"]).upper()
        out[ticker] = {"cik": int(row["cik_str"]), "title": row["title"]}
    return out


def resolve_ticker(client, ticker: str, refresh: bool = False) -> dict:
    """티커 문자열을 {ticker, cik, cik10, title} 로 해석한다."""
    tmap = load_ticker_map(client, refresh=refresh)
    t = ticker.upper().strip()
    if t not in tmap:
        raise KeyError(
            f"Ticker {ticker!r} not found in SEC company_tickers.json"
        )
    entry = tmap[t]
    return {
        "ticker": t,
        "cik": entry["cik"],
        "cik10": f"{entry['cik']:010d}",
        "title": entry["title"],
    }
