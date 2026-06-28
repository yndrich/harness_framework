"""표준화(canonical) 매핑 레이어 — 이 파일이 '사람이 관리하는' 핵심이다.

같은 경제적 개념이라도 기업/연도마다 us-gaap 태그가 다르다.
(예: 매출 = RevenueFromContractWithCustomerExcludingAssessedTax(ASC 606 이후)
 / Revenues / SalesRevenueNet(구) ...)

각 표준 항목(line)은 후보 태그를 '우선순위 순서'로 가진다. 정규화 단계는
연도마다 위에서부터 첫 번째로 값이 있는 태그를 사용한다. 따라서 시간이 지나며
태그가 바뀌어도(추가/삭제/개명) 자동으로 흡수된다.

새 기업을 다루다 태그가 안 잡히면(검토 시트의 GAP 플래그) 여기에 후보를
추가하면 된다. period_type:
    duration = 기간 개념(손익계산서/현금흐름표) — start~end 가 약 1년
    instant  = 시점 개념(재무상태표) — 회계연도 말 잔액
"""

from __future__ import annotations

MONEY = "#,##0"
SHARES = "#,##0"
PER_SHARE = "#,##0.00"

STATEMENTS = [
    {
        "key": "income_statement",
        "label": "Income Statement",
        "period_type": "duration",
        "lines": [
            {"key": "revenue", "label": "Revenue", "tags": [
                "RevenueFromContractWithCustomerExcludingAssessedTax",
                "Revenues",
                "RevenueFromContractWithCustomerIncludingAssessedTax",
                "SalesRevenueNet",
                "SalesRevenueGoodsNet",
            ]},
            {"key": "cost_of_revenue", "label": "Cost of Revenue", "tags": [
                "CostOfRevenue",
                "CostOfGoodsAndServicesSold",
                "CostOfGoodsSold",
            ]},
            {"key": "gross_profit", "label": "Gross Profit", "tags": [
                "GrossProfit",
            ]},
            {"key": "rd_expense", "label": "R&D Expense", "tags": [
                "ResearchAndDevelopmentExpense",
            ]},
            {"key": "sga_expense", "label": "SG&A Expense", "tags": [
                "SellingGeneralAndAdministrativeExpense",
                "GeneralAndAdministrativeExpense",
            ]},
            {"key": "operating_expenses", "label": "Operating Expenses", "tags": [
                "OperatingExpenses",
                "CostsAndExpenses",
            ]},
            {"key": "operating_income", "label": "Operating Income", "tags": [
                "OperatingIncomeLoss",
            ]},
            {"key": "interest_expense", "label": "Interest Expense", "tags": [
                "InterestExpense",
                "InterestExpenseNonoperating",
                "InterestExpenseDebt",
            ]},
            {"key": "interest_income", "label": "Interest Income", "tags": [
                "InvestmentIncomeInterest",
                "InterestAndDividendIncomeOperating",
                "InterestIncomeOther",
                # 거래소/핀테크(예: COIN)는 이자수익을 영업수익으로 분류 → 폴백
                "InterestIncomeOperating",
            ]},
            {"key": "other_income", "label": "Other Income/Expense", "tags": [
                # 이자이익/이자비용을 별도 라인으로 분리하므로 '기타'는 이자를 제외한
                # OtherNonoperatingIncomeExpense 만 쓴다. NonoperatingIncomeExpense(총
                # 영업외손익)는 이자를 포함해 이중계상이 되고 매분기 AMBIGUOUS 노이즈를
                # 유발하므로 후보에서 제외.
                "OtherNonoperatingIncomeExpense",
            ]},
            {"key": "pretax_income", "label": "Pretax Income", "tags": [
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
            ]},
            {"key": "income_tax", "label": "Income Tax Expense", "tags": [
                "IncomeTaxExpenseBenefit",
            ]},
            {"key": "net_income", "label": "Net Income", "tags": [
                "NetIncomeLoss",
                "ProfitLoss",
            ]},
            {"key": "eps_basic", "label": "EPS (Basic)", "fmt": PER_SHARE,
             "unit": "USD/shares", "tags": ["EarningsPerShareBasic"]},
            {"key": "eps_diluted", "label": "EPS (Diluted)", "fmt": PER_SHARE,
             "unit": "USD/shares", "tags": ["EarningsPerShareDiluted"]},
            {"key": "shares_basic", "label": "Wtd Avg Shares (Basic)",
             "fmt": SHARES, "unit": "shares", "tags": [
                "WeightedAverageNumberOfSharesOutstandingBasic"]},
            {"key": "shares_diluted", "label": "Wtd Avg Shares (Diluted)",
             "fmt": SHARES, "unit": "shares", "tags": [
                "WeightedAverageNumberOfDilutedSharesOutstanding"]},
        ],
    },
    {
        "key": "balance_sheet",
        "label": "Balance Sheet",
        "period_type": "instant",
        "lines": [
            {"key": "cash_and_equiv", "label": "Cash & Equivalents", "tags": [
                "CashAndCashEquivalentsAtCarryingValue",
                "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
            ]},
            {"key": "short_term_investments", "label": "Short-term Investments", "tags": [
                "ShortTermInvestments",
                "MarketableSecuritiesCurrent",
                # 일부 발행사(예: NVDA FY2026~)가 단기투자를 이 태그로 옮겼다.
                "DebtSecuritiesCurrent",
                "AvailableForSaleSecuritiesCurrent",
            ]},
            {"key": "marketable_equity_securities",
             "label": "Marketable Equity Securities", "tags": [
                "EquitySecuritiesFvNi",
                "EquitySecuritiesFairValue",
            ]},
            {"key": "accounts_receivable", "label": "Accounts Receivable", "tags": [
                "AccountsReceivableNetCurrent",
                "ReceivablesNetCurrent",
            ]},
            {"key": "inventory", "label": "Inventory", "tags": [
                "InventoryNet",
            ]},
            {"key": "prepaid_other_current",
             "label": "Prepaid & Other Current Assets", "tags": [
                "PrepaidExpenseAndOtherAssetsCurrent",
                "OtherAssetsCurrent",
            ]},
            {"key": "total_current_assets", "label": "Total Current Assets", "tags": [
                "AssetsCurrent",
            ]},
            {"key": "ppe_net", "label": "PP&E (Net)", "tags": [
                "PropertyPlantAndEquipmentNet",
            ]},
            {"key": "operating_lease_assets", "label": "Operating Lease Assets", "tags": [
                "OperatingLeaseRightOfUseAsset",
            ]},
            {"key": "goodwill", "label": "Goodwill", "tags": [
                "Goodwill",
            ]},
            {"key": "intangibles", "label": "Intangible Assets", "tags": [
                "IntangibleAssetsNetExcludingGoodwill",
                "FiniteLivedIntangibleAssetsNet",
            ]},
            {"key": "deferred_tax_assets", "label": "Deferred Tax Assets", "tags": [
                "DeferredIncomeTaxAssetsNet",
            ]},
            # 비시장성증권: 공시 face 의 합계(예: NVDA 2026Q4 43,364)가 companyfacts
            # 단일 fact 로 없다(여러 태그의 합성). face_only → 값 대신 Review 로 표시.
            {"key": "non_marketable_securities", "label": "Non-marketable Securities",
             "face_only": True, "tags": [],
             "note": "companyfacts 에 단일 fact 없음(합성 라인) — 정확한 face 합계는 "
                     "공시 inline-XBRL 파싱 필요"},
            {"key": "other_assets", "label": "Other Assets", "tags": [
                "OtherAssetsNoncurrent",
            ]},
            {"key": "total_assets", "label": "Total Assets", "tags": [
                "Assets",
            ]},
            {"key": "accounts_payable", "label": "Accounts Payable", "tags": [
                "AccountsPayableCurrent",
                "AccountsPayableTradeCurrent",
            ]},
            {"key": "accrued_liabilities",
             "label": "Accrued & Other Current Liabilities", "tags": [
                "AccruedLiabilitiesCurrent",
                "AccruedLiabilitiesCurrentAndOther",
            ]},
            {"key": "short_term_debt", "label": "Short-term Debt", "tags": [
                "LongTermDebtCurrent",
                "DebtCurrent",
                "ShortTermBorrowings",
            ]},
            {"key": "total_current_liabilities", "label": "Total Current Liabilities", "tags": [
                "LiabilitiesCurrent",
            ]},
            {"key": "long_term_debt", "label": "Long-term Debt", "tags": [
                "LongTermDebtNoncurrent",
                "LongTermDebt",
            ]},
            {"key": "lt_operating_lease_liab",
             "label": "Long-term Operating Lease Liabilities", "tags": [
                "OperatingLeaseLiabilityNoncurrent",
            ]},
            {"key": "other_lt_liabilities", "label": "Other Long-term Liabilities", "tags": [
                "OtherLiabilitiesNoncurrent",
            ]},
            {"key": "total_liabilities", "label": "Total Liabilities", "tags": [
                "Liabilities",
            ]},
            {"key": "common_stock", "label": "Common Stock", "tags": [
                "CommonStockValue",
            ]},
            {"key": "apic", "label": "Additional Paid-in Capital", "tags": [
                "AdditionalPaidInCapital",
                "AdditionalPaidInCapitalCommonStock",
            ]},
            {"key": "aoci", "label": "Accumulated Other Comprehensive Income", "tags": [
                "AccumulatedOtherComprehensiveIncomeLossNetOfTax",
            ]},
            {"key": "retained_earnings", "label": "Retained Earnings", "tags": [
                "RetainedEarningsAccumulatedDeficit",
            ]},
            {"key": "total_equity", "label": "Total Equity", "tags": [
                "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
                "StockholdersEquity",
            ]},
        ],
    },
    {
        "key": "cash_flow",
        "label": "Cash Flow",
        "period_type": "duration",
        "lines": [
            {"key": "cfo", "label": "Operating Cash Flow", "tags": [
                "NetCashProvidedByUsedInOperatingActivities",
                "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
            ]},
            {"key": "cfi", "label": "Investing Cash Flow", "tags": [
                "NetCashProvidedByUsedInInvestingActivities",
                "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations",
            ]},
            {"key": "cff", "label": "Financing Cash Flow", "tags": [
                "NetCashProvidedByUsedInFinancingActivities",
                "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations",
            ]},
            {"key": "depreciation_amort", "label": "Depreciation & Amortization", "tags": [
                "DepreciationDepletionAndAmortization",
                "DepreciationAmortizationAndAccretionNet",
                "DepreciationAndAmortization",
            ]},
            {"key": "stock_comp", "label": "Stock-based Compensation", "tags": [
                "ShareBasedCompensation",
            ]},
            {"key": "deferred_income_tax_cf", "label": "Deferred Income Taxes", "tags": [
                "DeferredIncomeTaxExpenseBenefit",
                "DeferredIncomeTaxesAndTaxCredits",
            ]},
            {"key": "gain_loss_investments", "label": "Gains/Losses on Investments", "tags": [
                "GainLossOnInvestments",
            ]},
            # 영업자산·부채 변동 (working capital)
            {"key": "chg_accounts_receivable", "label": "Change in Accounts Receivable",
             "tags": ["IncreaseDecreaseInAccountsReceivable"]},
            {"key": "chg_inventory", "label": "Change in Inventory",
             "tags": ["IncreaseDecreaseInInventories"]},
            {"key": "chg_prepaid_other", "label": "Change in Prepaid & Other Assets",
             "tags": ["IncreaseDecreaseInPrepaidDeferredExpenseAndOtherAssets",
                      # 선급을 따로 안 떼는 기업(예: COIN/AAPL)의 기타영업자산 변동 폴백
                      "IncreaseDecreaseInOtherOperatingAssets"]},
            {"key": "chg_accounts_payable", "label": "Change in Accounts Payable",
             "tags": ["IncreaseDecreaseInAccountsPayable"]},
            {"key": "chg_accrued_liabilities", "label": "Change in Accrued Liabilities",
             "tags": ["IncreaseDecreaseInAccruedLiabilitiesAndOtherOperatingLiabilities",
                      # 기타영업부채 변동 폴백(예: COIN/AAPL). 매입채무 합산 태그
                      # (...AccountsPayableAndAccruedLiabilities)은 매입채무와 이중계상
                      # 위험이 있어 의도적으로 제외한다.
                      "IncreaseDecreaseInOtherOperatingLiabilities"]},
            # 투자활동
            {"key": "capex", "label": "Capital Expenditures", "tags": [
                "PaymentsToAcquirePropertyPlantAndEquipment",
                "PaymentsToAcquireProductiveAssets",
                "PaymentsForCapitalImprovements",
            ]},
            {"key": "purchases_investments", "label": "Purchases of Investments", "tags": [
                "PaymentsToAcquireAvailableForSaleSecuritiesDebt",
                "PaymentsToAcquireInvestments",
            ]},
            {"key": "proceeds_investments", "label": "Sales/Maturities of Investments",
             "tags": [
                "ProceedsFromMaturitiesPrepaymentsAndCallsOfAvailableForSaleSecurities",
                "ProceedsFromSaleMaturityAndCollectionsOfInvestments",
            ]},
            {"key": "acquisitions", "label": "Acquisitions, net of cash", "tags": [
                "PaymentsToAcquireBusinessesNetOfCashAcquired",
            ]},
            # 재무활동
            {"key": "stock_repurchases", "label": "Repurchases of Common Stock", "tags": [
                "PaymentsForRepurchaseOfCommonStock",
            ]},
            {"key": "proceeds_stock_plans", "label": "Proceeds from Stock Plans", "tags": [
                "ProceedsFromStockPlans",
                "ProceedsFromIssuanceOfCommonStock",
            ]},
            {"key": "tax_withholding_sbc", "label": "Tax Withholding for SBC", "tags": [
                "PaymentsRelatedToTaxWithholdingForShareBasedCompensation",
            ]},
            {"key": "dividends_paid", "label": "Dividends Paid", "tags": [
                "PaymentsOfDividendsCommonStock",
                "PaymentsOfDividends",
            ]},
        ],
    },
]


