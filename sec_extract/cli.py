"""명령행 진입점.

사용 예:
    python -m sec_extract AAPL --years 5 -o apple.xlsx
    python -m sec_extract AAPL MSFT GOOGL --years 5 -o compare.xlsx
    python -m sec_extract AAPL --segments -o apple.xlsx   # 부문/지역/제품 분해 포함
    python -m sec_extract NVDA --raw-model --period 2025Q1 -o nvda_q.xlsx  # 특정 분기만
"""

from __future__ import annotations

import argparse
import sys

from .client import SecClient, DEFAULT_USER_AGENT
from .resolve import resolve_ticker
from .facts import CompanyFacts
from .canonical_map import STATEMENTS
from . import normalize as nz
from . import submissions as sub
from . import xbrl_instance as xi
from . import segments as seg
from . import segment_detail as sd
from . import labels as lb
from . import quarterly as qt
from .raw_model import write_raw_model_workbook, build_rows
from .excel import write_workbook


def _revenue_tags(statements):
    """분해 대상(매출) 후보 태그를 canonical_map(STATEMENTS)에서 가져온다.

    segments.build_disaggregation 는 '무엇을 분해할지'를 후보 태그로 받는다. 표준화
    매핑은 단일 출처여야 하므로(CLAUDE.md) 그 태그를 여기서 하드코딩하지 않고
    income_statement 의 revenue 항목과 공유한다.
    """
    for st in statements:
        if st["key"] == "income_statement":
            for line in st["lines"]:
                if line["key"] == "revenue":
                    return line["tags"]
    return []


