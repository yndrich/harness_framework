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
            ]},
            {"key": "accounts_receivable", "label": "Accounts Receivable", "tags": [
                "AccountsReceivableNetCurrent",
                "ReceivablesNetCurrent",
            ]},
            {"key": "inventory", "label": "Inventory", "tags": [
                "InventoryNet",
            ]},
            {"key": "total_current_assets", "label": "Total Current Assets", "tags": [
                "AssetsCurrent",
            ]},
            {"key": "ppe_net", "label": "PP&E (Net)", "tags": [
                "PropertyPlantAndEquipmentNet",
            ]},
            {"key": "goodwill", "label": "Goodwill", "tags": [
                "Goodwill",
            ]},
            {"key": "intangibles", "label": "Intangible Assets", "tags": [
                "IntangibleAssetsNetExcludingGoodwill",
                "FiniteLivedIntangibleAssetsNet",
            ]},
            {"key": "total_assets", "label": "Total Assets", "tags": [
                "Assets",
            ]},
            {"key": "accounts_payable", "label": "Accounts Payable", "tags": [
                "AccountsPayableCurrent",
                "AccountsPayableTradeCurrent",
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
            {"key": "total_liabilities", "label": "Total Liabilities", "tags": [
                "Liabilities",
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
            {"key": "capex", "label": "Capital Expenditures", "tags": [
                "PaymentsToAcquirePropertyPlantAndEquipment",
                "PaymentsToAcquireProductiveAssets",
                "PaymentsForCapitalImprovements",
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
