"""
scraper.py — Main entry point.

Flow
----
1.  Init DB.
2.  Build a requests.Session with browser headers + NSE cookie bootstrap.
3.  Refresh F&O universe.
4.  Fetch NSE corporate announcements.
5.  Fetch BSE corporate announcements.
6.  Merge, filter to F&O, deduplicate, categorise.
7.  Insert new records into SQLite.
8.  Send Telegram alerts for any un-alerted rows.
9.  Log stats.

Run manually : python scraper.py
Run via CI   : GitHub Actions calls this every 5 minutes.
"""

import sys
import time
import hashlib
import requests
from datetime import datetime, timedelta
from typing import List, Dict, Optional

import config
import database as db
import fo_stocks as fo
import telegram_alert as tg
from utils import (
    setup_logger, retry, make_hash, categorise,
    parse_nse_dt, parse_bse_dt, now_ist_str,
)

log = setup_logger("scraper")


# ─── Session factory ──────────────────────────────────────────────────────────

def build_session() -> requests.Session:
    """
    Create a requests.Session that mimics a real browser.
    Visits NSE homepage + a secondary page to properly seed cookies.
    NSE blocks direct API calls from datacenter IPs without valid cookies.
    """
    sess = requests.Session()
    sess.headers.update(config.BROWSER_HEADERS)

    # Visit homepage
    log.info("Bootstrapping NSE session (visiting homepage)…")
    try:
        resp = sess.get(
            config.NSE_HOME_URL,
            timeout=config.REQUEST_TIMEOUT,
            allow_redirects=True,
        )
        log.info("NSE homepage status: %d | cookies: %s",
                 resp.status_code, list(sess.cookies.keys()))
        time.sleep(2)

        # Visit the corporate announcements page to get deeper cookies
        sess.get(
            "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            timeout=config.REQUEST_TIMEOUT,
        )
        time.sleep(1.5)
        log.info("NSE session warmed up. Cookies: %s", list(sess.cookies.keys()))
    except Exception as exc:
        log.warning("NSE homepage bootstrap failed (%s) — proceeding anyway.", exc)

    return sess


def refresh_session(sess: requests.Session) -> requests.Session:
    """Re-visit the NSE homepage to refresh the session cookies."""
    log.info("Refreshing NSE session…")
    try:
        sess.get(config.NSE_HOME_URL, timeout=config.REQUEST_TIMEOUT)
        time.sleep(2)
        sess.get(
            "https://www.nseindia.com/companies-listing/corporate-filings-announcements",
            timeout=config.REQUEST_TIMEOUT,
        )
        time.sleep(1)
    except Exception as exc:
        log.warning("Session refresh failed: %s", exc)
    return sess


# ─── NSE scraper ──────────────────────────────────────────────────────────────

@retry(max_tries=config.MAX_RETRIES, delay=config.RETRY_DELAY)
def _fetch_nse_raw(sess: requests.Session) -> List[Dict]:
    """Call NSE announcement API and return raw JSON list."""
    resp = sess.get(config.NSE_ANNOUNCE_URL, timeout=config.REQUEST_TIMEOUT)

    if resp.status_code == 401 or resp.status_code == 403:
        log.warning("NSE returned %d — refreshing session and retrying…", resp.status_code)
        refresh_session(sess)
        raise requests.HTTPError(f"{resp.status_code} — session refreshed, retry")

    resp.raise_for_status()

    # Guard: NSE sometimes returns an HTML error page with status 200
    ct = resp.headers.get("Content-Type", "")
    if "json" not in ct and len(resp.content) < 100:
        raise ValueError(f"NSE returned non-JSON content-type: {ct!r} body={resp.text[:80]!r}")

    try:
        data = resp.json()
    except Exception as exc:
        raise ValueError(f"NSE JSON parse failed: {exc} | body={resp.text[:120]!r}")

    return data if isinstance(data, list) else data.get("data", [])


def fetch_nse_announcements(sess: requests.Session, fo_syms: set) -> List[Dict]:
    """
    Fetch NSE announcements, filter to F&O, and normalise to internal schema.
    """
    log.info("Fetching NSE announcements…")
    try:
        raw = _fetch_nse_raw(sess)
    except Exception as exc:
        log.error("NSE fetch failed: %s", exc)
        return []

    results = []
    for item in raw:
        symbol = (item.get("symbol") or item.get("sm_isin") or "").strip().upper()
        if symbol not in fo_syms:
            continue

        headline     = (item.get("subject") or item.get("desc") or "").strip()
        company_name = (item.get("corp") or item.get("sm_name") or symbol).strip()
        ann_dt_raw   = (item.get("exchdisstime") or item.get("bm_date") or "")
        ann_dt       = parse_nse_dt(ann_dt_raw)

        # Build attachment URL
        attach   = item.get("attchmntFile") or item.get("attachment") or ""
        att_url  = (
            f"https://nsearchives.nseindia.com/corporate/{attach}"
            if attach and not attach.startswith("http")
            else attach
        )

        category, score, label = categorise(headline)
        h = make_hash("NSE", symbol, headline, ann_dt)

        results.append({
            "hash":           h,
            "exchange":       "NSE",
            "symbol":         symbol,
            "company_name":   company_name,
            "headline":       headline,
            "category":       category,
            "impact_score":   score,
            "impact_label":   label,
            "attachment_url": att_url,
            "ann_datetime":   ann_dt,
        })

    log.info("NSE: %d F&O announcements parsed.", len(results))
    return results


# ─── BSE scraper ──────────────────────────────────────────────────────────────