def _build_segments(client, ticker, cik10, years, n_years):
    """--segments 경로: 공시별 inline-XBRL 인스턴스를 파싱해 차원 분해 테이블 생성.

    submissions(10-K 목록) → 인스턴스 URL 해석 → 파싱 → build_disaggregation.
    연도 라벨은 build_disaggregation 가 fact 의 기간 end 연도로 맞추므로(normalize 와
    동일 기준), normalize 가 만든 같은 `years` 리스트를 그대로 넘겨 제표 시트와 같은
    열에 정렬되게 한다.

    부분 결과 원칙: 한 공시/한 기업 파싱이 실패해도 그 부분만 건너뛰고 진행한다.
    실패 시 빈 dict 을 돌려줘 핵심 3대 재무제표 출력은 영향받지 않는다. 모든
    네트워크는 주입된 SecClient 경유(새 클라이언트 만들지 않음).
    """
    try:
        filings = sub.list_annual_filings(client, cik10, n_years)
    except Exception as e:  # noqa: BLE001 - 분해 실패가 핵심 경로를 죽이지 않게
        print(f"[skip] {ticker} segments: submissions 조회 실패: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return {}
    cik = int(cik10)   # Archives 경로의 cik 는 0 패딩 없는 정수
    facts = []
    for filing in filings:
        try:
            url = sub.find_instance_url(client, cik, filing)
            facts.extend(xi.parse_instance_url(client, url))
        except Exception as e:  # noqa: BLE001 - 공시 단위 부분 실패는 건너뛴다
            print(f"[skip] {ticker} {filing.get('accn')}: 인스턴스 파싱 실패: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            continue
    if not facts:
        return {}
    return seg.build_disaggregation(facts, years, _revenue_tags(STATEMENTS))


def build_company(client, ticker, n_years, refresh, with_segments=False):
    info = resolve_ticker(client, ticker, refresh=refresh)
    cf = CompanyFacts.fetch(client, info["cik10"], refresh=refresh)
    all_years = nz.available_years(cf, STATEMENTS)
    years = all_years[-n_years:] if n_years else all_years
    data = nz.normalize_company(cf, STATEMENTS, years)
    segments = {}
    if with_segments:
        segments = _build_segments(client, info["ticker"], info["cik10"],
                                   years, n_years)
    result = nz.CompanyResult(
        ticker=info["ticker"], title=info["title"], cik10=info["cik10"],
        entity=cf.entity, years=years, data=data, segments=segments,
    )
    n_flags = len(nz.collect_flags(result, STATEMENTS))
    return result, years, n_flags


def _fetch_label_map(client, ticker, cik10, with_segments):
    """공시 label linkbase 에서 concept→표시라벨 맵을 받는다(best-effort).

    Raw Data/Segment Detail 의 '항목(원본)' 열에 쓸 공시 원문 라벨. 편의 열이라
    실패는 조용히 빈 맵으로 폴백한다(핵심 출력 불변). --segments 면 10-Q 멤버 라벨
    까지 필요하므로 정기공시(10-K+10-Q)를, 아니면 최신 10-K 몇 건을 훑는다.
    """
    try:
        if with_segments:
            filings = sub.list_periodic_filings(client, cik10, n_annual=2,
                                                n_quarterly=3)
        else:
            filings = sub.list_annual_filings(client, cik10, 3)
        return lb.fetch_label_map(client, int(cik10), filings)
    except Exception as e:  # noqa: BLE001 - 라벨 취득 실패가 핵심 경로를 죽이지 않게
        print(f"[skip] {ticker} labels: 표시라벨 취득 실패: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return {}


def build_raw_company(client, ticker, n_quarters, refresh, with_segments=False,
                      period_specs=None):
    """--raw-model 경로: 분기 tidy 행 생성 (+선택적 as-reported 매출 분해).

    period_specs(예: ['2025Q1', '2024Q1:2024Q4'])가 주어지면 그 분기만 고른다
    (--quarters 의 '최근 N개' 슬라이싱 무시). 달력에 없는 분기는 select_periods
    가 ValueError 로 표면화한다.
    """
    info = resolve_ticker(client, ticker, refresh=refresh)
    cf = CompanyFacts.fetch(client, info["cik10"], refresh=refresh)
    calendar = qt.fiscal_calendar(cf, STATEMENTS)
    available = sorted(calendar.keys())
    if period_specs:
        periods = qt.select_periods(available, period_specs)
    else:
        periods = available[-n_quarters:] if n_quarters else available
    label_map = _fetch_label_map(client, info["ticker"], info["cik10"],
                                 with_segments)
    rows = build_rows(cf, STATEMENTS, periods, calendar=calendar,
                      label_map=label_map)
    n_flags = sum(len(r.get("flags", [])) for r in rows)
    seg_detail = None
    if with_segments:
        seg_detail = _build_segment_detail(
            client, info["ticker"], info["cik10"], calendar, periods, n_quarters,
            label_map=label_map)
    return info["ticker"], rows, periods, n_flags, seg_detail


def _build_segment_detail(client, ticker, cik10, calendar, periods, n_quarters,
                          label_map=None):
    """10-K+10-Q inline-XBRL 을 파싱해 as-reported 분기/연간 매출 분해를 만든다.

    부분 결과 원칙: 한 공시 파싱이 실패해도 그 부분만 건너뛴다. 전체 실패면 None.
    label_map: 멤버 표시라벨(원본 항목명) 맵 — build_as_reported 에 전달.
    """
    try:
        filings = sub.list_periodic_filings(client, cik10, n_annual=6,
                                            n_quarterly=(n_quarters or 16) + 4)
    except Exception as e:  # noqa: BLE001 - 분해 실패가 핵심 경로를 죽이지 않게
        print(f"[skip] {ticker} segment-detail: submissions 조회 실패: "
              f"{type(e).__name__}: {e}", file=sys.stderr)
        return None
    cik = int(cik10)
    facts = []
    for filing in filings:
        try:
            url = sub.find_instance_url(client, cik, filing)
            for f in xi.parse_instance_url(client, url):
                f["accn"] = filing.get("accn")
                f["filed"] = filing.get("filing_date")
                f["form"] = filing.get("form")
                facts.append(f)
        except Exception as e:  # noqa: BLE001 - 공시 단위 부분 실패는 건너뛴다
            print(f"[skip] {ticker} {filing.get('accn')}: 인스턴스 파싱 실패: "
                  f"{type(e).__name__}: {e}", file=sys.stderr)
            continue
    if not facts:
        return None
    annual_years = sorted({fy for fy, _ in periods})
    return sd.build_as_reported(facts, _revenue_tags(STATEMENTS), calendar,
                                periods, annual_years, label_map=label_map)


def main(argv=None, client=None) -> int:
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
    p.add_argument("--segments", action="store_true",
                   help="부문/지역/제품 매출 분해 시트 추가 (공시별 inline-XBRL 을 "
                        "파싱하므로 느리다; 기본 꺼짐)")
    p.add_argument("--raw-model", action="store_true",
                   help="분기 tidy Raw Data 출력 (사용자 모델 스키마 + Canonical Key)")
    p.add_argument("--quarters", type=int, default=16,
                   help="--raw-model 시 가져올 최근 분기 수 (기본 16)")
    p.add_argument("--period", nargs="+", metavar="YYYYQn", default=None,
                   help="특정 분기만 추출: 단일 2025Q1, 여러 개 2025Q1 2024Q3, "
                        "범위 2024Q1:2025Q1. --raw-model 필요; 지정 시 --quarters 무시")
    args = p.parse_args(argv)

    # --period 는 분기 출력(--raw-model)에만 의미가 있다(연간 경로는 회계연도 단위).
    if args.period and not args.raw_model:
        print("[error] --period 는 --raw-model 과 함께 써야 합니다 "
              "(분기 선택은 분기 출력에만 적용됩니다).", file=sys.stderr)
        return 2

    # client 주입 시(테스트) 그대로 공유한다 — 새 SecClient 를 만들지 않는다.
    if client is None:
        client_kwargs = {"user_agent": args.user_agent,
                         "use_cache": not args.no_cache}
        if args.cache_dir:
            client_kwargs["cache_dir"] = args.cache_dir
        client = SecClient(**client_kwargs)

    # --raw-model: 분기 tidy 출력 (사용자 모델 스키마)
    if args.raw_model:
        raw = []
        any_seg = False
        for t in args.tickers:
            try:
                ticker, rows, periods, n_flags, seg_detail = build_raw_company(
                    client, t, args.quarters, args.refresh,
                    with_segments=args.segments, period_specs=args.period)
            except KeyError as e:
                print(f"[skip] {e}", file=sys.stderr)
                continue
            except ValueError as e:   # --period 형식/범위 오류 등은 깔끔히 안내
                print(f"[error] {t}: {e}", file=sys.stderr)
                continue
            except Exception as e:  # noqa: BLE001
                print(f"[error] {t}: {type(e).__name__}: {e}", file=sys.stderr)
                continue
            raw.append((ticker, rows, periods, seg_detail))
            span = (f"{periods[0][0]}Q{periods[0][1]}–{periods[-1][0]}Q{periods[-1][1]}"
                    if periods else "no quarterly data")
            n_rows = sum(1 for r in rows if r.get("val") is not None)
            seg_note = ""
            if seg_detail:
                any_seg = True
                seg_note = (f" | 분해 {len(seg_detail['rows'])}행 "
                            f"(변경 {len(seg_detail['changes'])})")
            print(f"  {ticker}: {n_rows} rows | {len(periods)} quarters "
                  f"({span}) | review flags: {n_flags}{seg_note}")
        if not raw:
            print("처리된 기업이 없습니다.", file=sys.stderr)
            return 1
        write_raw_model_workbook(raw, args.output)
        seg_sheets = (" + Segment Detail/Reconcile/Changes" if any_seg else "")
        print(f"\n작성 완료(Raw Model): {args.output}  "
              f"(시트: Raw Data + Meta Data + Event Log + Review{seg_sheets})")
        return 0

    companies = []
    for t in args.tickers:
        try:
            result, years, n_flags = build_company(
                client, t, args.years, args.refresh,
                with_segments=args.segments)
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
    extra = ""
    if args.segments and any(getattr(c, "segments", None) for c in companies):
        extra = " + 분해(Segments/Geography/Products)"
    print(f"\n작성 완료: {args.output}  "
          f"(시트: 제표 3 + Comparison + Review + Provenance{extra})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
