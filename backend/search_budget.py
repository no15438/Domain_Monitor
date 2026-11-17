"""A persistent search ceiling shared by collection and assistant tools."""
from datetime import datetime, timezone
from pathlib import Path
import sqlite3
from config import settings


def reserve_search():
    limit = settings.tavily_daily_request_limit
    if not limit:
        return True
    path = Path(settings.database_path).with_name("ai-usage.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS search_usage (day TEXT PRIMARY KEY, requests INTEGER NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        day = datetime.now(timezone.utc).date().isoformat()
        row = conn.execute("SELECT requests FROM search_usage WHERE day=?", (day,)).fetchone()
        if row and row[0] >= limit:
            return False
        conn.execute("INSERT INTO search_usage VALUES (?,1) ON CONFLICT(day) DO UPDATE SET requests=requests+1", (day,))
    return True
