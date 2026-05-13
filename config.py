"""
config.py — Central configuration for the NSE/BSE Announcement Bot.
All tuneable constants live here. Secrets come from environment variables only.
"""

import os

# ─── Telegram ────────────────────────────────────────────────────────────────
TELEGRAM_TOKEN   = os.getenv("TELEGRAM_TOKEN", "")
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "")
TELEGRAM_API_BASE = "https://api.telegram.org/bot{token}/{method}"

# ─── Database ────────────────────────────────────────────────────────────────
DB_PATH = os.getenv("DB_PATH", "announcements.db")

# ─── NSE ─────────────────────────────────────────────────────────────────────
NSE_BASE_URL    = "https://www.nseindia.com"
NSE_HOME_URL    = "https://www.nseindia.com"
NSE_ANNOUNCE_URL = (
    "https://www.nseindia.com/api/corporate-announcements"
    "?index=equities&from_date=&to_date=&symbol=&issuer=&subject="
)
NSE_FO_URL = (
    "https://www.nseindia.com/api/equity-stockIndices"
    "?index=SECURITIES%20IN%20F%26O"
)

# ─── BSE ─────────────────────────────────────────────────────────────────────
BSE_ANNOUNCE_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/AnnGetAnnouncementDet/w"
    "?strCat=-1&strPrevDate=&strScrip=&strSearch=P&strToDate=&strType=C&subcategory=-1"
)
BSE_FO_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/FOunderlyings/w"
)

# ─── HTTP / Session ───────────────────────────────────────────────────────────
REQUEST_TIMEOUT  = 20          # seconds per request
MAX_RETRIES      = 3
RETRY_DELAY      = 5           # seconds between retries
SESSION_REFRESH_INTERVAL = 50  # refresh NSE session every N requests

BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":             "application/json, text/plain, */*",
    "Accept-Language":    "en-US,en;q=0.9,hi;q=0.8",
    "Accept-Encoding":    "gzip, deflate, br",
    "Referer":            "https://www.nseindia.com/",
    "Connection":         "keep-alive",
    "DNT":                "1",
    "sec-ch-ua":          '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "sec-ch-ua-mobile":   "?0",
    "sec-ch-ua-platform": '"Windows"',
    "sec-fetch-dest":     "empty",
    "sec-fetch-mode":     "cors",
    "sec-fetch-site":     "same-origin",
    "Cache-Control":      "no-cache",
    "Pragma":             "no-cache",
}

# BSE requires different origin headers
BSE_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept":          "application/json, text/plain, */*",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate, br",
    "Origin":          "https://www.bseindia.com",
    "Referer":         "https://www.bseindia.com/",
    "Connection":      "keep-alive",
    "sec-fetch-dest":  "empty",
    "sec-fetch-mode":  "cors",
    "sec-fetch-site":  "same-site",
}

# ─── Announcement lookback window ────────────────────────────────────────────
# How many hours back to consider announcements "new" on first cold run.
LOOKBACK_HOURS = 2

# ─── Categorisation keywords ──────────────────────────────────────────────────
# Format: { category_name: ([keywords], impact_score 1-10) }
CATEGORY_RULES = {
    "Quarterly Results": (
        ["quarterly result", "financial result", "q1 result", "q2 result",
         "q3 result", "q4 result", "annual result", "half year result",
         "unaudited result", "audited result", "standalone result",
         "consolidated result"], 8
    ),
    "Dividend": (
        ["dividend", "interim dividend", "final dividend", "special dividend",
         "dividend declared"], 7
    ),
    "Bonus Issue": (
        ["bonus share", "bonus issue", "bonus"], 8
    ),
    "Stock Split": (
        ["stock split", "share split", "sub-division", "subdivision"], 8
    ),
    "Board Meeting": (
        ["board meeting", "board of directors", "bom", "notice of board"], 5
    ),
    "Order Win": (
        ["order win", "order received", "contract awarded", "letter of award",
         "loa received", "new order", "work order", "purchase order"], 9
    ),
    "Promoter Activity": (
        ["promoter buying", "promoter selling", "promoter stake",
         "promoter acquisition", "promoter disposal", "creeping acquisition"], 7
    ),
    "Insider Trading": (
        ["insider trading", "upsi", "code of conduct", "trading window"], 4
    ),
    "Acquisition / Merger": (
        ["acquisition", "merger", "amalgamation", "takeover", "demerger",
         "scheme of arrangement", "slump sale"], 9
    ),
    "Buyback": (
        ["buyback", "buy-back", "share repurchase"], 8
    ),
    "Fund Raise": (
        ["rights issue", "preferential allotment", "qip", "fpo", "ipo",
         "fundraise", "fund raise", "capital raise", "ncd", "debenture"], 7
    ),
    "Debt / Rating": (
        ["credit rating", "rating upgrade", "rating downgrade",
         "rating reaffirmed", "loan", "debt", "npa"], 6
    ),
    "Regulatory / Legal": (
        ["sebi order", "court order", "show cause", "penalty", "fine",
         "nclt", "drat", "cci", "enforcement", "adjudication"], 8
    ),
}

# Fallback for unmatched announcements
DEFAULT_CATEGORY = "Miscellaneous"
DEFAULT_IMPACT   = 3

# Impact label mapping
IMPACT_LABELS = {
    range(1, 4):  ("🟢 Low",    "Low"),
    range(4, 7):  ("🟡 Medium", "Medium"),
    range(7, 11): ("🔴 High",   "High"),
}