def line_fmt(line: dict) -> str:
    return line.get("fmt", MONEY)


# ---- 한글 항목 라벨 (Raw Data 의 '항목' 열) -----------------------------
# canonical key -> 한글 라벨. Raw Data tidy 출력에서 '항목' 열로 쓴다.
# Canonical Key 가 진짜 표준화 식별자이고, 이 한글 라벨은 사람이 읽는 용도다.
KO_LABELS = {
    # income statement
    "revenue": "매출",
    "cost_of_revenue": "매출원가",
    "gross_profit": "매출총이익",
    "rd_expense": "연구개발비용",
    "sga_expense": "판매관리비용",
    "operating_expenses": "영업비용",
    "operating_income": "영업이익",
    "interest_expense": "이자비용",
    "interest_income": "이자이익",
    "other_income": "다른 이익 또는 비용",
    "pretax_income": "세전이익",
    "income_tax": "세금",
    "net_income": "순이익",
    "eps_basic": "주당순이익(기본)",
    "eps_diluted": "주당순이익(희석)",
    "shares_basic": "가중평균주식수(기본)",
    "shares_diluted": "가중평균주식수(희석)",
    # balance sheet
    "cash_and_equiv": "현금및현금성자산",
    "short_term_investments": "단기투자자산(채무증권)",
    "marketable_equity_securities": "시장성지분증권",
    "accounts_receivable": "매출채권",
    "inventory": "재고자산",
    "prepaid_other_current": "선급비용및기타유동자산",
    "total_current_assets": "유동자산합계",
    "ppe_net": "유형자산(순)",
    "operating_lease_assets": "운용리스자산",
    "goodwill": "영업권",
    "intangibles": "무형자산",
    "deferred_tax_assets": "이연법인세자산",
    "non_marketable_securities": "비시장성증권",
    "other_assets": "기타자산",
    "total_assets": "자산총계",
    "accounts_payable": "매입채무",
    "accrued_liabilities": "미지급및기타유동부채",
    "short_term_debt": "단기차입금",
    "total_current_liabilities": "유동부채합계",
    "long_term_debt": "장기차입금",
    "lt_operating_lease_liab": "장기운용리스부채",
    "other_lt_liabilities": "기타비유동부채",
    "total_liabilities": "부채총계",
    "common_stock": "보통주자본금",
    "apic": "주식발행초과금",
    "aoci": "기타포괄손익누계액",
    "retained_earnings": "이익잉여금",
    "total_equity": "자본총계",
    # cash flow
    "cfo": "영업활동현금흐름",
    "cfi": "투자활동현금흐름",
    "cff": "재무활동현금흐름",
    "depreciation_amort": "감가상각",
    "stock_comp": "주식보상비용",
    "deferred_income_tax_cf": "이연법인세",
    "gain_loss_investments": "투자손익",
    "chg_accounts_receivable": "매출채권변동",
    "chg_inventory": "재고자산변동",
    "chg_prepaid_other": "선급·기타자산변동",
    "chg_accounts_payable": "매입채무변동",
    "chg_accrued_liabilities": "미지급부채변동",
    "capex": "설비투자(CapEx)",
    "purchases_investments": "투자자산취득",
    "proceeds_investments": "투자자산처분·만기",
    "acquisitions": "사업취득(순)",
    "stock_repurchases": "자기주식취득",
    "proceeds_stock_plans": "주식플랜수령액",
    "tax_withholding_sbc": "주식보상세금원천징수",
    "dividends_paid": "배당금지급",
}


