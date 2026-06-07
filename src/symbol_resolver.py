"""
Shared natural-language ticker resolution.

Used by both the MCP client agent and the web dashboard so that a free-text
company name (e.g. "National Aluminium", "Reliance", "Asian Paints") resolves
to the correct NSE ticker symbol regardless of entry point — and so that an
unrecognised name produces a clear error rather than silently substituting a
different company's data.
"""

import logging
import time
from typing import Dict, Optional

import yfinance as yf

logger = logging.getLogger(__name__)

# Yahoo Finance returns HTTP 429 ("Too Many Requests. Rate limited.") under
# bursty traffic — common on shared cloud-host IPs. It's transient, so a short
# bounded retry recovers most of these rather than wrongly telling a user
# "company not found" when Yahoo was simply rate-limiting us at that instant.
_RATE_LIMIT_RETRY_ATTEMPTS = 3
_RATE_LIMIT_RETRY_BASE_DELAY_SECONDS = 1.5


def _is_rate_limit_error(exc: BaseException) -> bool:
    text = str(exc)
    return "Too Many Requests" in text or "rate limit" in text.lower()


def _yf_call(fn, description: str):
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

# Curated aliases for short names/abbreviations that Yahoo Finance's own live
# search (`yf.Search`) demonstrably resolves wrong or not at all — verified by
# hand, e.g.:
#   "Reliance"  -> live search top NSE hit is Reliance Infrastructure, not
#                  Reliance Industries (India's largest company by market cap)
#   "SBI" / "HDFC" / "L&T" / "BEL" / "HUL" / "Titan" / "Tata Steel"
#               -> live search returns no NSE match at all (forex pairs, ADRs,
#                  foreign-exchange listings instead)
#   "Maruti"    -> live search ranks a small unrelated company (Jay Bharat
#                  Maruti) above Maruth Suzuki India
# Full/longer company names ("Reliance Industries", "Tata Steel Limited", ...)
# resolve correctly via live search on their own, so they're deliberately left
# out of this table — it only needs to plug the gaps.
#
# Keys are lowercase. Matching is prefix-based (see resolve_symbol_from_prompt):
# the alias must match the start of the query, and any remaining words must be
# generic filler ("ltd", "share price", ...) — this is what lets "Reliance"
# resolve to Reliance Industries while "Reliance Power"/"Reliance Capital"
# still fall through to live search and find the company actually named.
_ALIASES: Dict[str, str] = {
    "national aluminium": "NATIONALUM.NS",
    "national aluminium company": "NATIONALUM.NS",
    "nalco": "NATIONALUM.NS",
    "nationalum": "NATIONALUM.NS",
    "tata consultancy services": "TCS.NS",
    "tata consultancy": "TCS.NS",
    "tcs": "TCS.NS",
    "infosys": "INFY.NS",
    "infy": "INFY.NS",
    "reliance industries": "RELIANCE.NS",
    "reliance": "RELIANCE.NS",
    "ril": "RELIANCE.NS",
    "hdfc bank": "HDFCBANK.NS",
    "hdfc": "HDFCBANK.NS",
    "state bank of india": "SBIN.NS",
    "sbi": "SBIN.NS",
    "wipro": "WIPRO.NS",
    "axis bank": "AXISBANK.NS",
    "axis": "AXISBANK.NS",
    "hindustan unilever": "HINDUNILVR.NS",
    "hul": "HINDUNILVR.NS",
    "larsen and toubro": "LT.NS",
    "larsen & toubro": "LT.NS",
    "larsen": "LT.NS",
    "l&t": "LT.NS",
    "maruti suzuki": "MARUTI.NS",
    "maruti": "MARUTI.NS",
    "mahindra and mahindra": "M&M.NS",
    "mahindra & mahindra": "M&M.NS",
    "m&m": "M&M.NS",
    "tata motors": "TMPV.NS",
    "tamoto": "TMPV.NS",
    "tata steel": "TATASTEEL.NS",
    "sun pharma": "SUNPHARMA.NS",
    "sun pharmaceutical": "SUNPHARMA.NS",
    "titan": "TITAN.NS",
    "titan company": "TITAN.NS",
    "adani": "ADANIENT.NS",
    "adani enterprises": "ADANIENT.NS",
    "bel": "BEL.NS",
    "bharat electronics": "BEL.NS",
    "zomato": "ETERNAL.NS",  # Zomato Ltd renamed to Eternal Ltd in 2024; old "Zomato" ticker no longer trades
}

