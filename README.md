# 📈 MCP Stock Research Agent & Dashboard

An AI-powered stock research platform built using the **Model Context Protocol (MCP)**. It implements a fully compliant FastMCP server exposing fundamental analysis, local file-based database CRUD tools, and a dynamic dashboard layout via the **Prefab UI** protocol, combined with a standalone **FastAPI + HTML5** interactive browser terminal.

---

## 🏗️ Architecture

```
                       User Prompt (e.g., "Analyze National Aluminium")
                                     │
                                     ▼
                              ┌──────────────┐
                              │  MCP Client  │
                              │   (Agent)    │
                              └──────┬───────┘
                                     │ (stdio connection)
                                     ▼
                              ┌──────────────┐
                              │  MCP Server  │
                              │  (FastMCP)   │
                              └──────┬───────┘
                                     │
         ┌───────────────────────────┼───────────────────────────┐
         ▼                           ▼                           ▼
┌─────────────────┐         ┌─────────────────┐         ┌─────────────────┐
│  Internet Tool  │         │    CRUD Tool    │         │     UI Tool     │
│                 │         │                 │         │   (Prefab UI)   │
│  yfinance API   │         │  local reports/ │         │  Generative App │
└─────────────────┘         └─────────────────┘         └─────────────────┘
```

The system is split into two access interfaces:
1. **MCP Protocol Interface**: For AI agent clients (like Claude Desktop) using Stdio transport and Prefab UI.
2. **Standalone Web Terminal**: A browser interface at `http://localhost:8000` presenting a fully responsive dark-themed terminal with real-time Plotly.js charts, quarterly indicators, and side-by-side stock comparisons.

---

## ⚡ Key Features

- **Internet Data Tool**: Real-time fundamentals, quarterly statement retrieval, and historical OHLCV pricing via `yfinance`.
- **Local CRUD Tool**: Persistent JSON storage for analyzed stocks under `reports/`.
- **UI Communication (Prefab UI)**: Exposes structural layout component trees (`show_dashboard`) to MCP-compatible rendering clients.
- **Valuation Estimation Model**: Calculates growth-adjusted fair PE, EPS, and valuation gap percentage.
- **Growth Scoring System**: Evaluates companies out of 10 points based on quarterly revenue/PAT trends, ROE, debt-to-equity, and promoter holdings.
- **Interactive Candlestick Charts**: Fully interactive Plotly.js charting (Zoom, Pan, Hover details, Date range slider).
- **Stock Comparison**: Compare two stocks side-by-side on all fundamental metrics.

---

## 🛠️ Setup Instructions

### 1. Prerequisites
- Python 3.8 or higher installed on your system.

### 2. Project Directory Installation
Clone or navigate to the project directory:
```bash
cd /Users/pawanthanay/Project/StocksMCP
```

### 3. Create a Virtual Environment and Install Dependencies
Initialize a Python virtual environment, activate it, and install all required modules (this also installs `prefab-ui`, the rendering engine behind the `show_dashboard` Prefab UI tool):
```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

> **macOS / Homebrew Python troubleshooting:** If `pip install` fails with
> `ImportError: ... Symbol not found: _XML_SetAllocTrackerActivationThreshold`
> (a known Homebrew Python 3.12 ↔ system `libexpat` mismatch), prefix your
> `pip`/`python3` commands with the Homebrew expat lib path, e.g.:
> ```bash
> export DYLD_LIBRARY_PATH="$(brew --prefix expat)/lib:$DYLD_LIBRARY_PATH"
> pip install -r requirements.txt
> ```

### 4. Configuration
Create a `.env` file from the example:
```bash
cp .env.example .env
```

---

## 🚀 Running the Application

### Option A: Running the Standalone Web Dashboard (Recommended)
This starts the FastAPI web server. You can view the dashboard in any standard browser:
```bash
python3 -m src.web_dashboard
```
Once started, open your browser and go to:
👉 **[http://localhost:8000](http://localhost:8000)**

Select stocks from the dropdown (e.g. *National Aluminium*, *TCS*, *Infosys*) to perform live analysis, view interactive Plotly candlestick charts, read AI-generated summaries, and run comparisons.

### Option B: Running the MCP Client Agent (Automatic Workflow)
Run the client script to execute the agentic loop. The agent connects to the server, fetches data, performs calculations, saves the JSON report, and registers the Prefab dashboard:
```bash
python3 -m src.client "Analyze National Aluminium stock"
```

To run a different stock, pass it in the prompt:
```bash
python3 -m src.client "Analyze TCS stock"
```

### Option C: Testing the MCP Server Directly
To run the server in stdio mode (for Claude Desktop or testing):
```bash
python3 -m src.server
```

---

## 📊 Growth Scoring System

Ratios are checked and scored out of 10 points:
- **Revenue Growth QoQ**: Growing = 2 points, Flat = 1 point, Declining = 0 points
- **PAT Growth QoQ**: Growing = 2 points, Flat = 1 point, Declining = 0 points
- **ROE (Return on Equity)**: >15% = 2 points, 10-15% = 1 point, <10% = 0 points
- **Debt-to-Equity**: <50% (0.5) = 2 points, 50-100% (0.5-1.0) = 1 point, >100% = 0 points
- **Promoter Holdings**: >=50% = 2 points, 30-50% = 1 point, <30% = 0 points

**Growth Categories**:
- **0-4 Points**: 🔴 **Weak**
- **5-7 Points**: 🟡 **Neutral**
- **8-10 Points**: 🟢 **Growth**

---

## 📁 Project Structure

```
StocksMCP/
├── requirements.txt            # Python dependencies (fastmcp, yfinance, fastapi, etc.)
├── .env.example                # Template for server & dashboard config
├── .gitignore                  # Git rules (ignoring .env and reports/*.json)
├── reports/                    # Directory where local JSON reports are saved
│   └── NATIONALUM_NS.json      # Sample generated report
├── src/
│   ├── __init__.py             # Package init
│   ├── server.py               # FastMCP Server containing tool endpoints
│   ├── client.py               # MCP client agent running automatic pipelines
│   ├── data_fetcher.py         # yfinance scraper & parser
│   ├── analyzer.py             # Computes fair value, growth scores, & AI summaries
│   ├── dashboard.py            # Prefab UI layout compiler
│   └── web_dashboard.py        # FastAPI server backend
└── templates/
    └── dashboard.html          # HTML5 terminal dashboard with Plotly charts
```

---

## 📈 Verification Checklist

To verify all requirements are met:
1. **Tool 1: fetch_stock_data**: Call `fetch_stock_data("NATIONALUM.NS")` → returns raw stock fundamentals, financials, and historical price history.
2. **Tool 2: save_stock_report**: Call `save_stock_report("NATIONALUM", report)` → creates `reports/NATIONALUM_NS.json` with calculated metrics, AI summary, and raw data.
3. **Tool 3: show_dashboard**: Call `show_dashboard("NATIONALUM.NS")` → registers and returns structural generative UI.
4. **CRUD CRUD CRUD**: Test update/delete tools (`update_stock_report` and `delete_stock_report`).
5. **FastAPI Web Server**: Run `python3 -m src.web_dashboard` and inspect interactive elements at `http://localhost:8000`.
