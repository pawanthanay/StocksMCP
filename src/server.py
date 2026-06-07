"""
FastMCP Server for the Stock Research Agent.
Exposes tools for:
- Data retrieval (fetch_stock_data)
- Local report CRUD (save_stock_report, read_stock_report, update_stock_report, delete_stock_report)
- Prefab UI dashboard (show_dashboard)
- Stock comparisons (compare_stocks)
"""

import logging
import sys
from pathlib import Path
from typing import Dict, Any, List

from fastmcp import FastMCP

# Ensure the parent directory is in the path to resolve imports correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.data_fetcher import fetch_complete_stock_data
from src.report_manager import (
    save_stock_report as save_report_to_disk,
    read_stock_report as read_report_from_disk,
    update_stock_report as update_report_on_disk,
    delete_stock_report as delete_report_from_disk,
    list_stock_reports
)
from src.analyzer import build_complete_report
from src.dashboard import build_prefab_dashboard, build_dashboard_data

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

# Initialize FastMCP Server
mcp = FastMCP("StockResearchServer")


@mcp.tool()
async def fetch_stock_data(symbol: str) -> Dict[str, Any]:
    """
    Fetch the latest fundamentals, quarterly financial results, and historical price data
    for a stock from yfinance. Use '.NS' suffix for Indian NSE stocks (e.g. TCS.NS).
    
    Args:
        symbol: The stock ticker symbol (e.g. NATIONALUM.NS, TCS.NS, AAPL).
    """
    logger.info(f"MCP Tool: fetch_stock_data for {symbol}")
    try:
        data = fetch_complete_stock_data(symbol)
        if not data:
            return {"error": f"Failed to retrieve data for symbol: {symbol}"}
        return data
    except Exception as e:
        logger.error(f"Error fetching stock data for {symbol}: {e}")
        return {"error": str(e)}


@mcp.tool()
async def save_stock_report(symbol: str, report: Dict[str, Any]) -> str:
    """
    Save a generated stock analysis report to local disk storage as a JSON file.
    
    Args:
        symbol: The stock symbol (used for file naming).
        report: The complete stock analysis report containing raw and calculated data.
    """
    logger.info(f"MCP Tool: save_stock_report for {symbol}")
    try:
        filepath = save_report_to_disk(symbol, report)
        return f"Successfully saved report for {symbol.upper()} to: {filepath}"
    except Exception as e:
        logger.error(f"Error saving report for {symbol}: {e}")
        return f"Error saving report: {str(e)}"


@mcp.tool()
async def read_stock_report(symbol: str) -> Dict[str, Any]:
    """
    Read and return a previously saved stock report from local disk storage.
    
    Args:
        symbol: The stock symbol of the report to retrieve.
    """
    logger.info(f"MCP Tool: read_stock_report for {symbol}")
    try:
        report = read_report_from_disk(symbol)
        return report
    except FileNotFoundError as e:
        return {"error": f"Report for {symbol} not found. Use fetch and save first."}
    except Exception as e:
        logger.error(f"Error reading report for {symbol}: {e}")
        return {"error": str(e)}


