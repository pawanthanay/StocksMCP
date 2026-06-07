"""
Lightweight Gemini REST client for AI-powered stock summary generation.

Calls the generativelanguage REST endpoint directly via ``httpx`` (already a
project dependency) using a user-supplied API key — no SDK installation
required. The key is only ever forwarded to Google's API for this request;
it is never persisted by the server.
"""

import logging
from typing import Any, Optional

import httpx

logger = logging.getLogger(__name__)

# Tried in order — the first model that responds successfully wins.
GEMINI_MODELS = ["gemini-2.0-flash", "gemini-1.5-flash"]
GEMINI_ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def _build_prompt(symbol: str, fundamentals: dict, calculated: dict, quarterly: list) -> str:
    fair = calculated.get("fair_price_data", {})
    latest_q = quarterly[0] if quarterly else {}
    prev_q = quarterly[1] if len(quarterly) > 1 else {}

    return (
        "You are a professional equity research analyst. Write a concise, "
        "specific 4-6 sentence analysis of the stock below for a retail "
        "investor dashboard. Reference the actual figures provided, and cover "
        "the growth trajectory, balance-sheet health, shareholding stability, "
        "and whether the stock looks undervalued or overvalued versus its fair "
        "price. Do not add disclaimers or mention that you are an AI.\n\n"
        f"Company: {fundamentals.get('company_name', symbol)} ({symbol})\n"
        f"Sector: {fundamentals.get('sector', 'N/A')} / {fundamentals.get('industry', 'N/A')}\n"
        f"Growth Score: {calculated.get('growth_score', 'N/A')}/10 "
        f"({calculated.get('growth_status', 'N/A')})\n"
        f"CMP: Rs {fundamentals.get('current_price', 'N/A')}  "
        f"Fair Price: Rs {fair.get('fair_price', 'N/A')}  "
        f"Gap: {fair.get('gap_percentage', 'N/A')}%\n"
        f"PE: {fundamentals.get('pe_ratio', 'N/A')}  PB: {fundamentals.get('pb_ratio', 'N/A')}  "
        f"ROE: {fundamentals.get('roe', 'N/A')}%  ROCE: {fundamentals.get('roce', 'N/A')}%  "
        f"D/E: {fundamentals.get('debt_to_equity', 'N/A')}\n"
        f"Promoter/Insider Holding: {fundamentals.get('promoter_holding', 'N/A')}%  "
        f"Institutional Holding (FII+DII+MF combined): {fundamentals.get('institutional_holding', 'N/A')}%  "
        f"Institutional Holders Count: {fundamentals.get('institutional_holders_count', 'N/A')}\n"
        f"Latest Quarter ({latest_q.get('quarter', 'N/A')}): "
        f"Net Sales Rs {latest_q.get('net_sales', 'N/A')} Cr, "
        f"PAT Rs {latest_q.get('pat', 'N/A')} Cr, NPM {latest_q.get('npm', 'N/A')}%\n"
        f"Previous Quarter ({prev_q.get('quarter', 'N/A')}): "
        f"Net Sales Rs {prev_q.get('net_sales', 'N/A')} Cr, "
        f"PAT Rs {prev_q.get('pat', 'N/A')} Cr\n"
    )


async def generate_ai_summary_with_gemini(
    symbol: str,
    fundamentals: dict,
    calculated_metrics: dict,
    quarterly_results: list,
    api_key: str,
    timeout: float = 25.0,
) -> Optional[str]:
    """
    Ask Gemini (using the caller-supplied API key) for an analyst-style summary.

    Returns the generated text, or ``None`` if the key is missing/invalid or
    the request fails for any reason — callers should fall back to the
    rule-based summary in that case.
    """
    if not api_key or not api_key.strip():
        return None

    prompt = _build_prompt(symbol, fundamentals, calculated_metrics, quarterly_results)
    payload: dict[str, Any] = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.4, "maxOutputTokens": 400},
    }

    async with httpx.AsyncClient(timeout=timeout) as client:
        for model in GEMINI_MODELS:
            url = GEMINI_ENDPOINT.format(model=model)
            try:
                resp = await client.post(url, params={"key": api_key.strip()}, json=payload)
                if resp.status_code == 404:
                    continue  # model not available for this key/region — try the next one
                if resp.status_code in (400, 401, 403):
                    logger.warning("Gemini rejected the request for %s (HTTP %s) — likely an invalid API key.", symbol, resp.status_code)
                    return None
                resp.raise_for_status()

                data = resp.json()
                candidates = data.get("candidates", [])
                if not candidates:
                    logger.warning("Gemini returned no candidates for %s", symbol)
                    return None

                parts = candidates[0].get("content", {}).get("parts", [])
                text = "".join(part.get("text", "") for part in parts).strip()
                return text or None
            except httpx.HTTPError as e:
                logger.warning("Gemini request failed for %s using %s: %s", symbol, model, e)

    return None
