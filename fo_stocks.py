"""
fo_stocks.py — Build and maintain the F&O stock universe.

Architecture
------------
The F&O list is stored in fo_symbols.json inside the repo and updated
automatically by a weekly GitHub Actions workflow (update_fo_list.yml).
The main scraper always reads from this file — so it is fast, reliable,
and never blocked by NSE's IP restrictions.

Source priority for the weekly updater
---------------------------------------
1. NSE fo_mktlots.csv (public archive, no auth needed)
2. NSE equity-stockIndices API (needs session cookies)
3. Hard-coded fallback (~267 stocks) — written to fo_symbols.json
   so even a failed update leaves a valid file
"""

import io
import json
import os
from typing import List, Dict

import requests
import pandas as pd

import config
from utils import setup_logger, retry

log = setup_logger("fo_stocks")

FO_SYMBOLS_FILE = os.path.join(os.path.dirname(__file__), "fo_symbols.json")
NSE_MKTLOTS_URL = "https://nsearchives.nseindia.com/content/fo/fo_mktlots.csv"


# ─── Read from repo file (used by main scraper every run) ────────────────────

def load_fo_symbols_from_file() -> List[Dict]:
    """Read the committed fo_symbols.json — fast, no network call needed."""
    try:
        with open(FO_SYMBOLS_FILE, "r") as f:
            data = json.load(f)
        symbols = data.get("symbols", [])
        log.info("✅ F&O universe loaded from fo_symbols.json: %d symbols "
                 "(last updated: %s).", len(symbols), data.get("updated", "unknown"))
        return symbols
    except FileNotFoundError:
        log.warning("fo_symbols.json not found — will use fallback.")
        return []
    except Exception as exc:
        log.warning("Could not read fo_symbols.json (%s) — will use fallback.", exc)
        return []


def save_fo_symbols_to_file(symbols: List[Dict]) -> None:
    """Write the updated symbol list to fo_symbols.json."""
    from datetime import datetime
    data = {
        "updated": datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC"),
        "count":   len(symbols),
        "symbols": symbols,
    }
    with open(FO_SYMBOLS_FILE, "w") as f:
        json.dump(data, f, indent=2)
    log.info("Saved %d symbols to fo_symbols.json.", len(symbols))


# ─── Fetch live list (used only by weekly updater) ───────────────────────────

@retry(max_tries=3, delay=8)
def fetch_fo_from_csv() -> List[Dict]:
    """
    Download NSE's fo_mktlots.csv (public, no auth required).
    NSE updates this file whenever F&O stocks change.
    """
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        ),
        "Referer": "https://www.nseindia.com/",
        "Accept":  "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    resp = requests.get(NSE_MKTLOTS_URL, headers=headers, timeout=20)
    resp.raise_for_status()

    df = pd.read_csv(io.StringIO(resp.text), header=0, skipinitialspace=True)
    first_col = df.columns[0]
    df = df.rename(columns={first_col: "SYMBOL"})

    symbols = []
    for _, row in df.iterrows():
        sym = str(row["SYMBOL"]).strip().upper()
        if (not sym or sym in ("SYMBOL", "UNDERLYING", "-", "NAN")
                or sym.startswith("#")):
            continue
        if sym in ("NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY",
                   "NIFTYNXT50", "SENSEX", "BANKEX"):
            continue
        lot = 0
        if len(df.columns) > 1:
            try:
                lot = int(str(row.iloc[1]).strip().replace(",", "") or 0)
            except (ValueError, TypeError):
                lot = 0
        symbols.append({"symbol": sym, "lot_size": lot, "name": "", "source": "nse_csv"})
    return symbols


