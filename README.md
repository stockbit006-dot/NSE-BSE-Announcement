# NSE + BSE Corporate Announcement Bot

Automatically monitors NSE and BSE for corporate announcements on **all F&O stocks**, categorises them, scores impact, deduplicates, stores history in SQLite, and fires **real-time Telegram alerts** — all without keeping your laptop on, powered by **GitHub Actions**.

---

## Architecture

```
GitHub Actions (cron: */5 * * * *)
         │
         ▼
   scraper.py  ──── builds requests.Session (NSE cookie bootstrap)
         │
         ├──► NSE /api/corporate-announcements  ──┐
         │                                        ├──► merge & filter (F&O only)
         └──► BSE API /AnnGetAnnouncementDet      ──┘
                                                  │
                                                  ▼
                                         categorise + impact score
                                                  │
                                                  ▼
                                          SQLite (announcements.db)
                                       [dedup by SHA-256 hash]
                                                  │
                                                  ▼
                                        Telegram Bot alerts
```

---

## Project Structure

```
nse-announcement-bot/
├── scraper.py          ← main entry point
├── config.py           ← all constants and category rules
├── fo_stocks.py        ← F&O universe builder (NSE API + fallback)
├── database.py         ← SQLite layer (schema, insert, dedup, stats)
├── telegram_alert.py   ← Telegram Bot API integration
├── utils.py            ← logging, retry decorator, hashing, categorisation
├── requirements.txt
├── announcements.db    ← created at runtime (not committed)
└── .github/
    └── workflows/
        └── scraper.yml ← GitHub Actions workflow (every 5 min)
```

---

## Quick Start

### Step 1 — Fork / Clone

```bash
git clone https://github.com/YOUR_USERNAME/nse-announcement-bot.git
cd nse-announcement-bot
```

### Step 2 — Create a Telegram Bot

1. Open Telegram, search for **@BotFather**.
2. Send `/newbot` → follow prompts → copy the **token** (looks like `123456:ABC-DEF…`).
3. Send **any message** to your new bot (required so the API can see your chat).
4. In a browser visit:
   ```
   https://api.telegram.org/bot<YOUR_TOKEN>/getUpdates
   ```
5. Copy the numeric value from `"id"` inside `"chat"` — that is your **CHAT_ID**.

> For a **group**: add the bot to the group, send a message in the group, then visit the URL above. The group chat ID will be a negative number.

### Step 3 — Add GitHub Secrets

Go to your repository → **Settings → Secrets and variables → Actions → New repository secret**.

| Secret Name        | Value                          |
|--------------------|--------------------------------|
| `TELEGRAM_TOKEN`   | Your BotFather token           |
| `TELEGRAM_CHAT_ID` | Your chat / group ID           |

### Step 4 — Enable GitHub Actions

Push the repo (fork triggers Actions automatically).  
Or go to **Actions → NSE-BSE Announcement Bot → Run workflow** for an instant test.

### Step 5 — Test locally (optional)

```bash
pip install -r requirements.txt

export TELEGRAM_TOKEN="your_token_here"
export TELEGRAM_CHAT_ID="your_chat_id_here"

python scraper.py
```

You should see log output and receive a Telegram message.

---

## Telegram Alert Format

```
🔵 NSE  RELIANCE  |  🔴 High
🏢 Reliance Industries Ltd
🏷️ Quarterly Results
📣 Standalone and Consolidated Un-audited Financial Results for Q3 FY2025
🕐 2025-01-15 17:32:00
📎 View Attachment
```

---

## Announcement Categories

| Category              | Typical Impact |
|-----------------------|---------------|
| Order Win             | 🔴 High (9)   |
| Acquisition / Merger  | 🔴 High (9)   |
| Quarterly Results     | 🔴 High (8)   |
| Bonus Issue           | 🔴 High (8)   |
| Stock Split           | 🔴 High (8)   |
| Buyback               | 🔴 High (8)   |
| Dividend              | 🟡 Medium (7) |
| Promoter Activity     | 🟡 Medium (7) |
| Fund Raise            | 🟡 Medium (7) |
| Debt / Rating         | 🟡 Medium (6) |
| Regulatory / Legal    | 🔴 High (8)   |
| Board Meeting         | 🟡 Medium (5) |
| Insider Trading       | 🟢 Low (4)    |
| Miscellaneous         | 🟢 Low (3)    |

---

## Database Schema

```sql
announcements (
    id              INTEGER PRIMARY KEY,
    hash            TEXT UNIQUE,      -- SHA-256 dedup key
    exchange        TEXT,             -- NSE | BSE
    symbol          TEXT,
    company_name    TEXT,
    headline        TEXT,
    category        TEXT,
    impact_score    INTEGER,          -- 1-10
    impact_label    TEXT,             -- 🔴 High / 🟡 Medium / 🟢 Low
    attachment_url  TEXT,
    ann_datetime    TEXT,
    fetched_at      TEXT,
    alerted         INTEGER           -- 0=pending, 1=sent
)
```

The database persists between GitHub Actions runs via the **Actions Cache**.  
It grows indefinitely — all history is kept. You can download it from the Actions Cache UI.

---

## GitHub Actions Details

- **Trigger**: `*/5 * * * *` (every 5 minutes, ~288 runs/day)
- **Concurrency lock** prevents two runs from writing to the DB simultaneously.
- **Timeout**: 4 minutes — kills hung runs before the next one starts.
- **DB persistence**: `actions/cache@v4` saves `announcements.db` between runs.
- **Free tier**: GitHub gives 2,000 minutes/month on free accounts.  
  288 runs × ~30 sec each ≈ **144 minutes/day → ~4,320 min/month**.  
  → Upgrade to a paid plan, use a private repo on Pro, or reduce to `*/10 * * * *`.

> **Tip**: Switch to `*/10 * * * *` (every 10 min) to stay within the free tier.

---

## Advanced / Optional Extensions

### High-Impact Only Alerts
Edit `telegram_alert.py → send_batch_alerts()`:
```python
if ann.get("impact_score", 0) >= 7:   # only High impact
    send_alert(ann)
```

### Add More Category Rules
Edit the `CATEGORY_RULES` dict in `config.py`:
```python
"JV / Partnership": (
    ["joint venture", "jv", "mou", "memorandum of understanding"], 7
),
```

### Query Historical Data
```bash
sqlite3 announcements.db
> SELECT symbol, category, impact_label, ann_datetime FROM announcements
  WHERE impact_score >= 7
  ORDER BY ann_datetime DESC
  LIMIT 20;
```

### Export to CSV
```python
import sqlite3, pandas as pd
conn = sqlite3.connect("announcements.db")
df = pd.read_sql("SELECT * FROM announcements", conn)
df.to_csv("announcements_export.csv", index=False)
```

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| No Telegram messages | Check TELEGRAM_TOKEN / TELEGRAM_CHAT_ID secrets. Run locally. |
| NSE returns 401 | Normal; the scraper auto-refreshes the session and retries. |
| DB not persisting | Ensure the `actions/cache` step succeeded. Check Actions logs. |
| "All F&O symbols from fallback" | NSE API might be temporarily down; bot still works via fallback list. |
| Duplicate alerts | Should not happen; if it does, check the `hash` column for collisions. |

---

## Security Notes

- **Never hardcode** `TELEGRAM_TOKEN` or `TELEGRAM_CHAT_ID` in any file.
- Both are injected by GitHub Actions from encrypted Secrets at runtime.
- The SQLite DB contains no credentials.
- The repo can be public safely.

---

## License

MIT — free to use, modify, and distribute.
