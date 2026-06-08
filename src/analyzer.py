"""
Module for stock analysis, growth scoring, fair value calculations, 
quarterly metric computation, and generating AI summaries.
"""

import logging
from typing import Dict, Any, List, Tuple

logger = logging.getLogger(__name__)


def calculate_growth_score(fundamentals: Dict[str, Any], quarterly_results: List[Dict[str, Any]]) -> Tuple[int, str]:
    """
    Calculate a growth score out of 10 points based on fundamental metrics:
    - Revenue Growth (2 pts): Q-o-Q growth of net sales
    - PAT Growth (2 pts): Q-o-Q growth of profit after tax
    - ROE Health (2 pts): ROE > 15% (2 pts), 10-15% (1 pt)
    - Debt Control (2 pts): D/E < 50% (2 pts), 50-100% (1 pt)
    - Promoter Stability (2 pts): Promoter holding >= 50% (2 pts), 30-50% (1 pt)
    
    Returns:
        Tuple[score, status] (score: 0-10, status: Growth/Neutral/Weak)
    """
    score = 0
    
    # 1. Revenue Growth (2 points)
    rev_points = 0
    if len(quarterly_results) >= 2:
        latest_rev = quarterly_results[0].get("net_sales", 0)
        prev_rev = quarterly_results[1].get("net_sales", 0)
        if latest_rev > prev_rev * 1.02:  # >2% QoQ growth
            rev_points = 2
        elif latest_rev >= prev_rev * 0.98:  # Flat within +/-2%
            rev_points = 1
    else:
        # Fallback to annual revenue comparison if quarterly is missing
        rev_points = 1
    score += rev_points
    
    # 2. PAT Growth (2 points)
    pat_points = 0
    if len(quarterly_results) >= 2:
        latest_pat = quarterly_results[0].get("pat", 0)
        prev_pat = quarterly_results[1].get("pat", 0)
        if latest_pat > prev_pat * 1.02:
            pat_points = 2
        elif latest_pat >= prev_pat * 0.98:
            pat_points = 1
    else:
        pat_points = 1
    score += pat_points
    
    # 3. ROE (2 points)
    roe = fundamentals.get("roe")
    roe_points = 0
    if roe is not None:
        if roe > 15.0:
            roe_points = 2
        elif roe >= 10.0:
            roe_points = 1
    else:
        roe_points = 1  # neutral default
    score += roe_points
    
    # 4. Debt Control (2 points)
    de = fundamentals.get("debt_to_equity")
    de_points = 0
    if de is not None:
        # yfinance can return e.g. 0.5 or 50.0. Let's handle both.
        # If it's a percentage (typical yfinance style for DE is often absolute ratio or multiplied by 100)
        # We assume value > 5 means it's represented as percentage (e.g. 50.0 = 50% or 0.5)
        de_val = de if de < 5 else de / 100.0
        
        if de_val < 0.5:
            de_points = 2
        elif de_val <= 1.0:
            de_points = 1
    else:
        de_points = 1  # neutral default when real D/E data is unavailable (matches roe_points/promo_points)
    score += de_points
    
    # 5. Promoter/Insider Stability (2 points)
    promo = fundamentals.get("promoter_holding")
    if promo is None:
        promo_points = 1  # neutral default when real holding data is unavailable
    elif promo >= 50.0:
        promo_points = 2
    elif promo >= 30.0:
        promo_points = 1
    else:
        promo_points = 0
    score += promo_points
    
    # Determine Growth Status
    if score >= 8:
        status = "Growth"
    elif score >= 5:
        status = "Neutral"
    else:
        status = "Weak"
        
    return score, status


# Typical trailing-PE benchmarks per GICS-style sector — used as the relative-valuation
# anchor when triangulating fair value (a real analyst would use live sector medians;
# these are reasonable long-run approximations for the Indian market).
SECTOR_PE_BENCHMARKS = {
    "Technology": 28.0,
    "Financial Services": 18.0,
    "Basic Materials": 15.0,
    "Energy": 12.0,
    "Consumer Defensive": 35.0,
    "Consumer Cyclical": 24.0,
    "Healthcare": 25.0,
    "Industrials": 22.0,
    "Utilities": 14.0,
    "Communication Services": 20.0,
    "Real Estate": 18.0,
}


