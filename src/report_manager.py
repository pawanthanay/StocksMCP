"""
Module for handling CRUD operations on stock research reports saved locally as JSON.
Saved files are stored in the reports/ directory.
"""

import json
import os
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, List, Optional

logger = logging.getLogger(__name__)

# Base directory for storing reports
REPORTS_DIR = Path(__file__).parent.parent / "reports"


def _ensure_reports_dir():
    """Ensure the reports directory exists."""
    if not REPORTS_DIR.exists():
        logger.info(f"Creating reports directory at {REPORTS_DIR}")
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)


def _clean_symbol(symbol: str) -> str:
    """Clean and normalize symbol name for file operations."""
    # Remove suffix like .NS or .BO for filename clean-ness, but keep it if requested.
    # Actually let's just replace dot with underscore or strip special characters to make it safe.
    clean = symbol.strip().upper()
    # Replace dot or special chars with underscore
    clean = clean.replace(".", "_").replace("/", "_")
    return clean


def save_stock_report(symbol: str, report: Dict[str, Any]) -> str:
    """
    Saves a stock research report to reports/{symbol}.json.
    Returns the absolute file path.
    """
    _ensure_reports_dir()
    clean_sym = _clean_symbol(symbol)
    filepath = REPORTS_DIR / f"{clean_sym}.json"
    
    # Enrich report with save metadata
    report["saved_at"] = datetime.utcnow().isoformat() + "Z"
    report["symbol"] = symbol.upper()
    
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info(f"Saved stock report for {symbol} to {filepath}")
        return str(filepath.resolve())
    except Exception as e:
        logger.error(f"Failed to save stock report for {symbol}: {e}")
        raise IOError(f"Failed to save report: {e}")


def read_stock_report(symbol: str) -> Dict[str, Any]:
    """
    Reads a stock research report from reports/{symbol}.json.
    Raises FileNotFoundError if report does not exist.
    """
    clean_sym = _clean_symbol(symbol)
    filepath = REPORTS_DIR / f"{clean_sym}.json"
    
    if not filepath.exists():
        logger.warning(f"Stock report for {symbol} not found at {filepath}")
        raise FileNotFoundError(f"No research report found for symbol: {symbol}")
        
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            report = json.load(f)
        logger.info(f"Successfully read stock report for {symbol}")
        return report
    except Exception as e:
        logger.error(f"Failed to read stock report for {symbol}: {e}")
        raise IOError(f"Failed to read report: {e}")


def update_stock_report(symbol: str, updates: Dict[str, Any]) -> Dict[str, Any]:
    """
    Updates an existing stock report with the provided dict updates.
    Overwrites conflicting keys.
    """
    # Read first to ensure it exists
    report = read_stock_report(symbol)
    
    # Merge updates
    report.update(updates)
    report["updated_at"] = datetime.utcnow().isoformat() + "Z"
    
    # Save back
    save_stock_report(symbol, report)
    return report


def delete_stock_report(symbol: str) -> bool:
    """
    Deletes a stock report from local storage.
    Returns True if file was deleted, False if it did not exist.
    """
    clean_sym = _clean_symbol(symbol)
    filepath = REPORTS_DIR / f"{clean_sym}.json"
    
    if not filepath.exists():
        logger.info(f"Attempted to delete report for {symbol}, but it doesn't exist.")
        return False
        
    try:
        os.remove(filepath)
        logger.info(f"Deleted stock report for {symbol} at {filepath}")
        return True
    except Exception as e:
        logger.error(f"Error deleting stock report for {symbol}: {e}")
        raise IOError(f"Failed to delete report: {e}")


def list_stock_reports() -> List[Dict[str, Any]]:
    """
    Lists all saved stock reports with basic metadata.
    Returns list of dicts with: symbol, company_name, saved_at, growth_status.
    """
    _ensure_reports_dir()
    reports = []
    
    for file in REPORTS_DIR.glob("*.json"):
        try:
            with open(file, "r", encoding="utf-8") as f:
                data = json.load(f)
                
            fundamentals = data.get("fundamentals", {})
            calculated = data.get("calculated_metrics", {})
            
            reports.append({
                "symbol": data.get("symbol", file.stem),
                "company_name": fundamentals.get("company_name") or data.get("company_name") or file.stem,
                "saved_at": data.get("saved_at", ""),
                "growth_status": calculated.get("growth_status") or data.get("growth_status") or "N/A",
                "filename": file.name
            })
        except Exception as e:
            logger.warning(f"Could not read report file {file.name}: {e}")
            continue
            
    # Sort by saved_at descending
    reports.sort(key=lambda x: x.get("saved_at", ""), reverse=True)
    return reports