@mcp.tool()
async def update_stock_report(symbol: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Update specific fields or sections of an existing saved stock report on disk.
    
    Args:
        symbol: The stock symbol of the report to update.
        updates: A dictionary containing the keys and values to update.
    """
    logger.info(f"MCP Tool: update_stock_report for {symbol}")
    try:
        updated_report = update_report_on_disk(symbol, updates)
        return {
            "status": "success",
            "message": f"Successfully updated report for {symbol.upper()}",
            "updated_fields": list(updates.keys())
        }
    except FileNotFoundError:
        return {"error": f"No existing report found to update for symbol: {symbol}"}
    except Exception as e:
        logger.error(f"Error updating report for {symbol}: {e}")
        return {"error": str(e)}


@mcp.tool()
async def delete_stock_report(symbol: str) -> str:
    """
    Delete a saved stock report from local disk storage.
    
    Args:
        symbol: The stock symbol of the report to delete.
    """
    logger.info(f"MCP Tool: delete_stock_report for {symbol}")
    try:
        deleted = delete_report_from_disk(symbol)
        if deleted:
            return f"Successfully deleted report for {symbol.upper()}"
        return f"No report existed for {symbol.upper()}"
    except Exception as e:
        logger.error(f"Error deleting report for {symbol}: {e}")
        return f"Error: {str(e)}"


@mcp.tool()
async def list_saved_reports() -> List[Dict[str, Any]]:
    """
    Lists metadata summary for all stock analysis reports saved in local storage.
    """
    logger.info("MCP Tool: list_saved_reports")
    try:
        return list_stock_reports()
    except Exception as e:
        logger.error(f"Error listing reports: {e}")
        return []


@mcp.tool()
async def compare_stocks(symbol_a: str, symbol_b: str) -> Dict[str, Any]:
    """
    Perform a fundamental side-by-side comparison of two stock symbols.
    
    Args:
        symbol_a: First stock symbol (e.g. TCS.NS)
        symbol_b: Second stock symbol (e.g. INFY.NS)
    """
    logger.info(f"MCP Tool: compare_stocks for {symbol_a} and {symbol_b}")
    try:
        raw_a = fetch_complete_stock_data(symbol_a)
        raw_b = fetch_complete_stock_data(symbol_b)
        
        if not raw_a or not raw_b:
            return {"error": "Failed to fetch data for one or both stocks."}
            
        report_a = build_complete_report(symbol_a, raw_a)
        report_b = build_complete_report(symbol_b, raw_b)
        
        # Save both reports as part of the analysis process
        save_report_to_disk(symbol_a, report_a)
        save_report_to_disk(symbol_b, report_b)
        
        # Extract comparison view
        comparison = {
            "symbol_a": report_a["symbol"],
            "company_a": report_a["company_name"],
            "growth_status_a": report_a["calculated_metrics"]["growth_status"],
            "growth_score_a": report_a["calculated_metrics"]["growth_score"],
            "cmp_a": report_a["fundamentals"]["current_price"],
            "fair_price_a": report_a["calculated_metrics"]["fair_price_data"]["fair_price"],
            "pe_a": report_a["fundamentals"]["pe_ratio"],
            
            "symbol_b": report_b["symbol"],
            "company_b": report_b["company_name"],
            "growth_status_b": report_b["calculated_metrics"]["growth_status"],
            "growth_score_b": report_b["calculated_metrics"]["growth_score"],
            "cmp_b": report_b["fundamentals"]["current_price"],
            "fair_price_b": report_b["calculated_metrics"]["fair_price_data"]["fair_price"],
            "pe_b": report_b["fundamentals"]["pe_ratio"],
        }
        return comparison
    except Exception as e:
        logger.error(f"Error comparing {symbol_a} and {symbol_b}: {e}")
        return {"error": str(e)}


@mcp.tool(app=True)
async def show_dashboard(symbol: str) -> Any:
    """
    Build and render an interactive stock analysis dashboard in the user interface.
    Fetches stock data, runs analysis, saves the report, and compiles the Prefab components.
    
    Args:
        symbol: The stock ticker symbol to analyze and display in the dashboard.
    """
    logger.info(f"MCP Tool: show_dashboard for {symbol}")
    symbol_clean = symbol.strip().upper()
    try:
        # 1. Fetch complete data
        raw_data = fetch_complete_stock_data(symbol_clean)
        if not raw_data:
            return {"error": f"Failed to retrieve stock data for {symbol_clean}"}
            
        # 2. Build analysis report
        report = build_complete_report(symbol_clean, raw_data)
        
        # 3. Save report locally
        save_report_to_disk(symbol_clean, report)
        
        # 4. Compile Prefab UI Component tree
        app = build_prefab_dashboard(report)
        return app
    except Exception as e:
        logger.error(f"Error building dashboard for {symbol_clean}: {e}", exc_info=True)
        return {"error": f"Failed to build dashboard: {str(e)}"}


if __name__ == "__main__":
    logger.info("Running FastMCP Server...")
    mcp.run()
