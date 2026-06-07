"""
MCP Client Agent for Stock Research.
Implements the automatic agent workflow that connects to the StockResearchServer,
calls fetch_stock_data, runs analysis, saves the report via save_stock_report,
and renders the dashboard using show_dashboard.
"""

import asyncio
import logging
import sys
from pathlib import Path
from typing import Dict, Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

# Ensure the parent directory is in the path to resolve imports correctly
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.analyzer import build_complete_report
from src.symbol_resolver import resolve_symbol_from_prompt

# Configure logging to console
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


async def run_stock_agent_workflow(prompt: str):
    """
    Main agent workflow:
    1. Parse symbol from prompt.
    2. Start the StockResearchServer via stdio.
    3. Call fetch_stock_data tool on the server.
    4. Compile the analysis report (build_complete_report).
    5. Call save_stock_report tool on the server to persist JSON.
    6. Call show_dashboard tool on the server to get dashboard details.
    7. Generate the final AI response to show the user.
    """
    symbol = resolve_symbol_from_prompt(prompt)
    logger.info(f"Resolved symbol: '{symbol}' from user prompt: '{prompt}'")

    # Define server parameters to start the server as a subprocess
    server_script = str(Path(__file__).parent / "server.py")
    server_params = StdioServerParameters(
        command="python3",
        args=[server_script],
        env=None
    )

    logger.info("Initializing connection to StockResearchServer...")
    
    async with stdio_client(server_params) as (read_channel, write_channel):
        async with ClientSession(read_channel, write_channel) as session:
            # 1. Initialize session
            logger.info("Initializing MCP Client Session...")
            await session.initialize()
            
            # List available tools to verify
            tools = await session.list_tools()
            tool_names = [t.name for t in tools.tools]
            logger.info(f"Server initialized successfully. Exposed tools: {tool_names}")
            
            # 2. STEP 1: Invoke fetch_stock_data tool
            logger.info(f"Executing tool [fetch_stock_data] for {symbol}...")
            fetch_result = await session.call_tool("fetch_stock_data", arguments={"symbol": symbol})
            
            # Parse the content
            # FastMCP returns a list of Content objects, typically TextContent
            if not fetch_result.content or len(fetch_result.content) == 0:
                logger.error("Empty response returned from fetch_stock_data tool")
                return
                
            import json
            raw_text = fetch_result.content[0].text
            raw_data = json.loads(raw_text)
            
            if "error" in raw_data:
                logger.error(f"Error returned from fetch_stock_data: {raw_data['error']}")
                print(f"\nFailed to analyze {symbol}: {raw_data['error']}")
                return

            logger.info("Successfully fetched fundamentals and historical stock data.")
            
            # 3. Compile full report
            # The agent compiles the calculated metrics and AI summary
            logger.info("Calculating growth score, fair price, and AI analysis summary...")
            report = build_complete_report(symbol, raw_data)
            
            # 4. STEP 2: Invoke save_stock_report tool
            logger.info(f"Executing tool [save_stock_report] to persist report locally...")
            save_result = await session.call_tool(
                "save_stock_report", 
                arguments={"symbol": symbol, "report": report}
            )
            logger.info(f"Save report response: {save_result.content[0].text}")
            
            # 5. STEP 3: Invoke show_dashboard tool (Prefab UI / Layout builder)
            logger.info(f"Executing tool [show_dashboard] to generate dashboard...")
            dashboard_result = await session.call_tool("show_dashboard", arguments={"symbol": symbol})
            logger.info("Dashboard compiled successfully on server.")
            
            # 6. Print final AI Response
            print("\n" + "="*80)
            print("                     STOCK RESEARCH TERMINAL - ANALYSIS REPORT")
            print("="*80)
            print(f"Company: {report['company_name']} ({report['symbol']})")
            print(f"Sector:  {report['fundamentals']['sector']} | Industry: {report['fundamentals']['industry']}")
            print(f"Price:   ₹{report['fundamentals']['current_price']:,.2f} | Growth Status: {report['calculated_metrics']['growth_status'].upper()}")
            print("-"*80)
            print("🤖 AI SYSTEM REPORT SUMMARY:")
            print(report["ai_summary"])
            print("-"*80)
            print("📊 METRIC BREAKDOWN:")
            print(f"- Growth Score: {report['calculated_metrics']['growth_score']}/10")
            print(f"- Fair Price:   ₹{report['calculated_metrics']['fair_price_data']['fair_price']:,.2f}")
            print(f"- Gap Status:   {report['calculated_metrics']['fair_price_data']['gap_percentage']:+.2f}%")
            print(f"- Debt/Equity:  {report['fundamentals']['debt_to_equity'] if report['fundamentals']['debt_to_equity'] else 'N/A'}")
            promoter_pct = report['fundamentals']['promoter_holding']
            institutional_pct = report['fundamentals']['institutional_holding']
            print(f"- Promoter/Insider %: {promoter_pct if promoter_pct is not None else 'N/A'}  |  Institutional %: {institutional_pct if institutional_pct is not None else 'N/A'}")
            print("="*80)
            print("✓ REPORT GENERATED AND PERSISTED LOCALLY.")
            print("✓ DASHBOARD RENDERED AND REGISTERED TO PREFAB PROTOCOL.")
            print("="*80 + "\n")


if __name__ == "__main__":
    # Get user prompt from argument if provided, else prompt
    import argparse
    parser = argparse.ArgumentParser(description="MCP Stock Research Client Agent")
    parser.add_argument("prompt", nargs="?", type=str, default="Analyze National Aluminium stock", 
                        help="The analysis prompt containing the company name")
    args = parser.parse_args()
    
    asyncio.run(run_stock_agent_workflow(args.prompt))
