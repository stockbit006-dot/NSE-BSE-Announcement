"""
fo_stocks.py — Build and maintain the F&O stock universe.

Strategy
--------
1. Primary  : NSE /api/equity-stockIndices?index=SECURITIES IN F&O
2. Fallback : Hard-coded list of ~200 liquid F&O stocks (always available)
              so the bot never silently drops alerts due to a stale API.
"""

from typing import List, Dict
import requests

import config
from utils import setup_logger, retry

log = setup_logger("fo_stocks")

# ─── Hard-coded fallback universe ────────────────────────────────────────────
# This list is refreshed periodically; keep it up to date as a backstop.
FALLBACK_FO_SYMBOLS = {
    "RELIANCE", "TCS", "INFY", "HDFCBANK", "ICICIBANK", "KOTAKBANK",
    "AXISBANK", "SBIN", "BAJFINANCE", "BAJAJFINSV", "LT", "WIPRO",
    "HCLTECH", "ASIANPAINT", "MARUTI", "TITAN", "ULTRACEMCO", "NESTLEIND",
    "POWERGRID", "NTPC", "ONGC", "COALINDIA", "JSWSTEEL", "TATASTEEL",
    "HINDALCO", "GRASIM", "CIPLA", "DRREDDY", "SUNPHARMA", "DIVISLAB",
    "APOLLOHOSP", "TECHM", "MPHASIS", "LTIM", "PERSISTENT", "COFORGE",
    "INDUSINDBK", "FEDERALBNK", "BANDHANBNK", "IDFCFIRSTB", "PNB",
    "CANBK", "BANKBARODA", "UNIONBANK", "M&M", "TATAMOTORS", "HEROMOTOCO",
    "BAJAJ-AUTO", "EICHERMOT", "BOSCHLTD", "TVSMOTOR", "MOTHERSON",
    "BALKRISIND", "APOLLOTYRE", "MRF", "EXIDEIND", "BHARTIARTL", "IDEA",
    "VEDL", "SAIL", "NMDC", "NATIONALUM", "HINDZINC", "PETRONET",
    "BPCL", "IOC", "HPCL", "GAIL", "IGL", "MGL", "MFSL", "ABCAPITAL",
    "RECLTD", "PFC", "IRFC", "HINDUNILVR", "ITC", "MARICO", "GODREJCP",
    "DABUR", "COLPAL", "EMAMILTD", "TATACONSUM", "BRITANNIA", "VBL",
    "UBL", "MCDOWELL-N", "RADICO", "PIDILITIND", "BERGEPAINT", "KANSAINER",
    "LALPATHLAB", "METROPOLIS", "LTTS", "HEXAWARE", "OFSS", "INFOEDGE",
    "JUSTDIAL", "ZOMATO", "PAYTM", "NYKAA", "POLICYBZR", "DELHIVERY",
    "IRCTC", "CONCOR", "ADANIPORTS", "ADANIENT", "ADANIGREEN", "ADANITRANS",
    "ADANIPOWER", "AWL", "ATGL", "SIEMENS", "ABB", "BHEL", "BEL",
    "HAL", "COCHINSHIP", "GRSE", "MAZDA", "AUROPHARMA", "TORNTPHARM",
    "ALKEM", "LUPIN", "IPCALAB", "GLENMARK", "NATCOPHARM", "GRANULES",
    "PIIND", "SUMICHEM", "AARTIIND", "DEEPAKFERT", "DEEPAKNTR", "GNFC",
    "CHAMBLFERT", "COROMANDEL", "TATACHEM", "ATUL", "NAVINFLUOR",
    "SRF", "ALOKINDS", "RAYMOND", "PAGEIND", "VEDANT", "MANYAVAR",
    "ZYDUSLIFE", "BIOCON", "LAURUSLABS", "IOLCP", "SUDARSCHEM",
    "MINDTREE", "MPHL", "TANLA", "RBLBANK", "YESBANK", "KARURVYSYA",
    "CEATLTD", "JKCEMENT", "RAMCOCEM", "HEIDELBERG", "INDIACEM",
    "TATACOFFEE", "UNITDSPR", "PGHH", "WHIRLPOOL", "VOLTAS", "BLUESTARCO",
    "HAVELLS", "POLYCAB", "KEI", "FINOLEX", "SCHNEIDER", "CUMMINSIND",
    "THERMAX", "KEC", "KALPATPOWR", "TORNTPOWER", "TATAPOWER", "CESC",
    "JSWENERGY", "RENUKA", "BAJAJHLDNG", "CHOLAFIN", "M&MFIN", "SHRIRAMFIN",
    "MANAPPURAM", "MUTHOOTFIN", "SBICARD", "HDFCLIFE", "SBILIFE",
    "ICICIlombard", "NIACL", "STARHEALTH", "ICICIGI", "GICRE",
    "NAUKRI", "AFFLE", "ROUTE", "INDIAMART", "MAPMYINDIA",
}


@retry(max_tries=3, delay=5)
def fetch_nse_fo_symbols(session: requests.Session) -> List[Dict]:
    """Fetch F&O symbols from NSE's live index API."""
    resp = session.get(config.NSE_FO_URL, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    data = resp.json()

    symbols = []
    for item in data.get("data", []):
        sym = item.get("symbol", "").strip().upper()
        if sym:
            symbols.append({"symbol": sym, "name": item.get("meta", {}).get("companyName", ""), "source": "NSE"})
    return symbols


def build_fo_universe(session: requests.Session) -> List[Dict]:
    """
    Try to fetch live F&O universe from NSE.
    Fall back to hard-coded set if that fails.
    Returns list of dicts with 'symbol', 'name', 'source'.
    """
    try:
        live = fetch_nse_fo_symbols(session)
        if len(live) > 50:  # sanity check
            log.info("F&O universe fetched from NSE: %d symbols.", len(live))
            return live
        log.warning("NSE returned only %d symbols; supplementing with fallback.", len(live))
        live_syms = {s["symbol"] for s in live}
        extras = [
            {"symbol": s, "name": "", "source": "fallback"}
            for s in FALLBACK_FO_SYMBOLS
            if s not in live_syms
        ]
        return live + extras
    except Exception as exc:
        log.error("Failed to fetch NSE F&O universe (%s); using fallback.", exc)
        return [
            {"symbol": s, "name": "", "source": "fallback"}
            for s in FALLBACK_FO_SYMBOLS
        ]