def calculate_fair_price(fundamentals: Dict[str, Any], quarterly_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Estimate fair value by triangulating two complementary methods analysts
    routinely cross-check against each other, then blending them:

    1) Growth & quality-adjusted relative PE valuation
       Fair Price = EPS x Fair PE, where Fair PE starts from the sector's
       typical multiple and is adjusted up/down for (a) the company's own
       smoothed earnings-growth trend — weighted across all available
       quarters rather than a single noisy data point — and (b) its
       profitability quality, measured by ROE versus a 15% "good business"
       benchmark (higher-quality compounders rightly command a premium).

    2) Graham Number (intrinsic-value sanity check)
       sqrt(22.5 x EPS x Book Value per Share) — Benjamin Graham's classic
       formula that anchors value to *both* earnings power and the balance
       sheet, guarding against PE-based estimates that drift too far from
       the company's actual asset backing.

    The final fair price blends the two (60% relative-PE / 40% Graham) when
    book-value data is available, falling back to the relative-PE estimate
    alone otherwise. The result is bounded to a realistic band around the
    current price, since genuine mispricings rarely exceed 2-2.5x without an
    extreme catalyst.
    """
    cmp = fundamentals.get("current_price", 0.0)
    if cmp <= 0:
        # No real current-price data to anchor any estimate to -- "fair price
        # ₹0.00, overvalued by 0.0%" would be a fabricated reading, not an
        # honest one. Say plainly that the model can't run.
        return {
            "fair_price": None,
            "current_price": cmp,
            "gap_percentage": None,
            "is_undervalued": None,
            "valuation_method": "N/A — no current price data available to anchor a fair-value estimate",
        }

    pe = fundamentals.get("pe_ratio")
    pb = fundamentals.get("pb_ratio")

    # --- EPS: prefer CMP / trailing PE (most current market-implied figure),
    # fall back to net profit / share count derived from market cap ---
    if pe and pe > 0:
        eps = cmp / pe
    else:
        market_cap = fundamentals.get("market_cap", 0.0)
        net_profit = fundamentals.get("net_profit", 0.0)
        if market_cap > 0 and net_profit > 0:
            shares = market_cap / cmp
            eps = net_profit / shares
        else:
            # No real trailing PE and no usable (positive) net profit to derive
            # EPS from -- typically a loss-making or pre-profit company.
            # Inventing an EPS (eps = cmp * 0.05) here would mean fabricating
            # the entire fair-value estimate on a made-up number; an honest
            # "model not applicable" is far better than a confident-looking guess.
            return {
                "fair_price": None,
                "current_price": cmp,
                "gap_percentage": None,
                "is_undervalued": None,
                "valuation_method": (
                    "N/A — no positive earnings (PE/net profit) data available to "
                    "estimate fair value; common for loss-making or pre-profit companies"
                ),
            }

    # --- Smoothed growth rate: average QoQ revenue growth across every
    # available consecutive quarter pair, weighted toward the most recent
    # quarters. This avoids over-reacting to one seasonal/one-off quarter,
    # which a single-quarter QoQ comparison is prone to. ---
    qoq_growth_rates = []
    for i in range(len(quarterly_results) - 1):
        latest_rev = quarterly_results[i].get("net_sales", 0.0)
        prev_rev = quarterly_results[i + 1].get("net_sales", 0.0)
        if prev_rev > 0:
            qoq_growth_rates.append((latest_rev - prev_rev) / prev_rev)

    if qoq_growth_rates:
        weights = list(range(len(qoq_growth_rates), 0, -1))  # most recent quarter weighted highest
        avg_growth_rate = sum(r * w for r, w in zip(qoq_growth_rates, weights)) / sum(weights)
        annualized_growth_pct = ((1.0 + avg_growth_rate) ** 4 - 1.0) * 100.0
        growth_phrase = f"~{annualized_growth_pct:.1f}% annualized growth"
        # Faster growers earn a premium multiple, decliners a discount (bounded so a
        # single blow-out or write-off quarter can't send the estimate to absurd extremes)
        growth_multiplier = 1.0 + max(-0.20, min(0.60, avg_growth_rate * 2.0))
    else:
        # No quarter-over-quarter revenue history to derive a real trend from --
        # apply a neutral multiplier (neither premium nor discount) instead of
        # asserting a fabricated growth figure in the displayed methodology text.
        growth_multiplier = 1.0
        growth_phrase = "no quarterly revenue history available to gauge growth (neutral multiplier applied)"

    # --- Method 1: Growth & quality-adjusted relative PE ---
    sector = fundamentals.get("sector", "N/A")
    sector_average_pe = SECTOR_PE_BENCHMARKS.get(sector, 20.0)

    # Quality premium/discount: ROE above/below the 15% "quality compounder" benchmark
    roe = fundamentals.get("roe")
    quality_multiplier = 1.0
    if roe is not None:
        quality_multiplier = 1.0 + max(-0.15, min(0.25, (roe - 15.0) / 100.0))

    relative_fair_pe = sector_average_pe * growth_multiplier * quality_multiplier
    relative_fair_pe = max(6.0, min(45.0, relative_fair_pe))
    relative_fair_price = eps * relative_fair_pe

    # --- Method 2: Graham Number — earnings x book-value cross-check ---
    graham_fair_price = None
    if pb and pb > 0 and eps > 0:
        book_value_per_share = cmp / pb
        if book_value_per_share > 0:
            graham_fair_price = (22.5 * eps * book_value_per_share) ** 0.5

    # --- Blend the two read-outs into one fair-value estimate ---
    if graham_fair_price and graham_fair_price > 0:
        fair_price = (relative_fair_price * 0.6) + (graham_fair_price * 0.4)
        valuation_method = (
            f"Blended model: 60% growth/quality-adjusted PE (Fair PE {relative_fair_pe:.1f}x off a "
            f"{sector_average_pe:.0f}x {sector} sector base, {growth_phrase}) "
            f"+ 40% Graham Number (√(22.5 × EPS × Book Value/Share))"
        )
    else:
        fair_price = relative_fair_price
        valuation_method = (
            f"Growth/quality-adjusted PE valuation: Fair PE of {relative_fair_pe:.1f}x applied to EPS "
            f"({sector_average_pe:.0f}x {sector} sector base, adjusted for {growth_phrase} "
            f"and ROE-based quality)"
        )

    # Bound the estimate to a realistic band around CMP — genuine mispricings
    # rarely exceed roughly 2-2.5x without an extreme, fundamentals-changing catalyst
    fair_price = max(cmp * 0.5, min(cmp * 2.5, fair_price))
    fair_price = round(fair_price, 2)

    # Gap percentage: ((Fair Price - CMP) / Fair Price) * 100
    if fair_price > 0:
        gap_percentage = ((fair_price - cmp) / fair_price) * 100.0
    else:
        gap_percentage = 0.0

    gap_percentage = round(gap_percentage, 2)
    is_undervalued = fair_price > cmp

    return {
        "fair_price": fair_price,
        "current_price": cmp,
        "gap_percentage": gap_percentage,
        "is_undervalued": is_undervalued,
        "valuation_method": valuation_method
    }


# Curated peer map of major NSE-listed names — keyed by Yahoo Finance's granular
# `industry` classification (e.g. "Apparel Manufacturing", "Auto Manufacturers"),
# NOT the broad `sector` ("Consumer Cyclical" spans both fashion retailers and
# automakers, "Basic Materials" spans both aluminium and steel — grouping by
# sector alone produces nonsensical "competitors" like Tata Motors for a fashion
# company). yfinance does not expose live peer/competitor data for NSE stocks,
# so each list below was hand-verified against Yahoo's own `industry` field for
# every symbol so the grouping is genuinely accurate, not just plausible-looking.
INDUSTRY_PEER_MAP: Dict[str, List[Tuple[str, str]]] = {
    "Information Technology Services": [
        ("TCS.NS", "Tata Consultancy Services"),
        ("INFY.NS", "Infosys"),
        ("WIPRO.NS", "Wipro"),
        ("HCLTECH.NS", "HCL Technologies"),
        ("TECHM.NS", "Tech Mahindra"),
    ],
    "Banks - Regional": [
        ("HDFCBANK.NS", "HDFC Bank"),
        ("ICICIBANK.NS", "ICICI Bank"),
        ("SBIN.NS", "State Bank of India"),
        ("KOTAKBANK.NS", "Kotak Mahindra Bank"),
        ("AXISBANK.NS", "Axis Bank"),
    ],
    "Credit Services": [
        ("BAJFINANCE.NS", "Bajaj Finance"),
        ("CHOLAFIN.NS", "Cholamandalam Investment and Finance"),
    ],
    "Oil & Gas Refining & Marketing": [
        ("RELIANCE.NS", "Reliance Industries"),
        ("IOC.NS", "Indian Oil Corporation"),
        ("BPCL.NS", "Bharat Petroleum"),
        ("HINDPETRO.NS", "Hindustan Petroleum Corporation"),
    ],
    "Oil & Gas Integrated": [
        ("ONGC.NS", "Oil & Natural Gas Corporation"),
        ("OIL.NS", "Oil India"),
    ],
    "Aluminum": [
        ("NATIONALUM.NS", "National Aluminium Company"),
        ("HINDALCO.NS", "Hindalco Industries"),
    ],
    "Steel": [
        ("TATASTEEL.NS", "Tata Steel"),
        ("JSWSTEEL.NS", "JSW Steel"),
        ("JINDALSTEL.NS", "Jindal Steel"),
        ("SAIL.NS", "Steel Authority of India"),
    ],
    "Other Industrial Metals & Mining": [
        ("VEDL.NS", "Vedanta"),
        ("HINDZINC.NS", "Hindustan Zinc"),
    ],
    "Specialty Chemicals": [
        ("ASIANPAINT.NS", "Asian Paints"),
        ("PIDILITIND.NS", "Pidilite Industries"),
        ("AARTIIND.NS", "Aarti Industries"),
    ],
    "Auto Manufacturers": [
        ("MARUTI.NS", "Maruti Suzuki India"),
        ("M&M.NS", "Mahindra & Mahindra"),
        ("TMPV.NS", "Tata Motors Passenger Vehicles"),
        ("BAJAJ-AUTO.NS", "Bajaj Auto"),
        ("HEROMOTOCO.NS", "Hero MotoCorp"),
        ("EICHERMOT.NS", "Eicher Motors"),
    ],
    "Apparel Manufacturing": [
        ("ABFRL.NS", "Aditya Birla Fashion and Retail"),
        ("PAGEIND.NS", "Page Industries"),
    ],
    "Apparel Retail": [
        ("TRENT.NS", "Trent"),
    ],
    "Department Stores": [
        ("VMART.NS", "V-Mart Retail"),
        ("SHOPERSTOP.NS", "Shoppers Stop"),
    ],
    "Luxury Goods": [
        ("TITAN.NS", "Titan Company"),
        ("KALYANKJIL.NS", "Kalyan Jewellers India"),
    ],
    "Drug Manufacturers - Specialty & Generic": [
        ("SUNPHARMA.NS", "Sun Pharmaceutical Industries"),
        ("DRREDDY.NS", "Dr. Reddy's Laboratories"),
        ("CIPLA.NS", "Cipla"),
        ("DIVISLAB.NS", "Divi's Laboratories"),
        ("LUPIN.NS", "Lupin"),
        ("AUROPHARMA.NS", "Aurobindo Pharma"),
    ],
    "Household & Personal Products": [
        ("HINDUNILVR.NS", "Hindustan Unilever"),
        ("GODREJCP.NS", "Godrej Consumer Products"),
        ("DABUR.NS", "Dabur India"),
        ("MARICO.NS", "Marico"),
    ],
    "Tobacco": [
        ("ITC.NS", "ITC"),
        ("GODFRYPHLP.NS", "Godfrey Phillips India"),
        ("VSTIND.NS", "VST Industries"),
    ],
    "Packaged Foods": [
        ("NESTLEIND.NS", "Nestle India"),
        ("BRITANNIA.NS", "Britannia Industries"),
        ("TATACONSUM.NS", "Tata Consumer Products"),
    ],
    "Discount Stores": [
        ("DMART.NS", "Avenue Supermarts (DMart)"),
    ],
    "Engineering & Construction": [
        ("LT.NS", "Larsen & Toubro"),
    ],
    "Specialty Industrial Machinery": [
        ("SIEMENS.NS", "Siemens India"),
        ("ABB.NS", "ABB India"),
        ("CUMMINSIND.NS", "Cummins India"),
    ],
    "Aerospace & Defense": [
        ("BEL.NS", "Bharat Electronics"),
        ("HAL.NS", "Hindustan Aeronautics"),
    ],
    "Utilities - Regulated Electric": [
        ("NTPC.NS", "NTPC"),
        ("POWERGRID.NS", "Power Grid Corporation of India"),
    ],
    "Utilities - Independent Power Producers": [
        ("TATAPOWER.NS", "Tata Power Company"),
        ("ADANIPOWER.NS", "Adani Power"),
    ],
}


def get_top_competitors(symbol: str, industry: str, limit: int = 3) -> List[Dict[str, str]]:
    """
    Returns up to `limit` peer companies from the same industry (excluding the
    queried symbol itself), sourced from a curated map of major NSE-listed names.

    Matches on Yahoo Finance's granular `industry` field rather than the broad
    `sector` — "sector" is too coarse to identify genuine competitors (e.g. an
    apparel company and an automaker can share the "Consumer Cyclical" sector).
    Returns an empty list — never a guessed/mismatched grouping — if we don't
    have a curated, verified peer set for this exact industry.
    """
    symbol_clean = symbol.strip().upper()
    peers = INDUSTRY_PEER_MAP.get(industry, [])
    filtered = [{"symbol": s, "name": n} for s, n in peers if s.upper() != symbol_clean]
    return filtered[:limit]


def calculate_quarterly_metrics(quarterly_results: List[Dict[str, Any]], fundamentals: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Computes key quarterly performance ratios (GPM, NPM, TTM PE) and recommendations.
    """
    processed_quarters = []
    market_cap = fundamentals.get("market_cap", 0.0)

    # Loop from oldest to newest to compute trailing/growth metrics, but return sorted by date desc
    # For simplification, we process them and calculate trailing PE
    for i, q in enumerate(quarterly_results):
        sales = q.get("net_sales", 0.0)
        pat = q.get("pat", 0.0)
        ebitda = q.get("ebitda", 0.0)
        interest = q.get("interest", 0.0)
        tax = q.get("tax", 0.0)

        # Gross Profit: use the company's actual reported figure from Yahoo
        # Finance's quarterly financials (genuine GPMs vary hugely by sector —
        # e.g. ~41% for TCS, ~28% for Reliance, ~65% for National Aluminium —
        # so a flat assumed margin would misrepresent every company).
        gp = q.get("gross_profit")

        gpm = (gp / sales * 100.0) if (gp is not None and sales > 0) else None
        npm = (pat / sales * 100.0) if sales > 0 else 0.0

        # TTM PAT & Gross Profit
        # Sum the real reported figures across the 4 most recent quarters when
        # available; for the tail end of the history (fewer than 4 trailing
        # quarters) annualize the latest quarter's real reported figure — a
        # standard analyst shorthand, not a fabricated number.
        available_quarters = quarterly_results[i : i+4]
        if len(available_quarters) == 4:
            ttm_pat = sum(item.get("pat", 0.0) for item in available_quarters)
            if all(item.get("gross_profit") is not None for item in available_quarters):
                ttm_gp = sum(item.get("gross_profit", 0.0) for item in available_quarters)
            else:
                ttm_gp = gp * 4.0 if gp is not None else None
        else:
            ttm_pat = pat * 4.0
            ttm_gp = gp * 4.0 if gp is not None else None

        ttm_pe = (market_cap / ttm_pat) if ttm_pat > 0 else None
        
        # Recommendation value based on QoQ trend
        recommendation = "Neutral"
        if i < len(quarterly_results) - 1:
            prev_quarter = quarterly_results[i+1]
            prev_sales = prev_quarter.get("net_sales", 0.0)
            prev_pat = prev_quarter.get("pat", 0.0)
            
            if sales > prev_sales * 1.03 and pat > prev_pat * 1.03:
                recommendation = "Growing"
            elif sales < prev_sales * 0.97 and pat < prev_pat * 0.97:
                recommendation = "Weak"
        else:
            recommendation = "Growing" if pat > 0 else "Weak"

        # Format quarter string
        raw_date = q.get("quarter", "")
        # convert e.g., '2025-12-31' to 'Q3 FY26' style or keep ISO. Let's keep ISO as key but display nicely
        
        # net_sales/interest/ebitda/tax/pat are always real floats here (never
        # None — fetch_quarterly_results normalizes unreported items to 0.0),
        # and a loss-making quarter has a genuinely NEGATIVE pat/ebitda. A
        # `> 0` guard would silently display that real loss as "₹0.00 Cr" —
        # convert unconditionally so genuine negative figures show as such.
        processed_quarters.append({
            "quarter": raw_date,
            "net_sales": round(sales / 1e7, 2),  # Convert to Crores (10 Million)
            "ttm_gp": round(ttm_gp / 1e7, 2) if ttm_gp is not None else None,
            "gpm": round(gpm, 2) if gpm is not None else None,
            "interest": round(interest / 1e7, 2),
            "ebitda": round(ebitda / 1e7, 2),
            "tax": round(tax / 1e7, 2),
            "pat": round(pat / 1e7, 2),
            "npm": round(npm, 2),
            "market_cap": round(market_cap / 1e7, 2) if market_cap > 0 else 0.0,
            "ttm_pe": round(ttm_pe, 2) if ttm_pe else None,
            "recommendation": recommendation
        })
        
    return processed_quarters