def line_ko(line: dict) -> str:
    """Raw Data '항목' 열에 쓸 한글 라벨 (없으면 영문 label)."""
    return KO_LABELS.get(line["key"], line["label"])


# ---- 차원(부문/지역/제품) 분해 매핑 ----------------------------------
# segments.py 가 inline-XBRL 컨텍스트의 차원(축/멤버)을 표준 그룹으로 묶을 때
# 쓰는 매핑. 축 문자열은 여기에만 둔다(다른 모듈에 하드코딩 금지 — 표준화 매핑은
# 단일 출처). 분해 대상 개념(우선 매출)의 후보 태그는 위 STATEMENTS 의 revenue
# 항목과 공유한다(segments 호출부가 그 tags 를 넘긴다).
KNOWN_AXES = {
    "us-gaap:StatementBusinessSegmentsAxis": "segment",
    "srt:StatementGeographicalAxis": "geography",
    "srt:ProductOrServiceAxis": "product",
}

# 표준 택소노미 네임스페이스(회사 고유가 아님). 여기 없는 prefix 의 멤버/개념은
# 회사 고유로 보고 검토(custom-tag)로 보낸다. 회사 고유 KPI 는 표준 택소노미에
# 없어 자동 표준화가 불가능하기 때문이다(ADR-007).
STANDARD_PREFIXES = frozenset({
    "us-gaap", "srt", "dei", "country", "stpr", "exch", "currency", "naics", "sic",
})