@retry(max_tries=config.MAX_RETRIES, delay=config.RETRY_DELAY)
def _fetch_bse_raw(sess: requests.Session) -> List[Dict]:
    """Call BSE announcement API and return raw JSON list."""
    # BSE needs its own Origin/Referer headers — use a fresh mini-session
    bse_sess = requests.Session()
    bse_sess.headers.update(config.BSE_HEADERS)

    resp = bse_sess.get(config.BSE_ANNOUNCE_URL, timeout=config.REQUEST_TIMEOUT)
    resp.raise_for_status()

    try:
        data = resp.json()
    except Exception as exc:
        raise ValueError(f"BSE JSON parse failed: {exc} | body={resp.text[:120]!r}")

    if isinstance(data, dict):
        return data.get("Table", data.get("data", []))
    return data if isinstance(data, list) else []


# NSE symbol ↔ BSE scrip code mapping helpers
# BSE uses numeric scrip codes; we match via company name fragments or a
# known static mapping for the most liquid names.

def _bse_symbol_from_item(item: Dict) -> Optional[str]:
    """
    Best-effort extraction of an NSE-style symbol from a BSE response item.
    BSE includes 'SCRIP_CD' (numeric) and 'SLONGNAME' / 'SSHORTNAME'.
    """
    short = (item.get("SCRIP_CD") or item.get("scrip_cd") or "").strip()
    nsym  = (item.get("NSE_SYMBOL") or item.get("nse_symbol") or "").strip().upper()
    if nsym:
        return nsym
    # Some fields carry the symbol directly
    for key in ("SYMBOL", "SCRIP_SYM", "symbol"):
        val = item.get(key, "").strip().upper()
        if val:
            return val
    return None


def fetch_bse_announcements(sess: requests.Session, fo_syms: set) -> List[Dict]:
    """
    Fetch BSE announcements, filter to F&O, and normalise.
    """
    log.info("Fetching BSE announcements…")
    try:
        raw = _fetch_bse_raw(sess)
    except Exception as exc:
        log.error("BSE fetch failed: %s", exc)
        return []

    results = []
    for item in raw:
        symbol = _bse_symbol_from_item(item)
        if not symbol or symbol not in fo_syms:
            continue

        headline     = (
            item.get("HEADLINE") or item.get("headline") or
            item.get("SUBJECT") or item.get("subject") or ""
        ).strip()
        company_name = (
            item.get("SLONGNAME") or item.get("SSHORTNAME") or
            item.get("companyname") or symbol
        ).strip()

        ann_dt_raw = (
            item.get("ANNOUNCEMENT_DATE") or item.get("DisseminationDT") or
            item.get("NEWS_DT") or ""
        )
        ann_dt = parse_bse_dt(ann_dt_raw)

        # Attachment
        att_file = item.get("ATTACHMENTNAME") or item.get("FILENAME") or ""
        att_url  = (
            f"https://www.bseindia.com/xml-data/corpfiling/AttachLive/{att_file}"
            if att_file and not att_file.startswith("http")
            else att_file
        )

        category, score, label = categorise(headline)
        h = make_hash("BSE", symbol, headline, ann_dt)

        results.append({
            "hash":           h,
            "exchange":       "BSE",
            "symbol":         symbol,
            "company_name":   company_name,
            "headline":       headline,
            "category":       category,
            "impact_score":   score,
            "impact_label":   label,
            "attachment_url": att_url,
            "ann_datetime":   ann_dt,
        })

    log.info("BSE: %d F&O announcements parsed.", len(results))
    return results


# ─── Main pipeline ────────────────────────────────────────────────────────────

def run() -> None:
    start = time.time()
    log.info("=" * 60)
    log.info("NSE/BSE Announcement Bot — run started at %s UTC", now_ist_str())
    log.info("=" * 60)

    # 1. Initialise database
    db.init_db()

    # 2. Build HTTP session
    sess = build_session()

    # 3. Refresh F&O universe
    fo_list = fo.build_fo_universe(sess)
    db.upsert_fo_stocks(fo_list)
    fo_syms = db.get_fo_symbols()
    log.info("Monitoring %d F&O symbols.", len(fo_syms))

    # 4. Fetch announcements from both exchanges
    nse_anns = fetch_nse_announcements(sess, fo_syms)
    bse_anns = fetch_bse_announcements(sess, fo_syms)

    all_anns = nse_anns + bse_anns
    log.info("Total raw F&O announcements: %d", len(all_anns))

    # 5. Insert new ones (deduplication handled inside insert_announcements)
    new_anns = db.insert_announcements(all_anns)
    log.info("New announcements inserted: %d", len(new_anns))

    # 6. Send Telegram alerts for all un-alerted rows (includes any
    #    previously inserted but un-alerted rows from prior runs)
    unalerted = db.get_unalerted()
    if unalerted:
        log.info("Sending %d Telegram alerts…", len(unalerted))
        sent = tg.send_batch_alerts(unalerted, mark_fn=db.mark_alerted)
        log.info("Alerts sent: %d", sent)
    else:
        log.info("No new alerts to send.")

    # 7. Stats
    stats = db.recent_stats(hours=24)
    log.info("Last-24h stats: %d total | by category: %s",
             stats["total"],
             {r["category"]: r["cnt"] for r in stats["by_category"]})

    elapsed = time.time() - start
    log.info("Run complete in %.1fs.", elapsed)
    log.info("=" * 60)


if __name__ == "__main__":
    try:
        run()
    except KeyboardInterrupt:
        log.info("Interrupted by user.")
        sys.exit(0)
    except Exception as exc:
        log.critical("Unhandled exception: %s", exc, exc_info=True)
        sys.exit(1)