def generate_ai_summary(fundamentals: Dict[str, Any], calculated_metrics: Dict[str, Any], quarterly_results: List[Dict[str, Any]]) -> str:
    """
    Generate an analyst-grade AI summary for the stock based on its numbers.
    """
    company_name = fundamentals.get("company_name", "The company")
    growth_status = calculated_metrics.get("growth_status", "Neutral")
    score = calculated_metrics.get("growth_score", 5)
    fair_data = calculated_metrics.get("fair_price_data", {})
    fair_price = fair_data.get("fair_price")
    gap_percentage = fair_data.get("gap_percentage")
    is_undervalued = fair_data.get("is_undervalued")
    pe = fundamentals.get("pe_ratio")
    
    # 1. Opening sentence
    summary = f"{company_name} is currently categorized as a {growth_status} stock (Growth Score: {score}/10). "
    
    # 2. Quarterly Performance comment
    if quarterly_results:
        latest = quarterly_results[0]
        latest_pat = latest.get("pat", 0) / 1e7 # in Cr
        latest_sales = latest.get("net_sales", 0) / 1e7 # in Cr
        
        if len(quarterly_results) >= 2:
            prev = quarterly_results[1]
            prev_sales = prev.get("net_sales", 0) / 1e7
            sales_change = ((latest_sales - prev_sales) / prev_sales * 100.0) if prev_sales > 0 else 0
            
            if sales_change > 5:
                summary += f"Revenue and PAT have shown strong upward momentum, with net sales rising by {sales_change:.1f}% QoQ in the latest quarter to ₹{latest_sales:.2f} Cr. "
            elif sales_change < -5:
                summary += f"Revenue has faced pressure, declining by {abs(sales_change):.1f}% QoQ to ₹{latest_sales:.2f} Cr, which warrants closer inspection. "
            else:
                summary += f"Quarterly performance has remained stable, with net sales recorded at ₹{latest_sales:.2f} Cr. "
        else:
            summary += f"In the latest quarter, net sales reached ₹{latest_sales:.2f} Cr with profit after tax at ₹{latest_pat:.2f} Cr. "
            
    # 3. Shareholding & Debt
    promoter = fundamentals.get("promoter_holding")
    institutional = fundamentals.get("institutional_holding")
    debt_equity = fundamentals.get("debt_to_equity", 0.0)

    if promoter is not None and institutional is not None:
        summary += f"Promoter/insider holding stands at {promoter:.1f}%, with institutional investors (FIIs, DIIs, and mutual funds combined) holding {institutional:.1f}%. "
    elif promoter is not None:
        summary += f"Promoter/insider holding stands at {promoter:.1f}%. "
    elif institutional is not None:
        summary += f"Institutional investors collectively hold {institutional:.1f}% of the company. "
    
    if debt_equity is not None:
        de_ratio = debt_equity if debt_equity < 5 else debt_equity / 100.0
        if de_ratio < 0.2:
            summary += "The company maintains a highly conservative capital structure with minimal debt (D/E ratio under control). "
        elif de_ratio < 0.8:
            summary += f"Debt levels are well managed with a D/E ratio of {de_ratio:.2f}. "
        else:
            summary += f"Leverage is relatively high with a D/E ratio of {de_ratio:.2f}, representing a potential risk factor. "
            
    # 4. Valuation & Conclusion
    pe_str = f"{pe:.2f}x" if pe else "N/A"
    if fair_price is None or gap_percentage is None or is_undervalued is None:
        # No usable earnings data to build a fair-value estimate from (typically
        # loss-making companies) -- say so plainly instead of asserting a
        # fabricated valuation gap and "undervalued/overvalued" verdict.
        summary += f"Trading at a PE ratio of {pe_str}, the stock currently lacks sufficient earnings data to support a reliable fair-value estimate."
    elif is_undervalued:
        summary += f"Trading at a PE ratio of {pe_str}, the stock appears undervalued by approximately {gap_percentage:.1f}% relative to its calculated growth-adjusted fair price of ₹{fair_price:,.2f}."
    else:
        summary += f"Trading at a PE ratio of {pe_str}, the stock appears overvalued by {abs(gap_percentage):.1f}% compared to its calculated fair price of ₹{fair_price:,.2f}."

    return summary