# Words that can trail a curated alias without changing what the user means
# (e.g. "Reliance Ltd", "TCS share price") — anything else trailing the alias
# ("Reliance Power", "Adani Power") signals a *different* company and must fall
# through to live search instead.
_GENERIC_SUFFIX_WORDS = {
    "ltd", "ltd.", "limited", "industries", "industry", "company", "co", "co.",
    "corporation", "corp", "stock", "share", "shares", "price", "prices",
    "india", "ind", "inc", "group", "the",
}

_KNOWN_NON_INDIAN_TICKERS = {"AAPL", "MSFT", "GOOG", "GOOGL", "TSLA", "NVDA", "AMZN", "META"}


def _alias_lookup(lowered_query: str) -> Optional[str]:
    tokens = lowered_query.replace(",", " ").replace(".", " ").split()
    best: Optional[str] = None
    for alias, symbol in _ALIASES.items():
        alias_tokens = alias.split()
        if tokens[: len(alias_tokens)] != alias_tokens:
            continue
        remainder = tokens[len(alias_tokens):]
        if all(word in _GENERIC_SUFFIX_WORDS for word in remainder):
            # Prefer the longest matching alias (e.g. "tata motors" over "tata")
            if best is None or len(alias_tokens) > len(best.split()):
                best = alias
    return _ALIASES[best] if best else None


def _is_resolvable(symbol: str) -> bool:
    """
    Confirms `symbol` identifies a real, currently-live company on Yahoo
    Finance. Presence of an `info` dict alone isn't sufficient — Yahoo returns
    a non-empty-but-useless stub like ``{'trailingPegRatio': None}`` for
    delisted/renamed tickers (e.g. the pre-demerger "TATAMOTORS.NS"), which
    would otherwise look "valid" while serving no real company data.
    """
    try:
        info = _yf_call(lambda: yf.Ticker(symbol).info, f"{symbol} resolvability check") or {}
    except Exception:
        return False
    has_identity = bool(info.get("longName") or info.get("shortName"))
    has_price = bool(info.get("currentPrice") or info.get("regularMarketPrice") or info.get("navPrice"))
    return has_identity or has_price


def _search_live(query: str) -> Optional[str]:
    """
    Live company-name search against Yahoo Finance for names not covered by
    the curated alias table — covers the long tail (mid/small caps, less common
    names) where Yahoo's search is reliable. Prefers NSE (.NS) listings, falls
    back to BSE (.BO), and only returns a candidate confirmed to resolve live —
    never an unverified guess.
    """
    try:
        results = _yf_call(lambda: yf.Search(query, max_results=15).quotes, f"live search '{query}'")
    except Exception as e:
        logger.warning(f"Live symbol search failed for '{query}': {e}")
        return None

    symbols = [str(r.get("symbol", "")) for r in results if r.get("symbol")]
    ordered = [s for s in symbols if s.endswith(".NS")] + [s for s in symbols if s.endswith(".BO")]
    for symbol in ordered:
        if _is_resolvable(symbol):
            return symbol
    return None


def resolve_symbol_from_prompt(prompt: str) -> str:
    """
    Resolve a free-text company name or ticker to a live NSE/BSE symbol.

    Resolution order:
      1. Curated alias table — short names/abbreviations Yahoo's own search
         gets wrong (see _ALIASES).
      2. Direct ticker guess — if the text already looks like a symbol
         ("TCS", "M&M", "INFY.NS"), try it directly; only used if it actually
         resolves to a live company.
      3. Live company-name search — covers everything else.

    Raises ValueError if none of the above resolves to a real company. We never
    fall back to an unrelated symbol — showing one company's genuine data under
    another company's name would be worse than showing an error.
    """
    cleaned = prompt.strip()
    if not cleaned:
        raise ValueError("Please enter a stock name or symbol to research.")

    lowered = cleaned.lower()

    alias_match = _alias_lookup(lowered)
    if alias_match:
        return alias_match

    candidate = cleaned.upper().replace(" ", "")
    if candidate.endswith(".NS") or candidate.endswith(".BO"):
        if _is_resolvable(candidate):
            return candidate
    elif candidate in _KNOWN_NON_INDIAN_TICKERS:
        if _is_resolvable(candidate):
            return candidate
    elif 1 < len(candidate) <= 12 and all(c.isalnum() or c in "&-" for c in candidate):
        guess = f"{candidate}.NS"
        if _is_resolvable(guess):
            return guess

    found = _search_live(cleaned)
    if found:
        return found

    raise ValueError(
        f"Could not find a listed company matching \"{prompt}\". "
        f"Try the full company name (e.g. \"Reliance Industries\") or its exact "
        f"NSE ticker (e.g. \"RELIANCE.NS\")."
    )
