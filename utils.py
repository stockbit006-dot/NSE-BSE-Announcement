"""
utils.py — Shared utilities: logging setup, retry decorator,
announcement categorisation, impact scoring, and deduplication hashing.
"""

import hashlib
import logging
import time
import functools
from datetime import datetime
from typing import Tuple

import config


# ─── Logging ─────────────────────────────────────────────────────────────────

def setup_logger(name: str = "ann_bot") -> logging.Logger:
    """Return a logger that writes to stdout with timestamp and level."""
    logger = logging.getLogger(name)
    if logger.handlers:          # avoid duplicate handlers on re-import
        return logger

    logger.setLevel(logging.DEBUG)
    handler = logging.StreamHandler()
    handler.setLevel(logging.DEBUG)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)-8s] %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    handler.setFormatter(fmt)
    logger.addHandler(handler)
    return logger


log = setup_logger()


# ─── Retry decorator ─────────────────────────────────────────────────────────

def retry(max_tries: int = config.MAX_RETRIES,
          delay: float = config.RETRY_DELAY,
          exceptions=(Exception,)):
    """
    Decorator: retry a function up to *max_tries* times, sleeping *delay*
    seconds between attempts. Logs every failure.
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(1, max_tries + 1):
                try:
                    return func(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    log.warning(
                        "Attempt %d/%d for '%s' failed: %s",
                        attempt, max_tries, func.__name__, exc
                    )
                    if attempt < max_tries:
                        time.sleep(delay)
            log.error("All %d attempts failed for '%s'.", max_tries, func.__name__)
            raise last_exc
        return wrapper
    return decorator


# ─── Announcement hashing ────────────────────────────────────────────────────

def make_hash(exchange: str, symbol: str, headline: str, dt_str: str) -> str:
    """
    Create a stable SHA-256 hash that uniquely identifies one announcement.
    Used to detect duplicates across runs.
    """
    raw = f"{exchange.upper()}|{symbol.upper()}|{headline.strip().lower()}|{dt_str}"
    return hashlib.sha256(raw.encode()).hexdigest()


# ─── Categorisation engine ───────────────────────────────────────────────────

def categorise(headline: str) -> Tuple[str, int, str]:
    """
    Match headline text against keyword rules and return
    (category, impact_score, impact_label).
    """
    lower = headline.lower()

    for category, (keywords, score) in config.CATEGORY_RULES.items():
        if any(kw in lower for kw in keywords):
            label = _impact_label(score)
            return category, score, label

    label = _impact_label(config.DEFAULT_IMPACT)
    return config.DEFAULT_CATEGORY, config.DEFAULT_IMPACT, label


def _impact_label(score: int) -> str:
    for r, (emoji_label, _) in config.IMPACT_LABELS.items():
        if score in r:
            return emoji_label
    return "🟢 Low"


# ─── Time helpers ─────────────────────────────────────────────────────────────

def now_ist_str() -> str:
    """Current UTC time as ISO string (GitHub Actions runs UTC)."""
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")


def parse_nse_dt(raw: str) -> str:
    """Normalise NSE datetime strings to 'YYYY-MM-DD HH:MM:SS'."""
    for fmt in ("%d-%b-%Y %H:%M:%S", "%Y-%m-%dT%H:%M:%S",
                "%d-%m-%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            continue
    return raw  # return as-is if unparseable


def parse_bse_dt(raw: str) -> str:
    """Normalise BSE datetime strings to 'YYYY-MM-DD HH:MM:SS'."""
    for fmt in ("%Y%m%d%H%M%S", "%d %b %Y", "%Y-%m-%dT%H:%M:%S",
                "%d-%m-%Y", "%Y-%m-%d %H:%M:%S"):
        try:
            return datetime.strptime(raw.strip(), fmt).strftime("%Y-%m-%d %H:%M:%S")
        except (ValueError, AttributeError):
            continue
    return raw