def build_complete_report(symbol: str, raw_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Orchestrate full analysis pipeline.
    Combines raw data with calculated metrics, growth scoring, fair price, and AI summary.
    """
    fundamentals = raw_data.get("fundamentals", {})
    quarterly_results = raw_data.get("quarterly_results", [])
    historical_prices = raw_data.get("historical_prices", [])
    
    # Calculate components
    growth_score, growth_status = calculate_growth_score(fundamentals, quarterly_results)
    fair_price_data = calculate_fair_price(fundamentals, quarterly_results)
    
    calculated_metrics = {
        "growth_score": growth_score,
        "growth_status": growth_status,
        "fair_price_data": fair_price_data
    }
    
    quarterly_metrics = calculate_quarterly_metrics(quarterly_results, fundamentals)
    ai_summary = generate_ai_summary(fundamentals, calculated_metrics, quarterly_results)
    top_competitors = get_top_competitors(symbol, fundamentals.get("industry", "N/A"))

    # Growth recommendation based on growth status
    recommendation = "Neutral"
    if growth_status == "Growth":
        recommendation = "Growing"
    elif growth_status == "Weak":
        recommendation = "Weak"
        
    return {
        "symbol": symbol.strip().upper(),
        "company_name": fundamentals.get("company_name", symbol),
        "fetched_at": raw_data.get("fetched_at"),
        "fundamentals": fundamentals,
        "calculated_metrics": calculated_metrics,
        "quarterly_metrics": quarterly_metrics,
        "historical_prices": historical_prices,
        "ai_summary": ai_summary,
        "top_competitors": top_competitors,
        "recommendation": recommendation
    }
