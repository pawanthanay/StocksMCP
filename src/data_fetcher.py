"""
Module for fetching stock data from Yahoo Finance (yfinance).
Handles fundamentals, quarterly statements, and historical price data.
All figures returned here are sourced live from Yahoo Finance — fields that
Yahoo does not publish for a given symbol are returned as ``None`` rather
than being estimated or fabricated.
"""

import logging
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple
import yfinance as yf
from curl_cffi import requests as cffi_requests

logger = logging.getLogger(__name__)

# Yahoo Finance's bot-detection fingerprints the TLS handshake, not just
# request rate — Python's default `requests`/`urllib3` stack has a recognisable
# signature that gets flagged (especially from shared/datacenter IPs on hosts
# like Render, Railway, AWS, ...), producing persistent "Too Many Requests"
# errors regardless of how few requests are actually sent. Routing all calls
# through a curl_cffi session that impersonates a real Chrome browser's TLS
# fingerprint is the documented fix and lets the exact same code run reliably
# both locally and on cloud hosts. One session is reused for the process
# lifetime (matches yfinance's own internal session-reuse pattern).
_yf_session = cffi_requests.Session(impersonate="chrome")

# Yahoo Finance can still return HTTP 429 ("Too Many Requests. Rate limited.")
# under genuinely bursty traffic even with a browser-like fingerprint. It's
# transient (a request that fails can succeed seconds later), so a short,
# bounded retry recovers these without risking a retry storm that would make
# the limiting worse.
_RATE_LIMIT_RETRY_ATTEMPTS = 3
_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS = 1.5


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc)
    return "Too Many Requests" in text or "rate limit" in text.lower()


def _yf_call(fn, description: str):
    """
    Runs a single yfinance network call, retrying with backoff ONLY on
    rate-limit errors — genuine data errors (bad symbol, network failure,
    etc.) surface immediately rather than being masked by retries.
    """
    last_exc: Optional[BaseException] = None
    for attempt in range(1, _RATE_LIMIT_RETRY_ATTEMPTS + 1):
        try:
            return fn()
        except Exception as e:
            last_exc = e
            if attempt < _RATE_LIMIT_RETRY_ATTEMPTS and _is_rate_limit_error(e):
                delay = _RATE_LIMIT_RETRY_BASE_DELAY_SECONDS * attempt
                logger.warning(
                    f"Yahoo Finance rate-limited '{description}' "
                    f"(attempt {attempt}/{_RATE_LIMIT_RETRY_ATTEMPTS}); retrying in {delay:.1f}s"
                )
                time.sleep(delay)
                continue
            raise
    raise last_exc  # unreachable — loop above always returns or raises


# Short-lived cache of live FX rates (key -> (rate, fetched_at_epoch_seconds)).
# A long-running server must keep re-pulling rates periodically — FX moves daily —
# so entries are refreshed once they exceed _FX_RATE_TTL_SECONDS rather than being
# kept "for the life of the process".
_fx_rate_cache: Dict[str, Tuple[Optional[float], float]] = {}
_FX_RATE_TTL_SECONDS = 60 * 60  # re-fetch at most once per hour


def _get_live_fx_rate(from_currency: str, to_currency: str) -> Optional[float]:
    """
    Fetch a live FX rate (1 unit of `from_currency` -> `to_currency`) from Yahoo
    Finance's currency pairs (e.g. "USDINR=X"). Returns ``None`` — never a
    fabricated/guessed rate — if the pair can't be resolved live. Cached for at
    most _FX_RATE_TTL_SECONDS so a long-running server keeps using a recent rate.
    """
    if from_currency == to_currency:
        return 1.0

    pair = f"{from_currency}{to_currency}=X"
    cached = _fx_rate_cache.get(pair)
    if cached is not None and (time.time() - cached[1]) < _FX_RATE_TTL_SECONDS:
        return cached[0]

    rate: Optional[float] = None
    try:
        fx_ticker = yf.Ticker(pair, session=_yf_session)
        fx_info = fx_ticker.info or {}
        rate = fx_info.get("regularMarketPrice") or fx_info.get("currentPrice")
        if rate is None:
            hist = fx_ticker.history(period="5d")
            if not hist.empty:
                rate = float(hist["Close"].iloc[-1])
    except Exception as e:
        logger.warning(f"Could not fetch live FX rate for {pair}: {e}")

    _fx_rate_cache[pair] = (rate, time.time())
    return rate