@retry(max_tries=3, delay=8)
def fetch_fo_from_api(session: requests.Session) -> List[Dict]:
    """Fetch F&O symbols from NSE's live index API (needs session cookies)."""
    resp = session.get(config.NSE_FO_URL, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()
    try:
        data = resp.json()
    except Exception as exc:
        raise ValueError(f"NSE FO API JSON parse failed: {exc}")
    symbols = []
    for item in data.get("data", []):
        sym = item.get("symbol", "").strip().upper()
        if sym:
            symbols.append({
                "symbol": sym,
                "name":   item.get("meta", {}).get("companyName", ""),
                "source": "nse_api",
            })
    return symbols


# ─── Hard-coded fallback (~267 stocks) ───────────────────────────────────────

FALLBACK_FO_SYMBOLS = {
    # Nifty 50
    "RELIANCE", "TCS", "HDFCBANK", "BHARTIARTL", "ICICIBANK", "INFOSYS",
    "SBIN", "HINDUNILVR", "ITC", "LT", "KOTAKBANK", "BAJFINANCE",
    "HCLTECH", "MARUTI", "AXISBANK", "SUNPHARMA", "TITAN", "WIPRO",
    "ULTRACEMCO", "NESTLEIND", "POWERGRID", "NTPC", "ONGC", "TECHM",
    "TATACONSUM", "BAJAJFINSV", "COALINDIA", "ADANIPORTS", "ASIANPAINT",
    "DRREDDY", "JSWSTEEL", "TATAMOTORS", "HINDALCO", "CIPLA", "DIVISLAB",
    "GRASIM", "BRITANNIA", "APOLLOHOSP", "EICHERMOT", "HEROMOTOCO",
    "BAJAJ-AUTO", "M&M", "TATAPOWER", "ADANIENT", "BPCL", "INDUSINDBK",
    "SHRIRAMFIN", "HDFCLIFE", "SBILIFE", "VEDL",
    # Nifty Next 50
    "SIEMENS", "ABB", "HAVELLS", "PIDILITIND", "BERGEPAINT", "COLPAL",
    "DABUR", "MARICO", "GODREJCP", "MCDOWELL-N", "PAGEIND", "BOSCHLTD",
    "CHOLAFIN", "DLFINDIA", "DMART", "NAUKRI", "ZOMATO", "PAYTM",
    "IRCTC", "CONCOR", "RECLTD", "PFC", "IRFC", "HAL", "BEL",
    "BHEL", "NMDC", "SAIL", "NATIONALUM", "HINDZINC", "GAIL",
    "IOC", "HPCL", "PETRONET", "IGL", "MGL", "TVSMOTOR",
    "MOTHERSON", "BALKRISIND", "APOLLOTYRE", "CEATLTD", "MRF",
    "EXIDEIND", "POLYCAB", "KEI", "FINOLEX", "KALPATPOWR",
    # Midcap F&O
    "MPHASIS", "LTIM", "PERSISTENT", "COFORGE", "LTTS", "HEXAWARE",
    "OFSS", "INFOEDGE", "AFFLE", "ROUTE", "INDIAMART", "TANLA",
    "ZYDUSLIFE", "BIOCON", "LAURUSLABS", "AUROPHARMA", "TORNTPHARM",
    "ALKEM", "LUPIN", "IPCALAB", "GLENMARK", "NATCOPHARM", "GRANULES",
    "PIIND", "SUMICHEM", "AARTIIND", "DEEPAKFERT", "DEEPAKNTR", "GNFC",
    "CHAMBLFERT", "COROMANDEL", "TATACHEM", "ATUL", "NAVINFLUOR",
    "SRF", "LALPATHLAB", "METROPOLIS",
    "FEDERALBNK", "BANDHANBNK", "IDFCFIRSTB", "PNB", "CANBK",
    "BANKBARODA", "UNIONBANK", "RBLBANK", "YESBANK", "KARURVYSYA",
    "INDIACEM", "JKCEMENT", "RAMCOCEM", "HEIDELBERG",
    "VOLTAS", "BLUESTARCO", "WHIRLPOOL",
    "CUMMINSIND", "THERMAX", "KEC", "TORNTPOWER", "JSWENERGY",
    "TATACOMM", "IDEA", "MFSL", "ABCAPITAL",
    "BAJAJHLDNG", "M&MFIN", "MANAPPURAM", "MUTHOOTFIN",
    "SBICARD", "ICICIGI", "ICICIlombard", "NIACL", "STARHEALTH", "GICRE",
    "ADANIGREEN", "ADANITRANS", "ADANIPOWER", "AWL", "ATGL",
    "NYKAA", "POLICYBZR", "DELHIVERY", "MAPMYINDIA",
    "COCHINSHIP", "GRSE", "MAZAGON",
    "RAYMOND", "VEDANT", "MANYAVAR",
    "VBL", "UBL", "RADICO", "UNITDSPR", "PGHH",
    "KANSAINER", "INDIGO", "SPICEJET", "TATACOFFEE", "EMAMILTD",
    "IOLCP", "SUDARSCHEM", "RENUKA", "BALRAMCHIN",
    "OBEROIRLTY", "GODREJPROP", "PRESTIGE", "PHOENIXLTD", "BRIGADE",
    "IBREALEST", "SOBHA", "SUNTECK", "ABFRL", "TRENT", "SHOPERSTOP",
    "ZEEL", "SUNTV", "PVRINOX", "FORTIS", "MAXHEALTH", "NARAYANA",
    "GMRAIRPORT", "AIAENG", "ELGIEQUIP", "CROMPTON", "AMBER", "DIXON",
    "ASTRAL", "SUPREMEIND", "GHCL", "HFCL", "STLTECH", "TEJASNET",
    "JINDALSAW", "TATAMETALI", "RATNAMANI", "PNCINFRA", "KNRCON",
    "HGINFRA", "FLUOROCHEM", "CDSL", "BSE", "MCX", "ANGELONE",
    "IIFLWAM", "360ONE", "MOTILALOFS", "UJJIVANSFB", "BIKAJI",
    "DEVYANI", "WESTLIFE", "ESCORTS", "TIINDIA", "JBCHEPHARM",
    "GLAND", "ERIS", "POWERINDIA", "EQUITASBNK", "RAINBOW",
}


# ─── Public interfaces ────────────────────────────────────────────────────────

def build_fo_universe(session: requests.Session) -> List[Dict]:
    """
    Called by the main scraper every 30 min.
    Reads from fo_symbols.json — fast, zero network calls.
    Falls back to hard-coded list if the file is missing.
    """
    stocks = load_fo_symbols_from_file()
    if len(stocks) > 100:
        return stocks

    # File missing or empty — use fallback until weekly updater runs
    log.warning("⚠️  fo_symbols.json missing/empty — using hard-coded fallback (%d symbols).",
                len(FALLBACK_FO_SYMBOLS))
    return [{"symbol": s, "name": "", "source": "fallback"} for s in FALLBACK_FO_SYMBOLS]


def update_fo_universe(session: requests.Session) -> int:
    """
    Called ONLY by the weekly updater workflow.
    Fetches the live list, saves to fo_symbols.json, returns symbol count.
    """
    stocks = None

    # Try CSV first
    try:
        stocks = fetch_fo_from_csv()
        if len(stocks) > 100:
            log.info("Weekly update: got %d symbols from NSE CSV.", len(stocks))
    except Exception as exc:
        log.warning("Weekly CSV fetch failed: %s", exc)

    # Try API if CSV failed
    if not stocks or len(stocks) <= 100:
        try:
            stocks = fetch_fo_from_api(session)
            if len(stocks) > 100:
                log.info("Weekly update: got %d symbols from NSE API.", len(stocks))
        except Exception as exc:
            log.warning("Weekly API fetch failed: %s", exc)

    # Use fallback if both failed
    if not stocks or len(stocks) <= 100:
        log.warning("Weekly update: all sources failed — writing fallback list.")
        stocks = [{"symbol": s, "name": "", "source": "fallback"}
                  for s in FALLBACK_FO_SYMBOLS]

    save_fo_symbols_to_file(stocks)
    return len(stocks)
