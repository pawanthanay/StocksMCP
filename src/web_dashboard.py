"""
FastAPI application to serve the interactive web dashboard 
and provide API endpoints for stock analysis, report storage, and comparisons.
"""

import logging
import sys
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

# Add parent directory to path to resolve imports correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_fetcher import fetch_complete_stock_data
from src.report_manager import (
    save_stock_report,
    read_stock_report,
    delete_stock_report,
    list_stock_reports
)
from src.analyzer import build_complete_report
from src.gemini_client import generate_ai_summary_with_gemini
from src.symbol_resolver import resolve_symbol_from_prompt

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

app = FastAPI(
    title="School Of Equity API",
    description="Backend API powering the School Of Equity stock research dashboard",
    version="1.0.0"
)

# Enable CORS for cross-origin local requests
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Setup templates directory
BASE_DIR = Path(__file__).parent.parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))


class StartResearchRequest(BaseModel):
    """Body for POST /api/start — free-text stock query plus an optional Gemini API key."""
    stock_query: str
    api_key: Optional[str] = None


async def _run_full_analysis(symbol: str, api_key: Optional[str] = None) -> dict:
    """
    Shared pipeline: fetch live fundamentals, compute metrics, optionally
    upgrade the AI summary using the caller's Gemini API key, persist the
    report locally, and return it.
    """
    raw_data = fetch_complete_stock_data(symbol)
    if not raw_data:
        raise ValueError(f"Could not retrieve stock data for {symbol}. Check the symbol name.")

    report = build_complete_report(symbol, raw_data)

    if api_key:
        gemini_summary = await generate_ai_summary_with_gemini(
            symbol=symbol,
            fundamentals=report.get("fundamentals", {}),
            calculated_metrics=report.get("calculated_metrics", {}),
            quarterly_results=report.get("quarterly_metrics", []),
            api_key=api_key,
        )
        if gemini_summary:
            report["ai_summary"] = gemini_summary
            logger.info(f"Used Gemini-generated summary for {symbol}")
        else:
            logger.info(f"Gemini summary unavailable for {symbol}; keeping rule-based summary")

    save_stock_report(symbol, report)
    return report


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    """
    Renders the web dashboard HTML interface.
    """
    logger.info("Serving main dashboard page")
    return templates.TemplateResponse(request, "dashboard.html", {})


@app.post("/api/start")
async def start_research_endpoint(payload: StartResearchRequest):
    """
    Landing-page entry point: resolves a free-text stock name/symbol to a
    ticker, runs the full analysis (optionally using the user's Gemini API
    key for the AI summary), and returns both the resolved symbol and report
    so the frontend can open the dashboard directly.
    """
    query = (payload.stock_query or "").strip()
    if not query:
        raise HTTPException(status_code=400, detail="Please enter a stock name or symbol.")

    try:
        symbol = resolve_symbol_from_prompt(query)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))

    logger.info(f"Resolved start request '{query}' -> symbol '{symbol}'")

    try:
        report = await _run_full_analysis(symbol, payload.api_key)
        return {"symbol": symbol, "report": report}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error during start analysis of {symbol}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error analyzing {symbol}: {str(e)}"
        )


@app.get("/api/analyze/{symbol}")
async def analyze_stock_endpoint(symbol: str, x_gemini_api_key: Optional[str] = Header(default=None)):
    """
    Triggers yfinance fetch, calculates metrics/valuation, optionally
    upgrades the AI summary via Gemini (if an API key is supplied through
    the X-Gemini-Api-Key header), persists a report locally, and returns it.
    """
    symbol_clean = symbol.strip().upper()
    logger.info(f"Triggered analysis endpoint for symbol: {symbol_clean}")

    try:
        report = await _run_full_analysis(symbol_clean, x_gemini_api_key)
        return report
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error(f"Error during analysis of {symbol_clean}: {e}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal Server Error analyzing {symbol_clean}: {str(e)}"
        )


@app.get("/api/report/{symbol}")
async def get_saved_report(symbol: str):
    """
    Retrieves a previously saved JSON report from disk.
    """
    symbol_clean = symbol.strip().upper()
    logger.info(f"Reading saved report for: {symbol_clean}")
    try:
        report = read_stock_report(symbol_clean)
        return report
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read report: {str(e)}")


@app.get("/api/reports")
async def list_reports_endpoint():
    """
    Lists metadata for all saved stock reports on disk.
    """
    logger.info("Listing saved reports")
    try:
        return list_stock_reports()
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.delete("/api/report/{symbol}")
async def delete_report_endpoint(symbol: str):
    """
    Deletes a saved JSON report from disk.
    """
    symbol_clean = symbol.strip().upper()
    logger.info(f"Deleting report for: {symbol_clean}")
    try:
        deleted = delete_stock_report(symbol_clean)
        if not deleted:
            raise HTTPException(status_code=404, detail=f"No report found for {symbol_clean}")
        return {"status": "success", "message": f"Deleted report for {symbol_clean}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    import uvicorn
    import os
    # Hosting platforms like Render/Railway/Heroku inject PORT and require the
    # app to bind to it; WEB_DASHBOARD_PORT remains the override for local dev.
    port = int(os.environ.get("PORT") or os.environ.get("WEB_DASHBOARD_PORT", 8000))
    host = os.environ.get("WEB_DASHBOARD_HOST", "0.0.0.0")
    reload_enabled = os.environ.get("WEB_DASHBOARD_RELOAD", "true").lower() == "true"
    logger.info(f"Starting Web Dashboard server at http://{host}:{port}")
    uvicorn.run("src.web_dashboard:app", host=host, port=port, reload=reload_enabled)
