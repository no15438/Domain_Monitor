import sqlite3
import os

DB_PATH: str | None = None


def init_db(db_path: str):
    global DB_PATH
    DB_PATH = db_path
    os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)

    conn = sqlite3.connect(db_path)
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topics (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT DEFAULT '#6366f1',
            global_overview TEXT,
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS topic_links (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            source_topic_id INTEGER REFERENCES topics(id),
            target_topic_id INTEGER REFERENCES topics(id),
            link_type TEXT DEFAULT 'related',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS topic_feeds (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            feed_url TEXT NOT NULL,
            label TEXT DEFAULT '',
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(topic_id, feed_url)
        );
        CREATE TABLE IF NOT EXISTS keywords (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            keyword TEXT NOT NULL,
            category TEXT DEFAULT '',
            topic_id INTEGER REFERENCES topics(id),
            is_active INTEGER DEFAULT 1,
            created_at TEXT DEFAULT (datetime('now')),
            UNIQUE(keyword, topic_id)
        );
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            summary TEXT,
            content TEXT,
            source TEXT,
            url TEXT UNIQUE,
            tags TEXT DEFAULT '[]',
            sentiment TEXT DEFAULT 'neutral',
            importance INTEGER DEFAULT 5,
            source_type TEXT DEFAULT 'search',
            topic_id INTEGER REFERENCES topics(id),
            published_at TEXT,
            event_id TEXT,
            is_canonical INTEGER DEFAULT 1,
            event_size INTEGER DEFAULT 1,
            source_score REAL DEFAULT 0,
            source_breakdown TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS topic_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            overview_content TEXT NOT NULL DEFAULT '',
            stats_metadata TEXT NOT NULL DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_snapshots_topic_time
            ON topic_snapshots(topic_id, created_at DESC);

        CREATE TABLE IF NOT EXISTS task_state (
            key TEXT PRIMARY KEY,
            status TEXT NOT NULL DEFAULT 'running',
            started_at TEXT DEFAULT (datetime('now')),
            finished_at TEXT,
            result_summary TEXT DEFAULT '',
            error TEXT DEFAULT ''
        );
    """)

    _migrate_topic_summaries_to_snapshots(conn)
    _migrate_articles_event_fields(conn)

    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_articles_topic_id ON articles(topic_id);
        CREATE INDEX IF NOT EXISTS idx_articles_created_at ON articles(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
        CREATE INDEX IF NOT EXISTS idx_articles_event_id ON articles(event_id);
        CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url);
        CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_keywords_topic_id ON keywords(topic_id);
        CREATE INDEX IF NOT EXISTS idx_feeds_topic_id ON topic_feeds(topic_id);
    """)

    conn.commit()
    conn.close()


def _migrate_topic_summaries_to_snapshots(conn):
    """One-time migration: copy rows from old topic_summaries into topic_snapshots, then drop the old table."""
    try:
        conn.execute("SELECT 1 FROM topic_summaries LIMIT 1")
    except Exception:
        return
    conn.execute(
        """INSERT INTO topic_snapshots (topic_id, overview_content, created_at)
           SELECT topic_id, content, generated_at FROM topic_summaries
           WHERE content IS NOT NULL AND content != ''"""
    )
    conn.execute("DROP TABLE IF EXISTS topic_summaries")


def _migrate_articles_event_fields(conn):
    """Add event-related and analysis columns to existing articles table (idempotent)."""
    new_cols = [
        ("event_id", "TEXT"),
        ("is_canonical", "INTEGER DEFAULT 1"),
        ("event_size", "INTEGER DEFAULT 1"),
        ("source_score", "REAL DEFAULT 0"),
        ("source_breakdown", "TEXT DEFAULT '{}'"),
        ("topic_relevance", "REAL DEFAULT 0"),
        ("key_entities", "TEXT DEFAULT '[]'"),
        ("topic_analysis", "TEXT DEFAULT ''"),
        ("is_kept", "INTEGER DEFAULT 0"),
        ("status", "TEXT DEFAULT 'active'"),
    ]
    for col_name, col_def in new_cols:
        try:
            conn.execute(f"ALTER TABLE articles ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass
    for tcol, tdef in [
        ("global_overview", "TEXT"),
        ("research_brief", "TEXT DEFAULT ''"),
        ("research_config", "TEXT DEFAULT '{}'"),
        ("pipeline_config", "TEXT DEFAULT '{}'"),
    ]:
        try:
            conn.execute(f"ALTER TABLE topics ADD COLUMN {tcol} {tdef}")
        except Exception:
            pass


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


# ── Topics ────────────────────────────────────────────


def get_topic_global_overview(topic_id: int) -> str | None:
    conn = _conn()
    row = conn.execute("SELECT global_overview FROM topics WHERE id = ?", (topic_id,)).fetchone()
    conn.close()
    return row["global_overview"] if row else None


def update_topic_global_overview(topic_id: int, content: str):
    conn = _conn()
    conn.execute("UPDATE topics SET global_overview = ? WHERE id = ?", (content, topic_id))
    conn.commit()
    conn.close()


def get_topics():
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM topics WHERE is_active = 1 ORDER BY created_at"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def create_topic(name: str, color: str = "#6366f1"):
    conn = _conn()
    try:
        cur = conn.execute(
            "INSERT INTO topics (name, color) VALUES (?, ?)", (name, color)
        )
        conn.commit()
        topic_id = cur.lastrowid
    except sqlite3.IntegrityError:
        conn.close()
        return None
    conn.close()
    return topic_id


def update_topic(
    topic_id: int,
    name: str | None = None,
    color: str | None = None,
    research_brief: str | None = None,
    research_config: str | None = None,
    pipeline_config: str | None = None,
):
    conn = _conn()
    if name is not None:
        conn.execute("UPDATE topics SET name = ? WHERE id = ?", (name, topic_id))
    if color is not None:
        conn.execute("UPDATE topics SET color = ? WHERE id = ?", (color, topic_id))
    if research_brief is not None:
        conn.execute("UPDATE topics SET research_brief = ? WHERE id = ?", (research_brief, topic_id))
    if research_config is not None:
        conn.execute("UPDATE topics SET research_config = ? WHERE id = ?", (research_config, topic_id))
    if pipeline_config is not None:
        conn.execute("UPDATE topics SET pipeline_config = ? WHERE id = ?", (pipeline_config, topic_id))
    conn.commit()
    conn.close()


def delete_topic(topic_id: int):
    conn = _conn()
    conn.execute("UPDATE topics SET is_active = 0 WHERE id = ?", (topic_id,))
    conn.execute("UPDATE keywords SET is_active = 0 WHERE topic_id = ?", (topic_id,))
    conn.commit()
    conn.close()


# ── Topic Feeds ───────────────────────────────────────


def get_topic_feeds(topic_id: int | None = None):
    conn = _conn()
    if topic_id is not None:
        rows = conn.execute(
            "SELECT * FROM topic_feeds WHERE is_active = 1 AND topic_id = ? ORDER BY created_at",
            (topic_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM topic_feeds WHERE is_active = 1 ORDER BY created_at"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_topic_feed(topic_id: int, feed_url: str, label: str = ""):
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO topic_feeds (topic_id, feed_url, label) VALUES (?, ?, ?)",
            (topic_id, feed_url, label),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()


def remove_topic_feed(feed_id: int):
    conn = _conn()
    conn.execute("UPDATE topic_feeds SET is_active = 0 WHERE id = ?", (feed_id,))
    conn.commit()
    conn.close()


# ── Articles ──────────────────────────────────────────


def delete_article(article_id: str):
    conn = _conn()
    conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()


def archive_article(article_id: str):
    conn = _conn()
    conn.execute("UPDATE articles SET status = 'archived' WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()


def restore_article(article_id: str):
    conn = _conn()
    conn.execute("UPDATE articles SET status = 'active' WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()


def get_articles(limit=50, offset=0, topic_id=None, sort="relevance", status="active"):
    conn = _conn()
    order = (
        "ORDER BY (importance * EXP(-0.023 * MAX(julianday('now') - julianday(COALESCE(published_at, created_at)), 0))) DESC, COALESCE(published_at, created_at) DESC"
        if sort == "relevance"
        else "ORDER BY COALESCE(published_at, created_at) DESC"
    )
    status_filter = "AND COALESCE(status, 'active') = ?" if status else ""
    params: list = []
    if topic_id is not None:
        base = f"SELECT * FROM articles WHERE topic_id = ? {status_filter} {order} LIMIT ? OFFSET ?"
        params = [topic_id] + ([status] if status else []) + [limit, offset]
    else:
        base = f"SELECT * FROM articles WHERE 1=1 {status_filter} {order} LIMIT ? OFFSET ?"
        params = ([status] if status else []) + [limit, offset]
    rows = conn.execute(base, params).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_article_by_url(url: str):
    conn = _conn()
    row = conn.execute("SELECT * FROM articles WHERE url = ?", (url,)).fetchone()
    conn.close()
    return dict(row) if row else None


def insert_article(article: dict) -> bool:
    """Insert an article. Returns True if inserted, False if duplicate URL (idempotent skip).
    Raises on unexpected integrity errors."""
    import logging
    _log = logging.getLogger("database")
    conn = _conn()
    try:
        conn.execute(
            """INSERT INTO articles
               (id, title, summary, content, source, url, tags, sentiment, importance,
                source_type, topic_id, published_at,
                event_id, is_canonical, event_size, source_score, source_breakdown,
                topic_relevance, key_entities, topic_analysis)
               VALUES (:id,:title,:summary,:content,:source,:url,:tags,:sentiment,:importance,
                :source_type,:topic_id,:published_at,
                :event_id,:is_canonical,:event_size,:source_score,:source_breakdown,
                :topic_relevance,:key_entities,:topic_analysis)""",
            article,
        )
        conn.commit()
        return True
    except sqlite3.IntegrityError as e:
        err_msg = str(e).lower()
        if "url" in err_msg or "unique" in err_msg:
            _log.debug("insert_article: duplicate URL skipped — %s", article.get("url", "?"))
            return False
        _log.error("insert_article: unexpected IntegrityError — %s | article id=%s", e, article.get("id", "?"))
        raise
    finally:
        conn.close()


def get_article_count(topic_id=None, status="active"):
    conn = _conn()
    status_filter = "AND COALESCE(status, 'active') = ?" if status else ""
    if topic_id is not None:
        count = conn.execute(
            f"SELECT COUNT(*) FROM articles WHERE topic_id = ? {status_filter}",
            (topic_id,) + ((status,) if status else ()),
        ).fetchone()[0]
    else:
        count = conn.execute(
            f"SELECT COUNT(*) FROM articles WHERE 1=1 {status_filter}",
            (status,) if status else (),
        ).fetchone()[0]
    conn.close()
    return count


# ── Keywords ──────────────────────────────────────────


def get_keywords(topic_id=None):
    conn = _conn()
    if topic_id is not None:
        rows = conn.execute(
            "SELECT * FROM keywords WHERE is_active = 1 AND topic_id = ? ORDER BY created_at DESC",
            (topic_id,),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM keywords WHERE is_active = 1 ORDER BY created_at DESC"
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def add_keyword(keyword: str, category: str = "", topic_id: int | None = None):
    conn = _conn()
    try:
        conn.execute(
            "INSERT INTO keywords (keyword, category, topic_id) VALUES (?, ?, ?)",
            (keyword, category, topic_id),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    finally:
        conn.close()


def remove_keyword(keyword_id: int):
    conn = _conn()
    conn.execute("UPDATE keywords SET is_active = 0 WHERE id = ?", (keyword_id,))
    conn.commit()
    conn.close()


def toggle_article_kept(article_id: str, is_kept: int):
    """Toggle the is_kept status of an article."""
    conn = _conn()
    conn.execute("UPDATE articles SET is_kept = ? WHERE id = ?", (is_kept, article_id))
    conn.commit()
    conn.close()


def update_article_metadata(
    article_id: str,
    title: str | None = None,
    summary: str | None = None,
    tags_json: str | None = None,
    sentiment: str | None = None,
    importance: int | None = None,
):
    """Update editable fields of an article. Only non-None fields are written."""
    conn = _conn()
    updates: list[str] = []
    params: list = []
    if title is not None:
        updates.append("title = ?"); params.append(title)
    if summary is not None:
        updates.append("summary = ?"); params.append(summary)
    if tags_json is not None:
        updates.append("tags = ?"); params.append(tags_json)
    if sentiment is not None:
        updates.append("sentiment = ?"); params.append(sentiment)
    if importance is not None:
        updates.append("importance = ?"); params.append(importance)
    if updates:
        params.append(article_id)
        conn.execute(f"UPDATE articles SET {', '.join(updates)} WHERE id = ?", params)
        conn.commit()
    conn.close()


def get_kept_articles(topic_id: int):
    """Get all articles kept in the knowledge base for a topic."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM articles WHERE topic_id = ? AND (is_kept = 1 OR importance >= 8) ORDER BY importance DESC, COALESCE(published_at, created_at) DESC",
        (topic_id,)
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_snapshot(topic_id: int):
    """Return the most recent snapshot for a topic."""
    conn = _conn()
    row = conn.execute(
        "SELECT id, overview_content, stats_metadata, created_at FROM topic_snapshots WHERE topic_id = ? ORDER BY id DESC LIMIT 1",
        (topic_id,),
    ).fetchone()
    conn.close()
    if row:
        return {
            "id": row["id"],
            "content": row["overview_content"],
            "stats_metadata": row["stats_metadata"],
            "generated_at": row["created_at"],
        }
    return None


def save_snapshot(topic_id: int, overview_content: str, stats_metadata: str = "{}") -> int:
    """Append a new snapshot. Returns the new snapshot id."""
    conn = _conn()
    cur = conn.execute(
        "INSERT INTO topic_snapshots (topic_id, overview_content, stats_metadata) VALUES (?, ?, ?)",
        (topic_id, overview_content, stats_metadata),
    )
    snapshot_id = cur.lastrowid
    conn.commit()
    conn.close()
    return snapshot_id


def delete_snapshot(snapshot_id: int):
    """Delete a snapshot by ID."""
    conn = _conn()
    conn.execute("DELETE FROM topic_snapshots WHERE id = ?", (snapshot_id,))
    conn.commit()
    conn.close()


def update_snapshot(snapshot_id: int, content: str):
    """Update a snapshot's content."""
    conn = _conn()
    conn.execute(
        "UPDATE topic_snapshots SET overview_content = ? WHERE id = ?",
        (content, snapshot_id)
    )
    conn.commit()
    conn.close()


def get_snapshot_history(topic_id: int, limit: int = 10):
    """Return recent snapshots for a topic (newest first)."""
    conn = _conn()
    rows = conn.execute(
        "SELECT id, overview_content, stats_metadata, created_at FROM topic_snapshots WHERE topic_id = ? ORDER BY id DESC LIMIT ?",
        (topic_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# Backward-compatible aliases
def get_cached_summary(topic_id: int):
    snap = get_latest_snapshot(topic_id)
    if snap:
        return {"content": snap["content"], "generated_at": snap["generated_at"]}
    return None


def save_cached_summary(topic_id: int, content: str):
    save_snapshot(topic_id, content)


def get_recent_urls(hours=72):
    conn = _conn()
    rows = conn.execute(
        "SELECT url FROM articles WHERE created_at >= datetime('now', ?)",
        (f"-{hours} hours",),
    ).fetchall()
    conn.close()
    return {r["url"] for r in rows}


def get_recent_article_stubs(topic_id=None, hours=48):
    """Return lightweight article stubs (title + content snippet + url) for
    cross-run semantic deduplication.  Only pulls the fields needed by the
    dedup vector, keeping the query fast even for large topic libraries."""
    conn = _conn()
    if topic_id is not None:
        rows = conn.execute(
            """SELECT url, title, content FROM articles
               WHERE topic_id = ? AND created_at >= datetime('now', ?)
               ORDER BY created_at DESC LIMIT 300""",
            (topic_id, f"-{hours} hours"),
        ).fetchall()
    else:
        rows = conn.execute(
            """SELECT url, title, content FROM articles
               WHERE created_at >= datetime('now', ?)
               ORDER BY created_at DESC LIMIT 300""",
            (f"-{hours} hours",),
        ).fetchall()
    conn.close()
    return [{"url": r["url"], "title": r["title"], "content": r["content"] or ""} for r in rows]


# ── Insights queries ─────────────────────────────────


def get_insight_summary(topic_id=None, hours=24):
    """Aggregate stats: top events, counts, source distribution."""
    conn = _conn()
    time_filter = "AND created_at >= datetime('now', ?)"
    base_where = "WHERE 1=1"
    params: list = []

    if topic_id is not None:
        base_where += " AND topic_id = ?"
        params.append(topic_id)

    params_with_time = params + [f"-{hours} hours"]

    total = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where} {time_filter}",
        params_with_time,
    ).fetchone()[0]

    important = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where} {time_filter} AND importance >= 8",
        params_with_time,
    ).fetchone()[0]

    source_rows = conn.execute(
        f"SELECT source_type, COUNT(*) as cnt FROM articles {base_where} {time_filter} GROUP BY source_type ORDER BY cnt DESC",
        params_with_time,
    ).fetchall()
    source_dist = {r["source_type"]: r["cnt"] for r in source_rows}

    sentiment_rows = conn.execute(
        f"SELECT sentiment, COUNT(*) as cnt FROM articles {base_where} {time_filter} GROUP BY sentiment",
        params_with_time,
    ).fetchall()
    sentiment_dist = {r["sentiment"]: r["cnt"] for r in sentiment_rows}

    top_events = conn.execute(
        f"""SELECT event_id, title, summary, source, url, importance, event_size,
                   source_score, source_breakdown, sentiment, tags, source_type, created_at, published_at
            FROM articles {base_where} {time_filter} AND is_canonical = 1
            ORDER BY event_size DESC,
                     (importance * EXP(-0.023 * MAX(julianday('now') - julianday(COALESCE(published_at, created_at)), 0))) DESC,
                     source_score DESC
            LIMIT 5""",
        params_with_time,
    ).fetchall()

    conn.close()
    return {
        "total_articles": total,
        "important_count": important,
        "source_distribution": source_dist,
        "sentiment_distribution": sentiment_dist,
        "top_events": [dict(r) for r in top_events],
    }


def get_events_grouped(topic_id=None, limit=30, offset=0, sort="relevance", status="active"):
    """Return canonical articles grouped by event_id, with alternatives count."""
    conn = _conn()
    base_where = "WHERE is_canonical = 1"
    params: list = []

    if topic_id is not None:
        base_where += " AND topic_id = ?"
        params.append(topic_id)

    if status:
        base_where += " AND COALESCE(status, 'active') = ?"
        params.append(status)

    order = (
        "ORDER BY (importance * EXP(-0.023 * MAX(julianday('now') - julianday(COALESCE(published_at, created_at)), 0))) DESC, event_size DESC, COALESCE(published_at, created_at) DESC"
        if sort == "relevance"
        else "ORDER BY COALESCE(published_at, created_at) DESC"
    )

    rows = conn.execute(
        f"SELECT * FROM articles {base_where} {order} LIMIT ? OFFSET ?",
        params + [limit, offset],
    ).fetchall()

    total = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where}",
        params,
    ).fetchone()[0]

    conn.close()
    return [dict(r) for r in rows], total


def get_event_alternatives(event_id: str):
    """Return all articles sharing the same event_id."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM articles WHERE event_id = ? ORDER BY source_score DESC",
        (event_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_topics_overview(hours=24):
    """Return stats for every active topic — for dashboard cards.
    Uses aggregated queries instead of per-topic N+1 to stay fast as topic count grows."""
    conn = _conn()
    topics = conn.execute(
        "SELECT * FROM topics WHERE is_active = 1 ORDER BY created_at"
    ).fetchall()

    if not topics:
        conn.close()
        return []

    topic_ids = [t["id"] for t in topics]
    time_param = f"-{hours} hours"
    placeholders = ",".join("?" * len(topic_ids))

    # Batch: total + important counts
    count_rows = conn.execute(
        f"""SELECT topic_id,
                   COUNT(*) as total,
                   SUM(CASE WHEN importance >= 8 THEN 1 ELSE 0 END) as important
            FROM articles
            WHERE topic_id IN ({placeholders})
              AND created_at >= datetime('now', ?)
            GROUP BY topic_id""",
        topic_ids + [time_param],
    ).fetchall()
    count_map: dict[int, dict] = {}
    for r in count_rows:
        count_map[r["topic_id"]] = {"total": r["total"], "important": r["important"]}

    # Batch: sentiment distribution
    sent_rows = conn.execute(
        f"""SELECT topic_id, sentiment, COUNT(*) as cnt
            FROM articles
            WHERE topic_id IN ({placeholders})
              AND created_at >= datetime('now', ?)
            GROUP BY topic_id, sentiment""",
        topic_ids + [time_param],
    ).fetchall()
    sent_map: dict[int, dict[str, int]] = {}
    for r in sent_rows:
        sent_map.setdefault(r["topic_id"], {})[r["sentiment"]] = r["cnt"]

    # Batch: previous-period count for trend delta
    prev_rows = conn.execute(
        f"""SELECT topic_id, COUNT(*) as cnt
            FROM articles
            WHERE topic_id IN ({placeholders})
              AND created_at >= datetime('now', ?)
              AND created_at < datetime('now', ?)
            GROUP BY topic_id""",
        topic_ids + [f"-{hours * 2} hours", time_param],
    ).fetchall()
    prev_map = {r["topic_id"]: r["cnt"] for r in prev_rows}

    # Batch: keywords
    kw_rows = conn.execute(
        f"""SELECT topic_id, keyword
            FROM keywords
            WHERE topic_id IN ({placeholders}) AND is_active = 1""",
        topic_ids,
    ).fetchall()
    kw_map: dict[int, list[str]] = {}
    for r in kw_rows:
        kw_map.setdefault(r["topic_id"], []).append(r["keyword"])

    # Batch: top headline per topic (window-optimised via subquery)
    top_rows = conn.execute(
        f"""SELECT topic_id, title FROM (
                SELECT topic_id, title,
                       ROW_NUMBER() OVER (PARTITION BY topic_id ORDER BY importance DESC, event_size DESC) as rn
                FROM articles
                WHERE topic_id IN ({placeholders})
                  AND created_at >= datetime('now', ?)
                  AND is_canonical = 1
            ) WHERE rn = 1""",
        topic_ids + [time_param],
    ).fetchall()
    top_map = {r["topic_id"]: r["title"] for r in top_rows}

    conn.close()

    result = []
    for t in topics:
        tid = t["id"]
        stats = count_map.get(tid, {"total": 0, "important": 0})
        total = stats["total"]
        prev_count = prev_map.get(tid, 0)
        result.append({
            **dict(t),
            "article_count": total,
            "important_count": stats["important"],
            "sentiment": sent_map.get(tid, {}),
            "trend_delta": total - prev_count,
            "keywords": kw_map.get(tid, []),
            "top_headline": top_map.get(tid),
        })

    return result


def get_topic_insights(topic_id=None, window_hours=24):
    """Topic-level trends: sentiment over time, top tags, trend delta."""
    conn = _conn()
    base_where = "WHERE 1=1"
    params: list = []

    if topic_id is not None:
        base_where += " AND topic_id = ?"
        params.append(topic_id)

    current_params = params + [f"-{window_hours} hours"]
    prev_params = params + [f"-{window_hours * 2} hours", f"-{window_hours} hours"]

    current_count = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where} AND created_at >= datetime('now', ?)",
        current_params,
    ).fetchone()[0]

    previous_count = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where} AND created_at >= datetime('now', ?) AND created_at < datetime('now', ?)",
        prev_params,
    ).fetchone()[0]

    trend_delta = current_count - previous_count

    sentiment_rows = conn.execute(
        f"SELECT sentiment, COUNT(*) as cnt FROM articles {base_where} AND created_at >= datetime('now', ?) GROUP BY sentiment",
        current_params,
    ).fetchall()
    sentiment_dist = {r["sentiment"]: r["cnt"] for r in sentiment_rows}

    tag_rows = conn.execute(
        f"SELECT tags FROM articles {base_where} AND created_at >= datetime('now', ?)",
        current_params,
    ).fetchall()

    import json
    tag_counts: dict[str, int] = {}
    for row in tag_rows:
        try:
            for tag in json.loads(row["tags"]):
                t = tag.strip().lower()
                if t:
                    tag_counts[t] = tag_counts.get(t, 0) + 1
        except Exception:
            pass
    top_tags = sorted(tag_counts.items(), key=lambda x: x[1], reverse=True)[:10]

    conn.close()
    return {
        "window_hours": window_hours,
        "article_count": current_count,
        "previous_count": previous_count,
        "trend_delta": trend_delta,
        "sentiment_distribution": sentiment_dist,
        "top_tags": [{"tag": t, "count": c} for t, c in top_tags],
    }


def get_trending_data(topic_id: int, days: int = 7):
    """Time-series trending data for charts: daily volume, sentiment, entities."""
    import json as _json
    conn = _conn()

    # Daily article count + sentiment breakdown
    daily_rows = conn.execute(
        """SELECT date(created_at) as day,
                  COUNT(*) as total,
                  SUM(CASE WHEN sentiment='positive' THEN 1 ELSE 0 END) as pos,
                  SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END) as neu,
                  SUM(CASE WHEN sentiment='negative' THEN 1 ELSE 0 END) as neg,
                  AVG(importance) as avg_importance,
                  AVG(topic_relevance) as avg_relevance
           FROM articles
           WHERE topic_id = ? AND created_at >= datetime('now', ?)
           GROUP BY date(created_at)
           ORDER BY day""",
        (topic_id, f"-{days} days"),
    ).fetchall()

    daily = [
        {
            "day": r["day"],
            "total": r["total"],
            "positive": r["pos"],
            "neutral": r["neu"],
            "negative": r["neg"],
            "avg_importance": round(r["avg_importance"] or 0, 1),
            "avg_relevance": round(r["avg_relevance"] or 0, 2),
        }
        for r in daily_rows
    ]

    # Top entities across the window
    entity_rows = conn.execute(
        "SELECT key_entities FROM articles WHERE topic_id = ? AND created_at >= datetime('now', ?)",
        (topic_id, f"-{days} days"),
    ).fetchall()

    entity_counts: dict[str, int] = {}
    for row in entity_rows:
        try:
            for ent in _json.loads(row["key_entities"]):
                e = ent.strip()
                if e:
                    entity_counts[e] = entity_counts.get(e, 0) + 1
        except Exception:
            pass
    top_entities = sorted(entity_counts.items(), key=lambda x: x[1], reverse=True)[:15]

    # Average topic relevance
    rel_row = conn.execute(
        "SELECT AVG(topic_relevance) as avg_rel FROM articles WHERE topic_id = ? AND created_at >= datetime('now', ?)",
        (topic_id, f"-{days} days"),
    ).fetchone()
    avg_topic_relevance = round(rel_row["avg_rel"] or 0, 2)

    conn.close()
    return {
        "days": days,
        "daily": daily,
        "top_entities": [{"entity": e, "count": c} for e, c in top_entities],
        "avg_topic_relevance": avg_topic_relevance,
    }


# ── Task state persistence ───────────────────────────


def task_start(key: str) -> bool:
    """Upsert a running task record. Always succeeds — callers use the in-memory
    set for concurrency control; this just persists the start event for audit."""
    conn = _conn()
    conn.execute(
        """INSERT INTO task_state (key, status, started_at, finished_at, result_summary, error)
           VALUES (?, 'running', datetime('now'), NULL, '', '')
           ON CONFLICT(key) DO UPDATE SET
             status='running', started_at=datetime('now'), finished_at=NULL, result_summary='', error=''""",
        (key,),
    )
    conn.commit()
    conn.close()
    return True


def task_finish(key: str, result_summary: str = "", error: str = ""):
    """Mark a task as finished (success or error)."""
    conn = _conn()
    status = "error" if error else "done"
    conn.execute(
        "UPDATE task_state SET status=?, finished_at=datetime('now'), result_summary=?, error=? WHERE key=?",
        (status, result_summary, error, key),
    )
    conn.commit()
    conn.close()


def task_is_running(key: str) -> bool:
    conn = _conn()
    row = conn.execute("SELECT status FROM task_state WHERE key = ?", (key,)).fetchone()
    conn.close()
    return bool(row and row["status"] == "running")


def task_get(key: str) -> dict | None:
    conn = _conn()
    row = conn.execute("SELECT * FROM task_state WHERE key = ?", (key,)).fetchone()
    conn.close()
    return dict(row) if row else None


def task_cleanup_stale(timeout_minutes: int = 30):
    """Mark running tasks older than timeout as timed-out."""
    conn = _conn()
    conn.execute(
        """UPDATE task_state SET status='timeout', error='exceeded timeout'
           WHERE status='running'
             AND started_at < datetime('now', ?)""",
        (f"-{timeout_minutes} minutes",),
    )
    conn.commit()
    conn.close()