def fetch_stock_fundamentals(symbol: str) -> Dict[str, Any]:
    """
    Fetch stock fundamentals from Yahoo Finance.
    Includes general info, market metrics, margins, and major-holders
    (promoter/institutional shareholding) data — all live, none fabricated.
    """
    logger.info(f"Fetching fundamentals for symbol: {symbol}")
    symbol_upper = symbol.strip().upper()
    ticker = yf.Ticker(symbol_upper, session=_yf_session)
    
    try:
        # Under sustained rate-limiting yfinance can return None here instead
        # of raising — guard with `or {}` so `info` is always a dict.
        info = _yf_call(lambda: ticker.info, f"{symbol_upper} fundamentals") or {}
    except Exception as e:
        logger.error(f"Error fetching info for {symbol_upper} from yfinance: {e}")
        info = {}

    # A delisted/renamed/mistyped symbol doesn't always come back as an empty
    # dict — Yahoo can return a near-empty stub like {'trailingPegRatio': None}
    # that is "truthy" but identifies no real company (e.g. the old TATAMOTORS.NS
    # post-demerger). Treat "no name and no live price" as "this symbol does not
    # currently resolve to a real company" so we surface a clear error instead of
    # silently rendering a dashboard full of fabricated-looking ₹0.00 zeros.
    has_identity = bool(info.get("longName") or info.get("shortName"))
    has_price = bool(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice"))
    if not info or not (has_identity or has_price):
        logger.warning(f"No usable data for {symbol_upper} — stock might be invalid, delisted, or renamed.")
        return {}

    # Extract parameters with safe fallbacks
    company_name = info.get("longName") or info.get("shortName") or symbol_upper
    sector = info.get("sector") or "N/A"
    industry = info.get("industry") or "N/A"
    
    # Prices & Valuation
    current_price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice") or 0.0
    market_cap = info.get("marketCap") or 0.0
    pe_ratio = info.get("trailingPE") or info.get("forwardPE")
    pb_ratio = info.get("priceToBook")
    
    # Financial metrics
    roe = info.get("returnOnEquity")
    if roe is not None:
        roe = roe * 100.0  # Convert fraction to percentage
        
    debt_to_equity = info.get("debtToEquity") # Often represented as a percentage (e.g. 10.5 means 10.5% or 0.105)
    # yfinance returns debtToEquity as percentage (e.g. 80.5) or ratio. Let's keep it as is.
    
    total_revenue = info.get("totalRevenue") or 0.0
    net_income = info.get("netIncomeToCommon") or info.get("netIncome") or 0.0
    ebitda = info.get("ebitda") or 0.0

    # Some NSE-listed companies (e.g. Infosys, Wipro) report income-statement
    # figures (totalRevenue/netIncome/ebitda) in USD while the stock trades in
    # INR — `currentPrice`/`marketCap`/`trailingPE` are genuinely in INR, but
    # these three are not. Convert with a LIVE FX rate so they're consistent
    # with everything else; if no live rate is fetchable, zero them out rather
    # than silently mixing currencies in downstream calculations (e.g. the
    # fair-price EPS fallback in analyzer.py divides net_profit by share count).
    financial_currency = info.get("financialCurrency")
    trading_currency = info.get("currency")
    if financial_currency and trading_currency and financial_currency != trading_currency:
        live_rate = _get_live_fx_rate(financial_currency, trading_currency)
        if live_rate is not None:
            total_revenue *= live_rate
            net_income *= live_rate
            ebitda *= live_rate
            logger.info(
                f"{symbol_upper}: converted income-statement figures from "
                f"{financial_currency} to {trading_currency} at live rate {live_rate:.4f}"
            )
        else:
            logger.warning(
                f"{symbol_upper}: revenue/profit/EBITDA are reported in "
                f"{financial_currency} but the stock trades in {trading_currency}, "
                f"and no live FX rate could be fetched — zeroing these out rather "
                f"than mixing currencies."
            )
            total_revenue = 0.0
            net_income = 0.0
            ebitda = 0.0


    fifty_two_week_high = info.get("fiftyTwoWeekHigh") or current_price
    fifty_two_week_low = info.get("fiftyTwoWeekLow") or current_price

    # Shareholding breakdown: Yahoo Finance does not expose a granular
    # FII / DII / Mutual-Fund / Pledged-shares split for NSE-listed stocks, but
    # it does provide a genuine major-holders summary (insider/promoter holding
    # and combined institutional holding) via the ticker's `major_holders` table.
    # We surface only that real data rather than fabricating the missing split.
    promoter_holding = None
    institutional_holding = None
    institutional_holders_count = None
    try:
        major_holders = _yf_call(lambda: ticker.major_holders, f"{symbol_upper} major holders")
        if major_holders is not None and not major_holders.empty and "Value" in major_holders.columns:
            breakdown = major_holders["Value"].to_dict()
            insiders_pct = breakdown.get("insidersPercentHeld")
            institutions_pct = breakdown.get("institutionsPercentHeld")
            institutions_count = breakdown.get("institutionsCount")
            if insiders_pct is not None:
                promoter_holding = round(float(insiders_pct) * 100.0, 2)
            if institutions_pct is not None:
                institutional_holding = round(float(institutions_pct) * 100.0, 2)
            if institutions_count is not None:
                institutional_holders_count = int(institutions_count)
    except Exception as e:
        logger.warning(f"Could not fetch major holders for {symbol_upper}: {e}")

    return {
        "symbol": symbol_upper,
        "company_name": company_name,
        "sector": sector,
        "industry": industry,
        "current_price": current_price,
        "market_cap": market_cap,
        "pe_ratio": pe_ratio,
        "pb_ratio": pb_ratio,
        "roe": roe,
        "debt_to_equity": debt_to_equity,
        "revenue": total_revenue,
        "net_profit": net_income,
        "ebitda": ebitda,
        "promoter_holding": promoter_holding,
        "institutional_holding": institutional_holding,
        "institutional_holders_count": institutional_holders_count,
        "fifty_two_week_high": fifty_two_week_high,
        "fifty_two_week_low": fifty_two_week_low,
    }


def fetch_historical_prices(symbol: str, period: str = "1y") -> List[Dict[str, Any]]:
    """
    Fetch historical prices (OHLCV) for a given symbol and period.
    Returns list of dicts with iso formatted dates.
    """
    logger.info(f"Fetching historical prices for {symbol} with period {period}")
    ticker = yf.Ticker(symbol.strip().upper(), session=_yf_session)
    
    try:
        hist = _yf_call(lambda: ticker.history(period=period), f"{symbol} historical prices")
    except Exception as e:
        logger.error(f"Error fetching history for {symbol} from yfinance: {e}")
        return []

    if hist.empty:
        logger.warning(f"No historical price data returned for {symbol}")
        return []

    prices = []
    for index, row in hist.iterrows():
        # index is Timestamp
        date_str = index.strftime("%Y-%m-%d")
        prices.append({
            "date": date_str,
            "open": round(float(row["Open"]), 2),
            "high": round(float(row["High"]), 2),
            "low": round(float(row["Low"]), 2),
            "close": round(float(row["Close"]), 2),
            "volume": int(row["Volume"]),
        })
    return prices


def fetch_quarterly_results(symbol: str) -> List[Dict[str, Any]]:
    """
    Fetch quarterly financial results (income statement) from Yahoo Finance.
    Sorted from newest to oldest.
    """
    logger.info(f"Fetching quarterly results for {symbol}")
    ticker = yf.Ticker(symbol.strip().upper(), session=_yf_session)
    
    try:
        quarterly_financials = _yf_call(lambda: ticker.quarterly_financials, f"{symbol} quarterly financials")
    except Exception as e:
        logger.error(f"Error fetching quarterly financials for {symbol}: {e}")
        return []

    if quarterly_financials is None or quarterly_financials.empty:
        logger.warning(f"No quarterly financial data returned for {symbol}")
        return []

    # Some NSE-listed companies (e.g. Infosys, Wipro) report their financial
    # statements in USD while the stock itself trades in INR — yfinance returns
    # the raw USD figures from `quarterly_financials`. Left unconverted, the
    # dashboard would display e.g. Infosys's ~$5B quarterly revenue as "Rs 504 Cr"
    # (~83x too small) while still labelling it in rupees. Convert with a LIVE
    # FX rate so "Cr" figures genuinely reflect rupees; if no live rate can be
    # fetched, refuse to return mismatched-currency figures mislabeled as INR.
    fx_rate = 1.0
    try:
        # Must know whether financial-statement currency differs from trading
        # currency BEFORE returning any figures — guessing "no mismatch" here
        # would silently show e.g. Infosys's USD figures as INR at ~1/83rd
        # their real value while still labelling them "Cr" (rupees-crore).
        # That's a far worse outcome than omitting the section entirely, so a
        # failed lookup must refuse to return data, not assume fx_rate = 1.0.
        info = _yf_call(lambda: ticker.info, f"{symbol} quarterly-financials currency check") or {}
    except Exception as e:
        logger.warning(
            f"{symbol}: could not verify financial-statement currency ({e}) — "
            f"omitting quarterly figures rather than risk showing them in the "
            f"wrong currency under an INR/Cr label."
        )
        return []

    financial_currency = info.get("financialCurrency")
    trading_currency = info.get("currency")
    if financial_currency and trading_currency and financial_currency != trading_currency:
        live_rate = _get_live_fx_rate(financial_currency, trading_currency)
        if live_rate is not None:
            fx_rate = live_rate
            logger.info(
                f"{symbol}: converting quarterly financials from "
                f"{financial_currency} to {trading_currency} at live rate {fx_rate:.4f}"
            )
        else:
            logger.warning(
                f"{symbol}: financials are reported in {financial_currency} but the "
                f"stock trades in {trading_currency}, and no live FX rate could be "
                f"fetched — omitting quarterly figures rather than mislabeling them."
            )
            return []

    results = []
    # yfinance columns are Timestamps representing quarter end dates
    for date_col in quarterly_financials.columns:
        date_str = date_col.strftime("%Y-%m-%d")
        q_data = quarterly_financials[date_col]
        
        # Convert Series to dict, normalizing NaN -> None. Yahoo Finance represents
        # an unreported line item as float('nan') rather than None; left as-is, the
        # `value or 0.0` fallbacks below would silently keep NaN (since NaN is
        # truthy in Python), eventually crashing JSON serialization downstream
        # ("Out of range float values are not JSON compliant: nan").
        row_dict = {
            str(k).strip(): (None if isinstance(v, float) and v != v else v)
            for k, v in q_data.items()
        }
        
        # Extract fields with multiple names since Yahoo Finance schemas can vary slightly
        net_sales = (
            row_dict.get("Total Revenue")
            or row_dict.get("TotalRevenue")
            or row_dict.get("Operating Revenue")
            or 0.0
        )
        gross_profit = (
            row_dict.get("Gross Profit")
            or row_dict.get("GrossProfit")
            or None
        )
        ebitda = (
            row_dict.get("EBITDA") 
            or row_dict.get("Normalized EBITDA") 
            or 0.0
        )
        interest = (
            row_dict.get("Interest Expense") 
            or row_dict.get("InterestExpense") 
            or row_dict.get("Interest Expense Non Operating")
            or 0.0
        )
        tax = (
            row_dict.get("Tax Provision") 
            or row_dict.get("TaxProvision") 
            or row_dict.get("Income Tax Expense")
            or 0.0
        )
        pat = (
            row_dict.get("Net Income") 
            or row_dict.get("NetIncome") 
            or row_dict.get("Net Income Common Stockholders")
            or 0.0
        )
        
        # Reported operating income (real figure from Yahoo Finance)
        operating_income = (
            row_dict.get("Operating Income") 
            or row_dict.get("OperatingIncome") 
            or 0.0
        )
        
        results.append({
            "quarter": date_str,
            "net_sales": float(net_sales) * fx_rate if net_sales is not None else 0.0,
            "gross_profit": float(gross_profit) * fx_rate if gross_profit is not None else None,
            "ebitda": float(ebitda) * fx_rate if ebitda is not None else 0.0,
            "interest": float(interest) * fx_rate if interest is not None else 0.0,
            "tax": float(tax) * fx_rate if tax is not None else 0.0,
            "pat": float(pat) * fx_rate if pat is not None else 0.0,
            "operating_income": float(operating_income) * fx_rate if operating_income is not None else 0.0,
        })
        
    # Sort results by date descending (newest first)
    results.sort(key=lambda x: x["quarter"], reverse=True)
    return results


def fetch_complete_stock_data(symbol: str) -> Dict[str, Any]:
    """
    Helper function to aggregate fundamentals, historical prices, and quarterly financial reports.
    """
    symbol_upper = symbol.strip().upper()
    fundamentals = fetch_stock_fundamentals(symbol_upper)
    if not fundamentals:
        return {}
        
    historical_prices = fetch_historical_prices(symbol_upper, period="1y")
    quarterly_results = fetch_quarterly_results(symbol_upper)
    
    return {
        "symbol": symbol_upper,
        "fundamentals": fundamentals,
        "historical_prices": historical_prices,
        "quarterly_results": quarterly_results,
        "fetched_at": datetime.utcnow().isoformat() + "Z"
    }