# 정합성(reconcile)용 '조정/제거' 멤버 힌트(소문자 부분문자열). 사업부간 제거·
# Corporate/Other·조정항목 때문에 '멤버 합 ≠ 총계'는 정상이다. 이런 멤버가 하나라도
# 있으면 차이가 커도 does-not-reconcile 로 띄우지 않는다(거짓양성 방지).
RECONCILING_MEMBER_HINTS = frozenset({
    "corporate", "eliminat", "reconcil", "intersegment", "intercompany",
    "other", "adjustment",
})


# ---- 별칭(Alias) 레이어 — 사람이 편집하는 선택적 표시 라벨 -------------
# segment_detail 의 as-reported 분해는 멤버 QName 을 '그대로' 보존한다(손실 0).
# 이 별칭 맵은 그 위에 얹는 '선택적' 한글/표시 라벨일 뿐이다 — 원본 멤버 열은
# 항상 유지되고, 별칭은 별도 열로만 덧붙는다. 자동 표준화가 아니라 사람이
# 점진적으로 채우는 사전이다(여기 없으면 별칭 열은 빈칸 → 채워야 할 멤버 표시).
# CRITICAL: 표준화/표시 매핑은 이 파일에만 둔다(다른 모듈 하드코딩 금지).

# 축(Axis) QName -> 한글 표시명.
AXIS_LABELS = {
    "us-gaap:StatementBusinessSegmentsAxis": "사업부문",
    "srt:StatementGeographicalAxis": "지역",
    "srt:ProductOrServiceAxis": "제품/서비스",
    "srt:MajorCustomersAxis": "주요고객",
    "srt:ConsolidationItemsAxis": "연결조정",
    "srt:ProductsAndServicesAxis": "제품/서비스",
    "us-gaap:RelatedPartyTransactionsByRelatedPartyAxis": "특수관계자",
}

