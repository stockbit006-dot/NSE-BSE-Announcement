"""
telegram_alert.py — Send rich Telegram alerts for corporate announcements.

Message format
--------------
Each alert is a single formatted message per announcement, using
Telegram's HTML parse mode for clean display.

Setup reminder
--------------
1. Create bot → @BotFather → /newbot → copy token.
2. Send any message to your bot.
3. GET https://api.telegram.org/bot<TOKEN>/getUpdates → copy chat.id.
4. Set GitHub Secrets: TELEGRAM_TOKEN, TELEGRAM_CHAT_ID.
"""

import time
import requests
from typing import Dict, List

import config
from utils import setup_logger, retry

log = setup_logger("telegram")

# Telegram API enforces ~30 msg/sec; we stay well below that.
SEND_DELAY = 0.5  # seconds between messages


# ─── Core send function ───────────────────────────────────────────────────────

@retry(max_tries=3, delay=3, exceptions=(requests.RequestException,))
def _send_message(text: str) -> bool:
    """
    POST a single message to Telegram.
    Returns True on success.
    Raises on network / API errors (triggers retry).
    """
    if not config.TELEGRAM_TOKEN or not config.TELEGRAM_CHAT_ID:
        log.warning("TELEGRAM_TOKEN or TELEGRAM_CHAT_ID not set — skipping alert.")
        return False

    url = config.TELEGRAM_API_BASE.format(
        token=config.TELEGRAM_TOKEN, method="sendMessage"
    )
    payload = {
        "chat_id":    config.TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    resp = requests.post(url, json=payload, timeout=config.REQUEST_TIMEOUT)

    if resp.status_code == 429:                     # rate limited
        retry_after = resp.json().get("parameters", {}).get("retry_after", 10)
        log.warning("Telegram rate limit hit — sleeping %ds.", retry_after)
        time.sleep(retry_after)
        raise requests.RequestException("Rate limited; will retry.")

    if not resp.ok:
        log.error("Telegram API error %d: %s", resp.status_code, resp.text[:200])
        resp.raise_for_status()

    return True


# ─── Message builder ──────────────────────────────────────────────────────────

def _build_message(ann: Dict) -> str:
    """Compose an HTML-formatted Telegram message for one announcement."""
    exchange     = ann.get("exchange", "")
    symbol       = ann.get("symbol", "")
    company      = ann.get("company_name", symbol)
    headline     = ann.get("headline", "")
    category     = ann.get("category", "Miscellaneous")
    impact_label = ann.get("impact_label", "🟢 Low")
    ann_dt       = ann.get("ann_datetime", "")
    attach_url   = ann.get("attachment_url", "")

    # Exchange badge
    exch_badge = "🔵 NSE" if exchange.upper() == "NSE" else "🟠 BSE"

    # Impact icon already embedded in impact_label (e.g. "🔴 High")
    lines = [
        f"<b>{exch_badge}  {symbol}</b>  |  {impact_label}",
        f"🏢 <i>{company}</i>",
        f"🏷️ <b>{category}</b>",
        f"📣 {headline[:300]}{'…' if len(headline) > 300 else ''}",
    ]
    if ann_dt:
        lines.append(f"🕐 {ann_dt}")
    if attach_url:
        lines.append(f'📎 <a href="{attach_url}">View Attachment</a>')

    return "\n".join(lines)


def _build_summary(new_count: int, high_count: int) -> str:
    """Short summary message for batches."""
    return (
        f"<b>📊 Announcement Run Complete</b>\n"
        f"New alerts sent: <b>{new_count}</b>\n"
        f"High-impact alerts: <b>{high_count}</b>"
    )


# ─── Public interface ─────────────────────────────────────────────────────────

def send_alert(ann: Dict) -> bool:
    """Send a single formatted alert. Returns True on success."""
    text = _build_message(ann)
    try:
        ok = _send_message(text)
        if ok:
            log.info("Alert sent: [%s] %s", ann.get("exchange"), ann.get("symbol"))
        return ok
    except Exception as exc:
        log.error("Failed to send alert for %s: %s", ann.get("symbol"), exc)
        return False


def send_batch_alerts(announcements: List[Dict], mark_fn=None) -> int:
    """
    Send alerts for a list of announcements.
    Calls mark_fn(hash) after each successful send (to mark alerted in DB).
    Returns count of successfully sent alerts.
    """
    sent = 0
    high = 0
    for ann in announcements:
        ok = send_alert(ann)
        if ok:
            sent += 1
            if ann.get("impact_score", 0) >= 7:
                high += 1
            if mark_fn:
                mark_fn(ann["hash"])
            time.sleep(SEND_DELAY)    # gentle pacing

    if sent:
        try:
            _send_message(_build_summary(sent, high))
        except Exception:
            pass  # summary is best-effort

    log.info("Batch alert complete. Sent %d / %d.", sent, len(announcements))
    return sent


def send_startup_ping() -> None:
    """Send a health-check message so you know the bot started."""
    try:
        _send_message(
            "🤖 <b>NSE/BSE Announcement Bot started</b>\n"
            "Monitoring F&O stocks for corporate announcements…"
        )
    except Exception as exc:
        log.warning("Startup ping failed: %s", exc)
