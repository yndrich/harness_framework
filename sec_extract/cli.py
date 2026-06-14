"""명령행 진입점.

사용 예:
    python -m sec_extract AAPL --years 5 -o apple.xlsx
    python -m sec_extract AAPL MSFT GOOGL --years 5 -o compare.xlsx
"""

from __future__ import annotations

import argparse
import sys

from .client import SecClient, DEFAULT_USER_AGENT
from .resolve import resolve_ticker
from .facts import CompanyFacts
from .canonical_map import STATEMENTS
from . import normalize as nz
from .excel import write_workbook


def build_company(client, ticker, n_years, refresh):
    info = resolve_ticker(client, ticker, refresh=refresh)
    cf = CompanyFacts.fetch(client, info["cik10"], refresh=refresh)
    all_years = nz.available_years(cf, STATEMENTS)
    years = all_years[-n_years:] if n_years else all_years
    data = nz.normalize_company(cf, STATEMENTS, years)
    result = nz.CompanyResult(
        ticker=info["ticker"], title=info["title"], cik10=info["cik10"],
        entity=cf.entity, years=years, data=data,
    )
    n_flags = len(nz.collect_flags(result, STATEMENTS))
    return result, years, n_flags


def main(argv=None) -> int:
    p = argparse.ArgumentParser(
        prog="sec_extract",
        description="SEC EDGAR 10-K/10-Q 재무정보를 표준화하여 엑셀로 추출",
    )
    p.add_argument("tickers", nargs="+", help="티커 (예: AAPL MSFT)")
    p.add_argument("-y", "--years", type=int, default=5,
                   help="가져올 최근 회계연도 수 (기본 5)")
    p.add_argument("-o", "--output", default="sec_financials.xlsx",
                   help="출력 .xlsx 경로")
    p.add_argument("--user-agent", default=DEFAULT_USER_AGENT,
                   help="SEC User-Agent (연락 이메일 포함 필수)")
    p.add_argument("--cache-dir", default=None, help="응답 캐시 디렉터리")
    p.add_argument("--refresh", action="store_true",
                   help="캐시 무시하고 새로 받기")
    p.add_argument("--no-cache", action="store_true", help="캐시 사용 안 함")
    args = p.parse_args(argv)

    client_kwargs = {"user_agent": args.user_agent, "use_cache": not args.no_cache}
    if args.cache_dir:
        client_kwargs["cache_dir"] = args.cache_dir
    client = SecClient(**client_kwargs)

    companies = []
    for t in args.tickers:
        try:
            result, years, n_flags = build_company(
                client, t, args.years, args.refresh)
        except KeyError as e:
            print(f"[skip] {e}", file=sys.stderr)
            continue
        except Exception as e:  # noqa: BLE001 - CLI 친화적 오류 출력
            print(f"[error] {t}: {type(e).__name__}: {e}", file=sys.stderr)
            continue
        companies.append(result)
        yr = f"{years[0]}–{years[-1]}" if years else "no annual data"
        print(f"  {result.ticker}: {result.title} | years {yr} | "
              f"review flags: {n_flags}")

    if not companies:
        print("처리된 기업이 없습니다.", file=sys.stderr)
        return 1

    write_workbook(companies, STATEMENTS, args.output)
    print(f"\n작성 완료: {args.output}  "
          f"(시트: 제표 3 + Comparison + Review + Provenance)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