# 멤버 QName -> 표시 라벨(별칭). 표준 country:* 와 회사 고유(예: nvda:) 모두 둘 수
# 있다. 새 멤버가 분해/Change Log 에 나타나면 여기에 한 줄 추가하면 된다.
MEMBER_ALIASES = {
    # 지역(country ISO)
    "country:US": "미국", "country:TW": "대만", "country:CN": "중국",
    "country:HK": "홍콩", "country:SG": "싱가포르", "country:JP": "일본",
    "country:KR": "한국", "country:DE": "독일", "country:GB": "영국",
    "country:IE": "아일랜드", "country:VN": "베트남", "country:IL": "이스라엘",
    # NVDA 제품/플랫폼 (회사 고유 멤버 — 자동 표준화 불가, 사람이 라벨링)
    "nvda:DataCenterMember": "데이터센터",
    "nvda:GamingMember": "게이밍",
    "nvda:ProfessionalVisualizationMember": "프로페셔널 비주얼라이제이션",
    "nvda:AutomotiveMember": "오토모티브",
    "nvda:OEMAndOtherMember": "OEM·기타",
    "nvda:OEMIpMember": "OEM·IP",
    "nvda:ComputeMember": "컴퓨트",
    "nvda:NetworkingMember": "네트워킹",
    "nvda:ComputeAndNetworkingMember": "컴퓨트·네트워킹",
    "nvda:GraphicsMember": "그래픽스",
    "nvda:HyperscaleMember": "하이퍼스케일",
    "nvda:EdgeComputingMember": "엣지컴퓨팅",
    "nvda:AICloudsIndustrialEnterpriseMember": "AI클라우드·산업·엔터프라이즈",
    "nvda:ChinaIncludingHongKongMember": "중국(홍콩 포함)",
    "nvda:OtherCountriesMember": "기타 국가",
    "nvda:OtherAsiaPacificMember": "기타 아시아·태평양",
    "nvda:AllOtherCountriesNotSeparatelyDisclosedMember": "기타 국가(미공개)",
    "srt:EuropeMember": "유럽",
    "srt:AsiaPacificMember": "아시아·태평양",
    "srt:AmericasMember": "미주",
    # 연결조정 축 멤버(매출 분해라기보다 소계/조정)
    "us-gaap:OperatingSegmentsMember": "영업부문 합계",
    "us-gaap:IntersegmentEliminationMember": "부문간 제거",
    "us-gaap:MaterialReconcilingItemsMember": "조정항목",
    "us-gaap:CorporateNonSegmentMember": "전사(비부문)",
    # COIN(코인베이스) 제품/서비스 매출 멤버. 주의: 조부모/부모/자식이 동시에
    # 태깅되므로(예: 아래 3계층) 모델에서 한 계층만 합산할 것 — Reconcile 시트가
    # overlap(Σ멤버>합계) 으로 표면화한다.
    "coin:BankServicingAndSubscriptionAndCirculationMember": "뱅크서비싱·구독서비스 합계",
    "us-gaap:BankServicingMember": "뱅크서비싱",
    "coin:BankServicingConsumerNetMember": "뱅크서비싱-소비자(순)",
    "coin:BankServicingInstitutionalMember": "뱅크서비싱-기관",
    "coin:BankServicingRetailNetMember": "뱅크서비싱-리테일(순)",
    "coin:BankServicingOtherMember": "뱅크서비싱-기타",
    "us-gaap:SubscriptionAndCirculationMember": "구독·서비스",
    "coin:SubscriptionAndCirculationStablecoinMember": "구독·서비스-스테이블코인",
    "coin:SubscriptionAndCirculationBlockchainInfrastructureServiceMember":
        "구독·서비스-블록체인인프라",
    "coin:SubscriptionAndCirculationCustodialFeeMember": "구독·서비스-수탁수수료",
    "coin:SubscriptionAndCirculationEarnCampaignMember": "구독·서비스-언(스테이킹)",
    "coin:SubscriptionAndCirculationOtherMember": "구독·서비스-기타",
    "coin:LearningRewardsMember": "러닝 리워드",
    "coin:OtherCryptoSalesMember": "기타 크립토 매출",
    "coin:ProductAndServiceOtherCryptoAssetSalesMember": "기타 크립토자산 판매",
    "coin:OtherRevenueMember": "기타 매출",
    # 지역/기타 — 표준 us-gaap 멤버라 타 기업에도 재사용된다
    "coin:RestOfTheWorldMember": "기타 지역",
    "us-gaap:NonUsMember": "미국 외",
    "us-gaap:RelatedPartyMember": "특수관계자",
}


def axis_label(axis: str) -> str:
    """축 QName 의 표시명. 없으면 local-name(콜론 뒤)으로 폴백."""
    if axis in AXIS_LABELS:
        return AXIS_LABELS[axis]
    return axis.split(":", 1)[1] if ":" in axis else axis


def member_label(member: str):
    """멤버 QName 의 별칭. 정의돼 있지 않으면 None(별칭 열은 빈칸)."""
    return MEMBER_ALIASES.get(member)
