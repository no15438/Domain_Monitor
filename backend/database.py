import json
import logging
import os
import sqlite3
import uuid

DB_PATH: str | None = None
_log = logging.getLogger(__name__)


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

    conn.executescript("""
        CREATE TABLE IF NOT EXISTS raw_news (
            id TEXT PRIMARY KEY,
            topic_id INTEGER REFERENCES topics(id),
            article_id TEXT,
            url TEXT NOT NULL,
            normalized_url TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            content TEXT DEFAULT '',
            source TEXT DEFAULT '',
            source_type TEXT DEFAULT '',
            published_at TEXT,
            fetched_at TEXT DEFAULT (datetime('now')),
            novelty_score REAL DEFAULT 0,
            noise_score REAL DEFAULT 0,
            authority_score REAL DEFAULT 0,
            freshness_state TEXT DEFAULT 'hot',
            retention_until TEXT,
            metadata_json TEXT DEFAULT '{}'
        );

        CREATE TABLE IF NOT EXISTS events_v2 (
            id TEXT PRIMARY KEY,
            topic_id INTEGER REFERENCES topics(id),
            event_key TEXT NOT NULL,
            title TEXT NOT NULL,
            summary TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            canonical_article_id TEXT,
            first_seen_at TEXT DEFAULT (datetime('now')),
            last_seen_at TEXT DEFAULT (datetime('now')),
            novelty_window_end TEXT,
            stability_score REAL DEFAULT 0,
            fact_confidence REAL DEFAULT 0,
            supersedes_event_id TEXT,
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS event_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            event_id TEXT NOT NULL REFERENCES events_v2(id),
            raw_news_id TEXT REFERENCES raw_news(id),
            article_id TEXT,
            source_rank INTEGER DEFAULT 0,
            source_role TEXT DEFAULT 'supporting',
            is_canonical INTEGER DEFAULT 0,
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS evidence_sets (
            id TEXT PRIMARY KEY,
            topic_id INTEGER REFERENCES topics(id),
            event_id TEXT REFERENCES events_v2(id),
            claim_id TEXT,
            title TEXT NOT NULL DEFAULT '',
            summary TEXT DEFAULT '',
            evidence_type TEXT DEFAULT 'fact',
            stance TEXT DEFAULT 'supporting',
            confidence REAL DEFAULT 0,
            freshness_half_life REAL DEFAULT 7,
            review_state TEXT DEFAULT 'machine_only',
            supporting_event_ids TEXT DEFAULT '[]',
            contradicting_event_ids TEXT DEFAULT '[]',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS claims (
            id TEXT PRIMARY KEY,
            topic_id INTEGER REFERENCES topics(id),
            claim_type TEXT DEFAULT 'fact',
            statement TEXT NOT NULL,
            summary TEXT DEFAULT '',
            status TEXT DEFAULT 'active',
            supporting_evidence_ids TEXT DEFAULT '[]',
            supersedes_claim_id TEXT,
            last_validated_at TEXT DEFAULT (datetime('now')),
            decay_policy TEXT DEFAULT 'medium',
            staleness_status TEXT DEFAULT 'fresh',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now')),
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS claim_evolution (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            claim_id TEXT NOT NULL REFERENCES claims(id),
            previous_claim_id TEXT REFERENCES claims(id),
            relation_type TEXT NOT NULL,
            reason TEXT DEFAULT '',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS temporal_snapshots (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            window_type TEXT DEFAULT 'daily',
            window_start TEXT,
            window_end TEXT,
            summary_text TEXT NOT NULL DEFAULT '',
            stats_metadata TEXT NOT NULL DEFAULT '{}',
            snapshot_status TEXT DEFAULT 'final',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS snapshot_claims (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL REFERENCES temporal_snapshots(id),
            claim_id TEXT NOT NULL REFERENCES claims(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS snapshot_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            snapshot_id INTEGER NOT NULL REFERENCES temporal_snapshots(id),
            event_id TEXT NOT NULL REFERENCES events_v2(id),
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS snapshot_deltas (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            topic_id INTEGER REFERENCES topics(id),
            from_snapshot_id INTEGER REFERENCES temporal_snapshots(id),
            to_snapshot_id INTEGER REFERENCES temporal_snapshots(id),
            change_summary TEXT NOT NULL DEFAULT '',
            new_event_ids TEXT DEFAULT '[]',
            resolved_event_ids TEXT DEFAULT '[]',
            strengthened_claim_ids TEXT DEFAULT '[]',
            weakened_claim_ids TEXT DEFAULT '[]',
            superseded_claim_ids TEXT DEFAULT '[]',
            metadata_json TEXT DEFAULT '{}',
            created_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS synthesis_artifacts (
            id TEXT PRIMARY KEY,
            topic_id INTEGER REFERENCES topics(id),
            artifact_type TEXT NOT NULL,
            title TEXT NOT NULL DEFAULT '',
            content TEXT NOT NULL DEFAULT '',
            status TEXT DEFAULT 'final',
            version INTEGER DEFAULT 1,
            metadata_json TEXT DEFAULT '{}',
            generated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS artifact_sources (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            artifact_id TEXT NOT NULL REFERENCES synthesis_artifacts(id),
            source_type TEXT NOT NULL,
            source_id TEXT NOT NULL,
            created_at TEXT DEFAULT (datetime('now'))
        );
    """)

    _migrate_topic_summaries_to_snapshots(conn)
    _migrate_articles_event_fields(conn)
    _migrate_lineage_tables(conn)

    conn.executescript("""
        CREATE INDEX IF NOT EXISTS idx_articles_topic_id ON articles(topic_id);
        CREATE INDEX IF NOT EXISTS idx_articles_created_at ON articles(created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_articles_status ON articles(status);
        CREATE INDEX IF NOT EXISTS idx_articles_event_id ON articles(event_id);
        CREATE INDEX IF NOT EXISTS idx_articles_url ON articles(url);
        CREATE INDEX IF NOT EXISTS idx_articles_published_at ON articles(published_at DESC);
        CREATE INDEX IF NOT EXISTS idx_keywords_topic_id ON keywords(topic_id);
        CREATE INDEX IF NOT EXISTS idx_feeds_topic_id ON topic_feeds(topic_id);
        CREATE INDEX IF NOT EXISTS idx_raw_news_topic_fetch ON raw_news(topic_id, fetched_at DESC);
        CREATE INDEX IF NOT EXISTS idx_raw_news_normalized_url ON raw_news(normalized_url);
        CREATE INDEX IF NOT EXISTS idx_events_v2_topic_status_seen ON events_v2(topic_id, status, last_seen_at DESC);
        CREATE INDEX IF NOT EXISTS idx_events_v2_event_key ON events_v2(topic_id, event_key);
        CREATE INDEX IF NOT EXISTS idx_event_sources_event_id ON event_sources(event_id);
        CREATE INDEX IF NOT EXISTS idx_evidence_sets_topic_event ON evidence_sets(topic_id, event_id);
        CREATE INDEX IF NOT EXISTS idx_claims_topic_status_validated ON claims(topic_id, status, last_validated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_claims_statement ON claims(topic_id, statement);
        CREATE INDEX IF NOT EXISTS idx_claim_evolution_claim_id ON claim_evolution(claim_id, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_temporal_snapshots_topic_window ON temporal_snapshots(topic_id, window_type, created_at DESC);
        CREATE INDEX IF NOT EXISTS idx_snapshot_claims_snapshot_id ON snapshot_claims(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_snapshot_events_snapshot_id ON snapshot_events(snapshot_id);
        CREATE INDEX IF NOT EXISTS idx_snapshot_deltas_topic_to_snapshot ON snapshot_deltas(topic_id, to_snapshot_id DESC);
        CREATE INDEX IF NOT EXISTS idx_synthesis_artifacts_topic_type ON synthesis_artifacts(topic_id, artifact_type, generated_at DESC);
        CREATE INDEX IF NOT EXISTS idx_artifact_sources_artifact_id ON artifact_sources(artifact_id, source_type, source_id);
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


def _migrate_lineage_tables(conn):
    for col_name, col_def in [
        ("created_at", "TEXT DEFAULT (datetime('now'))"),
    ]:
        try:
            conn.execute(f"ALTER TABLE events_v2 ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass
    for tcol, tdef in [
        ("global_overview", "TEXT"),
        ("research_brief", "TEXT DEFAULT ''"),
        ("research_config", "TEXT DEFAULT '{}'"),
        ("pipeline_config", "TEXT DEFAULT '{}'"),
        ("archived_at", "TEXT"),
        ("sort_order", "INTEGER DEFAULT 0"),
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
        """SELECT * FROM topics
           WHERE is_active = 1 AND archived_at IS NULL
           ORDER BY sort_order ASC, created_at"""
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def reorder_topics(ordered_ids: list[int]):
    """Persist a new display order for topics by updating sort_order."""
    conn = _conn()
    for idx, topic_id in enumerate(ordered_ids):
        conn.execute(
            "UPDATE topics SET sort_order = ? WHERE id = ?",
            (idx, topic_id),
        )
    conn.commit()
    conn.close()


def create_topic(name: str, color: str = "#6366f1"):
    conn = _conn()
    existing = conn.execute(
        "SELECT id, is_active, archived_at FROM topics WHERE name = ?",
        (name,),
    ).fetchone()
    if existing:
        active = bool(existing["is_active"])
        archived = bool(existing["archived_at"])
        if active and not archived:
            conn.close()
            return None
        tid = existing["id"]
        conn.execute(
            "UPDATE topics SET is_active = 1, archived_at = NULL, color = ? WHERE id = ?",
            (color, tid),
        )
        conn.commit()
        conn.close()
        return tid
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


def archive_topic(topic_id: int):
    conn = _conn()
    conn.execute(
        "UPDATE topics SET archived_at = datetime('now') WHERE id = ? AND is_active = 1",
        (topic_id,),
    )
    conn.commit()
    conn.close()


def unarchive_topic(topic_id: int):
    conn = _conn()
    conn.execute(
        "UPDATE topics SET archived_at = NULL WHERE id = ? AND is_active = 1",
        (topic_id,),
    )
    conn.commit()
    conn.close()


def delete_topic(topic_id: int):
    """Permanently remove the topic and all dependent rows (SQLite + Chroma)."""
    tid = (topic_id,)
    conn = _conn()
    try:
        conn.execute(
            "DELETE FROM artifact_sources WHERE artifact_id IN "
            "(SELECT id FROM synthesis_artifacts WHERE topic_id = ?)",
            tid,
        )
        conn.execute("DELETE FROM synthesis_artifacts WHERE topic_id = ?", tid)
        conn.execute("DELETE FROM snapshot_deltas WHERE topic_id = ?", tid)
        conn.execute(
            "DELETE FROM snapshot_claims WHERE snapshot_id IN "
            "(SELECT id FROM temporal_snapshots WHERE topic_id = ?)",
            tid,
        )
        conn.execute(
            "DELETE FROM snapshot_events WHERE snapshot_id IN "
            "(SELECT id FROM temporal_snapshots WHERE topic_id = ?)",
            tid,
        )
        conn.execute("DELETE FROM temporal_snapshots WHERE topic_id = ?", tid)
        conn.execute("DELETE FROM claim_evolution WHERE topic_id = ?", tid)
        conn.execute("DELETE FROM evidence_sets WHERE topic_id = ?", tid)
        conn.execute(
            "UPDATE events_v2 SET supersedes_event_id = NULL WHERE topic_id = ?", tid
        )
        conn.execute(
            "DELETE FROM event_sources WHERE event_id IN "
            "(SELECT id FROM events_v2 WHERE topic_id = ?)",
            tid,
        )
        conn.execute("DELETE FROM events_v2 WHERE topic_id = ?", tid)
        conn.execute(
            "UPDATE claims SET supersedes_claim_id = NULL WHERE topic_id = ?", tid
        )
        conn.execute("DELETE FROM claims WHERE topic_id = ?", tid)
        conn.execute("DELETE FROM raw_news WHERE topic_id = ?", tid)
        conn.execute("DELETE FROM articles WHERE topic_id = ?", tid)
        conn.execute("DELETE FROM topic_feeds WHERE topic_id = ?", tid)
        conn.execute("DELETE FROM keywords WHERE topic_id = ?", tid)
        conn.execute("DELETE FROM topic_snapshots WHERE topic_id = ?", tid)
        conn.execute(
            "DELETE FROM topic_links WHERE source_topic_id = ? OR target_topic_id = ?",
            (topic_id, topic_id),
        )
        for key in (
            f"global-{topic_id}",
            f"live-{topic_id}",
            f"evolution-{topic_id}",
            f"fetch-{topic_id}",
        ):
            conn.execute("DELETE FROM task_state WHERE key = ?", (key,))
        conn.execute("DELETE FROM topics WHERE id = ?", tid)
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    try:
        from vector_store import delete_vector_documents_for_topic

        delete_vector_documents_for_topic(topic_id)
    except Exception as exc:
        _log.warning("Chroma cleanup after topic %s delete failed: %s", topic_id, exc)


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


# ── Knowledge Lineage ────────────────────────────────


def _json_dumps(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_loads(value, default):
    if not value:
        return default
    try:
        return json.loads(value)
    except Exception:
        return default


def _serialize_evidence_row(row: sqlite3.Row | dict) -> dict:
    item = dict(row)
    item["supporting_event_ids"] = _json_loads(item.get("supporting_event_ids"), [])
    item["contradicting_event_ids"] = _json_loads(item.get("contradicting_event_ids"), [])
    item["support_score"] = item.get("confidence", 0.0)
    item["signal_type"] = item.get("evidence_type", "")
    return item


def _serialize_claim_row(row: sqlite3.Row | dict) -> dict:
    item = dict(row)
    item["supporting_evidence_ids"] = _json_loads(item.get("supporting_evidence_ids"), [])
    item["evidence_ids"] = list(item["supporting_evidence_ids"])
    item["claim_kind"] = item.get("claim_type", "")
    item["last_refreshed_at"] = item.get("last_validated_at")
    item["lifecycle_status"] = item.get("status", "")
    item["freshness"] = item.get("staleness_status", "")
    return item


def insert_raw_news(items: list[dict]):
    if not items:
        return
    conn = _conn()
    conn.executemany(
        """INSERT OR REPLACE INTO raw_news
           (id, topic_id, article_id, url, normalized_url, title, content, source, source_type,
            published_at, fetched_at, novelty_score, noise_score, authority_score,
            freshness_state, retention_until, metadata_json)
           VALUES (:id, :topic_id, :article_id, :url, :normalized_url, :title, :content, :source,
                   :source_type, :published_at, COALESCE(:fetched_at, datetime('now')),
                   :novelty_score, :noise_score, :authority_score, :freshness_state,
                   :retention_until, :metadata_json)""",
        items,
    )
    conn.commit()
    conn.close()


def list_raw_news(topic_id: int, limit: int = 100):
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM raw_news
           WHERE topic_id = ?
           ORDER BY fetched_at DESC
           LIMIT ?""",
        (topic_id, limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def upsert_event(
    topic_id: int,
    event_id: str,
    event_key: str,
    title: str,
    summary: str = "",
    status: str = "active",
    canonical_article_id: str | None = None,
    first_seen_at: str | None = None,
    last_seen_at: str | None = None,
    novelty_window_end: str | None = None,
    stability_score: float = 0.0,
    fact_confidence: float = 0.0,
    supersedes_event_id: str | None = None,
    metadata: dict | None = None,
):
    conn = _conn()
    conn.execute(
        """INSERT INTO events_v2
           (id, topic_id, event_key, title, summary, status, canonical_article_id, first_seen_at,
            last_seen_at, novelty_window_end, stability_score, fact_confidence, supersedes_event_id, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, COALESCE(?, datetime('now')), COALESCE(?, datetime('now')), ?, ?, ?, ?, ?)
           ON CONFLICT(id) DO UPDATE SET
             topic_id=excluded.topic_id,
             event_key=excluded.event_key,
             title=excluded.title,
             summary=excluded.summary,
             status=excluded.status,
             canonical_article_id=COALESCE(excluded.canonical_article_id, events_v2.canonical_article_id),
             last_seen_at=COALESCE(excluded.last_seen_at, events_v2.last_seen_at, datetime('now')),
             novelty_window_end=COALESCE(excluded.novelty_window_end, events_v2.novelty_window_end),
             stability_score=excluded.stability_score,
             fact_confidence=excluded.fact_confidence,
             supersedes_event_id=COALESCE(excluded.supersedes_event_id, events_v2.supersedes_event_id),
             metadata_json=excluded.metadata_json""",
        (
            event_id,
            topic_id,
            event_key,
            title,
            summary,
            status,
            canonical_article_id,
            first_seen_at,
            last_seen_at,
            novelty_window_end,
            stability_score,
            fact_confidence,
            supersedes_event_id,
            _json_dumps(metadata or {}),
        ),
    )
    conn.commit()
    conn.close()


def replace_event_sources(event_id: str, sources: list[dict]):
    conn = _conn()
    conn.execute("DELETE FROM event_sources WHERE event_id = ?", (event_id,))
    if sources:
        conn.executemany(
            """INSERT INTO event_sources
               (event_id, raw_news_id, article_id, source_rank, source_role, is_canonical, metadata_json)
               VALUES (:event_id, :raw_news_id, :article_id, :source_rank, :source_role, :is_canonical, :metadata_json)""",
            sources,
        )
    conn.commit()
    conn.close()


def get_recent_event_stubs(topic_id: int, days: int = 7) -> list[dict]:
    """Return lightweight stubs of recent events for pipeline reconciliation.

    Returns id, title, canonical_url so the pipeline can detect whether a new
    cluster matches an existing event before creating a fresh event_id.
    """
    conn = _conn()
    rows = conn.execute(
        """SELECT e.id, e.title, a.url AS canonical_url
           FROM events_v2 e
           LEFT JOIN articles a ON a.id = e.canonical_article_id
           WHERE e.topic_id = ?
             AND e.first_seen_at >= datetime('now', ? || ' days')
           ORDER BY e.first_seen_at DESC
           LIMIT 500""",
        (topic_id, f"-{days}"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_events_v2(topic_id: int, status: str | None = None, limit: int = 50):
    conn = _conn()
    where = "WHERE topic_id = ?"
    params: list = [topic_id]
    if status:
        where += " AND status = ?"
        params.append(status)
    rows = conn.execute(
        f"""SELECT * FROM events_v2
            {where}
            ORDER BY last_seen_at DESC, created_at DESC
            LIMIT ?""",
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_events_since(topic_id: int, days: int = 14, limit: int = 50) -> list[dict]:
    """Return events whose last_seen_at is within the past `days` days.

    Falls back to any active events when none are found in the window (so
    callers always get *something* if active events exist at all).
    """
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM events_v2
           WHERE topic_id = ?
             AND status = 'active'
             AND last_seen_at >= datetime('now', ?)
           ORDER BY last_seen_at DESC, created_at DESC
           LIMIT ?""",
        (topic_id, f"-{days} days", limit),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_fresh_claims(topic_id: int, limit: int = 30) -> list[dict]:
    """Return claims that are actively fresh: status=active AND staleness_status=fresh."""
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM claims
           WHERE topic_id = ?
             AND status = 'active'
             AND staleness_status = 'fresh'
           ORDER BY last_validated_at DESC, created_at DESC
           LIMIT ?""",
        (topic_id, limit),
    ).fetchall()
    conn.close()
    return [_serialize_claim_row(r) for r in rows]


def get_event_by_id(event_id: str):
    conn = _conn()
    row = conn.execute("SELECT * FROM events_v2 WHERE id = ?", (event_id,)).fetchone()
    conn.close()
    return dict(row) if row else None


def upsert_evidence_set(
    evidence_id: str,
    topic_id: int,
    event_id: str,
    claim_id: str | None,
    title: str,
    summary: str,
    evidence_type: str = "fact",
    stance: str = "supporting",
    confidence: float = 0.0,
    freshness_half_life: float = 7.0,
    review_state: str = "machine_only",
    supporting_event_ids: list[str] | None = None,
    contradicting_event_ids: list[str] | None = None,
    metadata: dict | None = None,
):
    conn = _conn()
    conn.execute(
        """INSERT INTO evidence_sets
           (id, topic_id, event_id, claim_id, title, summary, evidence_type, stance, confidence,
            freshness_half_life, review_state, supporting_event_ids, contradicting_event_ids,
            metadata_json, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(id) DO UPDATE SET
             topic_id=excluded.topic_id,
             event_id=excluded.event_id,
             claim_id=excluded.claim_id,
             title=excluded.title,
             summary=excluded.summary,
             evidence_type=excluded.evidence_type,
             stance=excluded.stance,
             confidence=excluded.confidence,
             freshness_half_life=excluded.freshness_half_life,
             review_state=excluded.review_state,
             supporting_event_ids=excluded.supporting_event_ids,
             contradicting_event_ids=excluded.contradicting_event_ids,
             metadata_json=excluded.metadata_json,
             updated_at=datetime('now')""",
        (
            evidence_id,
            topic_id,
            event_id,
            claim_id,
            title,
            summary,
            evidence_type,
            stance,
            confidence,
            freshness_half_life,
            review_state,
            _json_dumps(supporting_event_ids or []),
            _json_dumps(contradicting_event_ids or []),
            _json_dumps(metadata or {}),
        ),
    )
    conn.commit()
    conn.close()


def list_evidence_sets(topic_id: int, limit: int = 100):
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM evidence_sets
           WHERE topic_id = ?
           ORDER BY updated_at DESC, created_at DESC
           LIMIT ?""",
        (topic_id, limit),
    ).fetchall()
    conn.close()
    return [_serialize_evidence_row(r) for r in rows]


def get_evidence_sets_for_claim(topic_id: int, claim_id: str):
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM evidence_sets
           WHERE topic_id = ? AND claim_id = ?
           ORDER BY updated_at DESC, created_at DESC""",
        (topic_id, claim_id),
    ).fetchall()
    conn.close()
    return [_serialize_evidence_row(r) for r in rows]


def _normalize_statement(statement: str) -> str:
    return " ".join((statement or "").strip().lower().split())


def find_similar_claim(topic_id: int, statement: str):
    normalized = _normalize_statement(statement)
    if not normalized:
        return None
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM claims
           WHERE topic_id = ?
           ORDER BY updated_at DESC, created_at DESC
           LIMIT 200""",
        (topic_id,),
    ).fetchall()
    conn.close()
    for row in rows:
        item = dict(row)
        if _normalize_statement(item.get("statement", "")) == normalized:
            return item
    return None


def upsert_claim(
    topic_id: int,
    statement: str,
    claim_id: str | None = None,
    claim_type: str = "fact",
    summary: str = "",
    status: str = "active",
    supporting_evidence_ids: list[str] | None = None,
    supersedes_claim_id: str | None = None,
    decay_policy: str = "medium",
    staleness_status: str = "fresh",
    metadata: dict | None = None,
) -> str:
    existing = find_similar_claim(topic_id, statement)
    claim_id = claim_id or (existing["id"] if existing else str(uuid.uuid4()))
    merged_evidence_ids = list(supporting_evidence_ids or [])
    if existing:
        for evidence_id in _json_loads(existing.get("supporting_evidence_ids"), []):
            if evidence_id not in merged_evidence_ids:
                merged_evidence_ids.append(evidence_id)
    conn = _conn()
    conn.execute(
        """INSERT INTO claims
           (id, topic_id, claim_type, statement, summary, status, supporting_evidence_ids,
            supersedes_claim_id, last_validated_at, decay_policy, staleness_status, metadata_json,
            updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'), ?, ?, ?, datetime('now'))
           ON CONFLICT(id) DO UPDATE SET
             claim_type=excluded.claim_type,
             statement=excluded.statement,
             summary=excluded.summary,
             status=excluded.status,
             supporting_evidence_ids=excluded.supporting_evidence_ids,
             supersedes_claim_id=COALESCE(excluded.supersedes_claim_id, claims.supersedes_claim_id),
             last_validated_at=datetime('now'),
             decay_policy=excluded.decay_policy,
             staleness_status=excluded.staleness_status,
             metadata_json=excluded.metadata_json,
             updated_at=datetime('now')""",
        (
            claim_id,
            topic_id,
            claim_type,
            statement,
            summary,
            status,
            _json_dumps(merged_evidence_ids),
            supersedes_claim_id,
            decay_policy,
            staleness_status,
            _json_dumps(metadata or {}),
        ),
    )
    conn.commit()
    conn.close()
    return claim_id


def add_claim_evolution(
    topic_id: int,
    claim_id: str,
    previous_claim_id: str | None,
    relation_type: str,
    reason: str = "",
    metadata: dict | None = None,
):
    conn = _conn()
    conn.execute(
        """INSERT INTO claim_evolution
           (topic_id, claim_id, previous_claim_id, relation_type, reason, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (topic_id, claim_id, previous_claim_id, relation_type, reason, _json_dumps(metadata or {})),
    )
    conn.commit()
    conn.close()


def get_claim_evolution(topic_id: int, claim_id: str | None = None, limit: int = 200):
    conn = _conn()
    where = "WHERE topic_id = ?"
    params: list = [topic_id]
    if claim_id is not None:
        where += " AND (claim_id = ? OR previous_claim_id = ?)"
        params.extend([claim_id, claim_id])
    rows = conn.execute(
        f"""SELECT * FROM claim_evolution
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?""",
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_claim_lifecycle(
    claim_id: str,
    *,
    status: str,
    staleness_status: str,
    last_validated_at: str | None = None,
    supersedes_claim_id: str | None = None,
    metadata: dict | None = None,
):
    conn = _conn()
    fields = [
        "status = ?",
        "staleness_status = ?",
        "updated_at = datetime('now')",
    ]
    params: list = [status, staleness_status]
    if last_validated_at is not None:
        fields.append("last_validated_at = ?")
        params.append(last_validated_at)
    if supersedes_claim_id is not None:
        fields.append("supersedes_claim_id = ?")
        params.append(supersedes_claim_id)
    if metadata is not None:
        fields.append("metadata_json = ?")
        params.append(_json_dumps(metadata))
    params.append(claim_id)
    conn.execute(
        f"UPDATE claims SET {', '.join(fields)} WHERE id = ?",
        params,
    )
    conn.commit()
    conn.close()


def get_claims_v2(topic_id: int, status: str | None = None, limit: int = 100):
    conn = _conn()
    where = "WHERE topic_id = ?"
    params: list = [topic_id]
    if status:
        where += " AND status = ?"
        params.append(status)
    rows = conn.execute(
        f"""SELECT * FROM claims
            {where}
            ORDER BY last_validated_at DESC, created_at DESC
            LIMIT ?""",
        params + [limit],
    ).fetchall()
    conn.close()
    return [_serialize_claim_row(row) for row in rows]


def get_active_claims(topic_id: int, limit: int = 100):
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM claims
           WHERE topic_id = ? AND status IN ('active', 'stale')
           ORDER BY last_validated_at DESC, created_at DESC
           LIMIT ?""",
        (topic_id, limit),
    ).fetchall()
    conn.close()
    return [_serialize_claim_row(row) for row in rows]


def get_claims_by_ids(claim_ids: list[str]) -> list[dict]:
    """Return claim records for a given list of claim UUIDs (preserving order)."""
    if not claim_ids:
        return []
    conn = _conn()
    placeholders = ",".join("?" * len(claim_ids))
    rows = conn.execute(
        f"SELECT * FROM claims WHERE id IN ({placeholders})",
        claim_ids,
    ).fetchall()
    conn.close()
    id_order = {cid: i for i, cid in enumerate(claim_ids)}
    result = sorted(
        [_serialize_claim_row(r) for r in rows],
        key=lambda r: id_order.get(r["id"], 9999),
    )
    return result


def get_claims_for_event(event_id: str, limit: int = 20) -> list[dict]:
    """Return claims associated with an event via evidence_sets.

    A claim is linked to this event if at least one evidence_set row has
    both event_id = ? and a non-null claim_id referencing that claim.
    Each result includes an evidence_count field reflecting how many
    evidence rows for this event support that claim.
    """
    conn = _conn()
    rows = conn.execute(
        """SELECT c.*,
                  COUNT(es.id) AS evidence_count
           FROM claims c
           INNER JOIN evidence_sets es ON es.claim_id = c.id AND es.event_id = ?
           WHERE c.status IN ('active', 'stale', 'superseded')
           GROUP BY c.id
           ORDER BY c.last_validated_at DESC, c.created_at DESC
           LIMIT ?""",
        (event_id, limit),
    ).fetchall()
    conn.close()
    results = []
    for row in rows:
        item = _serialize_claim_row(row)
        item["evidence_count"] = row["evidence_count"]
        results.append(item)
    return results


def get_current_claims(topic_id: int, limit: int = 100):
    return get_active_claims(topic_id, limit=limit)


def save_temporal_snapshot(
    topic_id: int,
    summary_text: str,
    stats_metadata: str = "{}",
    window_type: str = "daily",
    window_start: str | None = None,
    window_end: str | None = None,
    snapshot_status: str = "final",
    event_ids: list[str] | None = None,
    claim_ids: list[str] | None = None,
) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO temporal_snapshots
           (topic_id, window_type, window_start, window_end, summary_text, stats_metadata, snapshot_status)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (topic_id, window_type, window_start, window_end, summary_text, stats_metadata, snapshot_status),
    )
    snapshot_id = cur.lastrowid
    if event_ids:
        conn.executemany(
            "INSERT INTO snapshot_events (snapshot_id, event_id) VALUES (?, ?)",
            [(snapshot_id, event_id) for event_id in event_ids],
        )
    if claim_ids:
        conn.executemany(
            "INSERT INTO snapshot_claims (snapshot_id, claim_id) VALUES (?, ?)",
            [(snapshot_id, claim_id) for claim_id in claim_ids],
        )
    conn.commit()
    conn.close()
    return snapshot_id


def get_temporal_snapshots(topic_id: int, window_type: str | None = None, limit: int = 20):
    conn = _conn()
    where = "WHERE topic_id = ?"
    params: list = [topic_id]
    if window_type:
        where += " AND window_type = ?"
        params.append(window_type)
    rows = conn.execute(
        f"""SELECT * FROM temporal_snapshots
            {where}
            ORDER BY created_at DESC, id DESC
            LIMIT ?""",
        params + [limit],
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_latest_temporal_snapshot(topic_id: int, window_type: str = "daily"):
    rows = get_temporal_snapshots(topic_id, window_type=window_type, limit=1)
    return rows[0] if rows else None


def get_snapshot_events(snapshot_id: int):
    conn = _conn()
    rows = conn.execute(
        """SELECT e.* FROM snapshot_events se
           JOIN events_v2 e ON e.id = se.event_id
           WHERE se.snapshot_id = ?
           ORDER BY e.last_seen_at DESC""",
        (snapshot_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_snapshot_claims(snapshot_id: int):
    conn = _conn()
    rows = conn.execute(
        """SELECT c.* FROM snapshot_claims sc
           JOIN claims c ON c.id = sc.claim_id
           WHERE sc.snapshot_id = ?
           ORDER BY c.last_validated_at DESC""",
        (snapshot_id,),
    ).fetchall()
    conn.close()
    return [_serialize_claim_row(row) for row in rows]


def save_snapshot_delta(
    topic_id: int,
    from_snapshot_id: int | None,
    to_snapshot_id: int,
    change_summary: str,
    new_event_ids: list[str] | None = None,
    resolved_event_ids: list[str] | None = None,
    strengthened_claim_ids: list[str] | None = None,
    weakened_claim_ids: list[str] | None = None,
    superseded_claim_ids: list[str] | None = None,
    metadata: dict | None = None,
) -> int:
    conn = _conn()
    cur = conn.execute(
        """INSERT INTO snapshot_deltas
           (topic_id, from_snapshot_id, to_snapshot_id, change_summary, new_event_ids, resolved_event_ids,
            strengthened_claim_ids, weakened_claim_ids, superseded_claim_ids, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            topic_id,
            from_snapshot_id,
            to_snapshot_id,
            change_summary,
            _json_dumps(new_event_ids or []),
            _json_dumps(resolved_event_ids or []),
            _json_dumps(strengthened_claim_ids or []),
            _json_dumps(weakened_claim_ids or []),
            _json_dumps(superseded_claim_ids or []),
            _json_dumps(metadata or {}),
        ),
    )
    delta_id = cur.lastrowid
    conn.commit()
    conn.close()
    return delta_id


def get_snapshot_deltas(topic_id: int, limit: int = 20):
    conn = _conn()
    rows = conn.execute(
        """SELECT * FROM snapshot_deltas
           WHERE topic_id = ?
           ORDER BY created_at DESC, id DESC
           LIMIT ?""",
        (topic_id, limit),
    ).fetchall()
    conn.close()
    result = []
    for row in rows:
        item = dict(row)
        for key in (
            "new_event_ids",
            "resolved_event_ids",
            "strengthened_claim_ids",
            "weakened_claim_ids",
            "superseded_claim_ids",
        ):
            item[key] = _json_loads(item.get(key), [])
        result.append(item)
    return result


def upsert_synthesis_artifact(
    topic_id: int,
    artifact_type: str,
    title: str,
    content: str,
    status: str = "final",
    version: int = 1,
    metadata: dict | None = None,
    source_snapshot_ids: list[int] | None = None,
    source_delta_ids: list[int] | None = None,
    source_claim_ids: list[str] | None = None,
) -> str:
    artifact_id = str(uuid.uuid4())
    conn = _conn()
    conn.execute(
        """INSERT INTO synthesis_artifacts
           (id, topic_id, artifact_type, title, content, status, version, metadata_json)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
        (artifact_id, topic_id, artifact_type, title, content, status, version, _json_dumps(metadata or {})),
    )
    source_rows = []
    for snapshot_id in source_snapshot_ids or []:
        source_rows.append((artifact_id, "snapshot", str(snapshot_id)))
    for delta_id in source_delta_ids or []:
        source_rows.append((artifact_id, "delta", str(delta_id)))
    for claim_id in source_claim_ids or []:
        source_rows.append((artifact_id, "claim", claim_id))
    if source_rows:
        conn.executemany(
            "INSERT INTO artifact_sources (artifact_id, source_type, source_id) VALUES (?, ?, ?)",
            source_rows,
        )
    conn.commit()
    conn.close()
    return artifact_id


def replace_synthesis_artifact(
    topic_id: int,
    artifact_type: str,
    title: str,
    content: str,
    status: str = "final",
    metadata: dict | None = None,
    source_snapshot_ids: list[int] | None = None,
    source_delta_ids: list[int] | None = None,
    source_claim_ids: list[str] | None = None,
) -> str:
    conn = _conn()
    existing = conn.execute(
        """SELECT id, version FROM synthesis_artifacts
           WHERE topic_id = ? AND artifact_type = ?
           ORDER BY generated_at DESC LIMIT 1""",
        (topic_id, artifact_type),
    ).fetchone()
    artifact_id = existing["id"] if existing else str(uuid.uuid4())
    version = int(existing["version"]) + 1 if existing else 1
    conn.execute("DELETE FROM artifact_sources WHERE artifact_id = ?", (artifact_id,))
    conn.execute(
        """INSERT INTO synthesis_artifacts
           (id, topic_id, artifact_type, title, content, status, version, metadata_json, generated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, datetime('now'))
           ON CONFLICT(id) DO UPDATE SET
             title=excluded.title,
             content=excluded.content,
             status=excluded.status,
             version=excluded.version,
             metadata_json=excluded.metadata_json,
             generated_at=datetime('now')""",
        (artifact_id, topic_id, artifact_type, title, content, status, version, _json_dumps(metadata or {})),
    )
    source_rows = []
    for snapshot_id in source_snapshot_ids or []:
        source_rows.append((artifact_id, "snapshot", str(snapshot_id)))
    for delta_id in source_delta_ids or []:
        source_rows.append((artifact_id, "delta", str(delta_id)))
    for claim_id in source_claim_ids or []:
        source_rows.append((artifact_id, "claim", claim_id))
    if source_rows:
        conn.executemany(
            "INSERT INTO artifact_sources (artifact_id, source_type, source_id) VALUES (?, ?, ?)",
            source_rows,
        )
    conn.commit()
    conn.close()
    return artifact_id


def get_synthesis_artifact(topic_id: int, artifact_type: str):
    conn = _conn()
    row = conn.execute(
        """SELECT * FROM synthesis_artifacts
           WHERE topic_id = ? AND artifact_type = ?
           ORDER BY generated_at DESC LIMIT 1""",
        (topic_id, artifact_type),
    ).fetchone()
    if not row:
        conn.close()
        return None
    artifact = dict(row)
    artifact["metadata"] = _json_loads(artifact.get("metadata_json"), {})
    source_rows = conn.execute(
        "SELECT source_type, source_id FROM artifact_sources WHERE artifact_id = ?",
        (artifact["id"],),
    ).fetchall()
    conn.close()
    artifact["sources"] = [dict(r) for r in source_rows]
    return artifact


def list_artifact_sources(artifact_id: str):
    conn = _conn()
    rows = conn.execute(
        "SELECT source_type, source_id FROM artifact_sources WHERE artifact_id = ?",
        (artifact_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


# ── Articles ──────────────────────────────────────────


def delete_article(article_id: str) -> bool:
    conn = _conn()
    cur = conn.execute("DELETE FROM articles WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def archive_article(article_id: str) -> bool:
    conn = _conn()
    cur = conn.execute("UPDATE articles SET status = 'archived' WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def restore_article(article_id: str) -> bool:
    conn = _conn()
    cur = conn.execute("UPDATE articles SET status = 'active' WHERE id = ?", (article_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def get_articles(limit=50, offset=0, topic_id=None, sort="relevance", status="active", event_id=None):
    conn = _conn()
    order = (
        "ORDER BY (importance * EXP(-0.023 * MAX(julianday('now') - julianday(COALESCE(published_at, created_at)), 0))) DESC, COALESCE(published_at, created_at) DESC"
        if sort == "relevance"
        else "ORDER BY COALESCE(published_at, created_at) DESC"
    )
    where_parts = ["1=1"]
    params: list = []
    if topic_id is not None:
        where_parts.append("topic_id = ?")
        params.append(topic_id)
    if event_id is not None:
        where_parts.append("event_id = ?")
        params.append(event_id)
    if status:
        where_parts.append("COALESCE(status, 'active') = ?")
        params.append(status)
    where = "WHERE " + " AND ".join(where_parts)
    base = f"SELECT * FROM articles {where} {order} LIMIT ? OFFSET ?"
    rows = conn.execute(base, params + [limit, offset]).fetchall()
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


def update_article_event_fields(url: str, event_id: str, is_canonical: int, event_size: int) -> None:
    """Update event linkage fields on an already-stored article.

    Called when the pipeline re-encounters a URL that is already in the DB but
    belongs to a different (or newly-computed) event cluster.  Keeps event_id,
    is_canonical, and event_size in sync so get_event_alternatives() works.
    """
    conn = _conn()
    conn.execute(
        "UPDATE articles SET event_id = ?, is_canonical = ?, event_size = ? WHERE url = ?",
        (event_id, is_canonical, event_size, url),
    )
    conn.commit()
    conn.close()


def get_article_count(topic_id=None, status="active", event_id=None):
    conn = _conn()
    where_parts = ["1=1"]
    params: list = []
    if topic_id is not None:
        where_parts.append("topic_id = ?")
        params.append(topic_id)
    if event_id is not None:
        where_parts.append("event_id = ?")
        params.append(event_id)
    if status:
        where_parts.append("COALESCE(status, 'active') = ?")
        params.append(status)
    where = "WHERE " + " AND ".join(where_parts)
    count = conn.execute(f"SELECT COUNT(*) FROM articles {where}", params).fetchone()[0]
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


def toggle_article_kept(article_id: str, is_kept: int) -> bool:
    """Toggle the is_kept status of an article."""
    conn = _conn()
    cur = conn.execute("UPDATE articles SET is_kept = ? WHERE id = ?", (is_kept, article_id))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


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


def _analysis_ts_expr(alias: str = "") -> str:
    """SQL expression for analysis timeline timestamp.

    Prefer published_at when it parses as a valid datetime; otherwise fallback
    to created_at. Alias should include trailing dot when needed (e.g. 'a.').
    """
    prefix = alias or ""
    return (
        "COALESCE("
        f"datetime(NULLIF({prefix}published_at, '')),"
        f"datetime({prefix}created_at)"
        ")"
    )


def get_insight_summary(topic_id=None, hours=24):
    """Aggregate stats: top events, counts, source distribution."""
    conn = _conn()
    hour_arg = f"-{hours} hours"
    # Table-qualify columns so JOIN subqueries never see ambiguous names (e.g. status on a vs e).
    base_where = "WHERE COALESCE(articles.status, 'active') = 'active'"
    params: list = []

    if topic_id is not None:
        base_where += " AND articles.topic_id = ?"
        params.append(topic_id)

    analysis_ts = _analysis_ts_expr("articles.")
    base_where += f" AND {analysis_ts} >= datetime('now', ?)"
    params_with_time = params + [hour_arg]

    total = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where}",
        params_with_time,
    ).fetchone()[0]

    important = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where} AND articles.importance >= 8",
        params_with_time,
    ).fetchone()[0]

    source_rows = conn.execute(
        f"SELECT articles.source_type, COUNT(*) as cnt FROM articles {base_where} GROUP BY articles.source_type ORDER BY cnt DESC",
        params_with_time,
    ).fetchall()
    source_dist = {r["source_type"]: r["cnt"] for r in source_rows}

    sentiment_rows = conn.execute(
        f"SELECT articles.sentiment, COUNT(*) as cnt FROM articles {base_where} GROUP BY articles.sentiment",
        params_with_time,
    ).fetchall()
    sentiment_dist = {r["sentiment"]: r["cnt"] for r in sentiment_rows}

    join_where = "WHERE COALESCE(a.status, 'active') = 'active'"
    join_params: list = []
    if topic_id is not None:
        join_where += " AND a.topic_id = ?"
        join_params.append(topic_id)
    join_analysis_ts = _analysis_ts_expr("a.")
    join_where += f" AND {join_analysis_ts} >= datetime('now', ?) AND a.is_canonical = 1"
    join_params.append(hour_arg)

    top_events = conn.execute(
        f"""SELECT
                COALESCE(e.id, a.event_id, a.id)                              AS id,
                a.topic_id,
                COALESCE(e.title, a.title)                                     AS title,
                COALESCE(NULLIF(e.summary, ''), a.summary, '')                 AS summary,
                COALESCE(a.status, 'active')                                   AS status,
                COALESCE(e.status, 'active')                                   AS event_status,
                COALESCE(e.canonical_article_id, a.id)                         AS canonical_article_id,
                a.url                                                           AS canonical_url,
                a.source                                                        AS canonical_source,
                a.source_type,
                COALESCE(a.source_score, 0)                                    AS source_score,
                COALESCE(a.sentiment, 'neutral')                               AS sentiment,
                COALESCE(a.importance, 5)                                       AS importance,
                COALESCE(a.tags, '[]')                                          AS tags,
                COALESCE(a.is_kept, 0)                                          AS is_kept,
                a.published_at,
                a.created_at,
                COALESCE(e.first_seen_at, a.published_at, a.created_at)        AS first_seen_at,
                COALESCE(e.last_seen_at, a.published_at, a.created_at)         AS last_seen_at,
                COALESCE(e.stability_score, 0)                                  AS stability_score,
                COALESCE(e.fact_confidence, 0)                                  AS fact_confidence,
                (SELECT COUNT(*) FROM articles sub
                 WHERE sub.event_id = COALESCE(e.id, a.event_id)
                   AND sub.event_id IS NOT NULL
                   AND sub.event_id != '')                                       AS source_count
            FROM articles a
            LEFT JOIN events_v2 e ON e.id = a.event_id
            {join_where}
            ORDER BY source_count DESC,
                     (a.importance * EXP(-0.023 * MAX(julianday('now') - julianday(COALESCE(a.published_at, a.created_at)), 0))) DESC,
                     a.source_score DESC
            LIMIT 5""",
        join_params,
    ).fetchall()

    conn.close()
    return {
        "total_articles": total,
        "important_count": important,
        "source_distribution": source_dist,
        "sentiment_distribution": sentiment_dist,
        "top_events": [dict(r) for r in top_events],
    }


def get_event_card_summaries(topic_id=None, limit=30, offset=0, sort="relevance", status="active"):
    """Return lightweight event card summaries for the Events list view.

    Primary table is articles (canonical=1) LEFT JOIN events_v2 for backward
    compatibility with events that predate the events_v2 table.
    Includes preview_sources (top 2 non-canonical source names) as a JSON array.
    Does NOT return content / key_entities / topic_analysis — use get_event_detail().
    """
    conn = _conn()

    where_parts = [
        "a.is_canonical = 1",
        "COALESCE(a.status, 'active') = ?",
    ]
    params: list = [status]

    if topic_id is not None:
        where_parts.append("a.topic_id = ?")
        params.append(topic_id)

    where = "WHERE " + " AND ".join(where_parts)
    eid_expr = "COALESCE(e.id, a.event_id)"

    order = (
        f"ORDER BY (COALESCE(a.importance, 5) * EXP(-0.023 * MAX(julianday('now') - julianday(COALESCE(a.published_at, a.created_at)), 0))) DESC, source_count DESC, COALESCE(a.published_at, a.created_at) DESC"
        if sort == "relevance"
        else "ORDER BY COALESCE(a.published_at, a.created_at) DESC"
    )

    rows = conn.execute(
        f"""
        SELECT
            {eid_expr}                                                         AS id,
            a.topic_id,
            COALESCE(e.title, a.title)                                         AS title,
            COALESCE(NULLIF(e.summary, ''), a.summary, '')                     AS summary,
            COALESCE(a.status, 'active')                                       AS status,
            COALESCE(e.status, 'active')                                       AS event_status,
            COALESCE(e.canonical_article_id, a.id)                             AS canonical_article_id,
            a.url                                                               AS canonical_url,
            a.source                                                            AS canonical_source,
            a.source_type,
            COALESCE(a.source_score, 0)                                        AS source_score,
            COALESCE(a.sentiment, 'neutral')                                   AS sentiment,
            COALESCE(a.importance, 5)                                          AS importance,
            COALESCE(a.tags, '[]')                                             AS tags,
            COALESCE(a.is_kept, 0)                                             AS is_kept,
            a.published_at,
            a.created_at,
            COALESCE(e.first_seen_at, a.published_at, a.created_at)            AS first_seen_at,
            COALESCE(e.last_seen_at, a.published_at, a.created_at)             AS last_seen_at,
            COALESCE(e.stability_score, 0)                                     AS stability_score,
            COALESCE(e.fact_confidence, 0)                                     AS fact_confidence,
            (SELECT COUNT(*) FROM articles sub
             WHERE sub.event_id = {eid_expr}
               AND sub.event_id IS NOT NULL
               AND sub.event_id != '')                                          AS source_count,
            (SELECT json_group_array(json_object(
                        'source', ps.source,
                        'title',  ps.title,
                        'url',    ps.url,
                        'source_score', ps.source_score
                    ))
             FROM (SELECT source, title, url, source_score
                   FROM articles ps
                   WHERE ps.event_id = {eid_expr}
                     AND ps.is_canonical = 0
                     AND ps.event_id IS NOT NULL
                   ORDER BY ps.source_score DESC
                   LIMIT 2) ps)                                                 AS preview_sources
        FROM articles a
        LEFT JOIN events_v2 e ON e.id = a.event_id
        {where}
        {order}
        LIMIT ? OFFSET ?
        """,
        params + [limit, offset],
    ).fetchall()

    # Filter out single-source events — only show true multi-source aggregations
    rows = [r for r in rows if (r["source_count"] or 0) >= 2]

    # One row per logical event: multiple canonical rows can share the same event_id
    # (merge artifacts, bad data), which would duplicate React keys in the UI.
    _seen_ids: set[str] = set()
    _deduped: list = []
    for r in rows:
        rid = r["id"]
        if not rid or rid in _seen_ids:
            continue
        _seen_ids.add(rid)
        _deduped.append(r)
    rows = _deduped

    total = conn.execute(
        f"SELECT COUNT(*) FROM articles a {where}",
        params,
    ).fetchone()[0]

    conn.close()
    return rows, total


def get_event_detail(event_id: str) -> dict | None:
    """Return full event detail including canonical article content and all sources.

    Used by the event card expanded view and Ask AI context.
    Returns None if the event_id is not found.
    """
    conn = _conn()

    row = conn.execute(
        """
        SELECT
            COALESCE(e.id, a.event_id, a.id)                              AS id,
            a.topic_id,
            COALESCE(e.title, a.title)                                     AS title,
            COALESCE(NULLIF(e.summary, ''), a.summary, '')                 AS summary,
            COALESCE(a.status, 'active')                                   AS status,
            COALESCE(e.status, 'active')                                   AS event_status,
            COALESCE(e.canonical_article_id, a.id)                         AS canonical_article_id,
            a.url                                                           AS canonical_url,
            a.source                                                        AS canonical_source,
            a.source_type,
            COALESCE(a.source_score, 0)                                    AS source_score,
            COALESCE(a.sentiment, 'neutral')                               AS sentiment,
            COALESCE(a.importance, 5)                                      AS importance,
            COALESCE(a.tags, '[]')                                         AS tags,
            COALESCE(a.is_kept, 0)                                         AS is_kept,
            a.published_at,
            a.created_at,
            COALESCE(e.first_seen_at, a.published_at, a.created_at)        AS first_seen_at,
            COALESCE(e.last_seen_at, a.published_at, a.created_at)         AS last_seen_at,
            COALESCE(e.stability_score, 0)                                 AS stability_score,
            COALESCE(e.fact_confidence, 0)                                 AS fact_confidence,
            -- Canonical article full-text fields for chat / search context
            a.content                                                       AS canonical_content,
            a.key_entities                                                  AS canonical_key_entities,
            a.topic_analysis                                                AS canonical_topic_analysis,
            -- Store the canonical article's own event_id for sources lookup
            a.event_id                                                      AS article_event_id,
            (SELECT COUNT(*) FROM articles sub
             WHERE sub.event_id = COALESCE(e.id, a.event_id)
               AND sub.event_id IS NOT NULL
               AND sub.event_id != '')                                      AS source_count
        FROM articles a
        LEFT JOIN events_v2 e ON e.id = a.event_id
        WHERE COALESCE(e.id, a.event_id, a.id) = ?
          AND a.is_canonical = 1
        LIMIT 1
        """,
        (event_id,),
    ).fetchone()

    if row is None:
        conn.close()
        return None

    detail = dict(row)

    # Use the canonical article's own event_id for sources lookup — avoids
    # the mismatch where events_v2.id differs from articles.event_id.
    article_event_id = detail.pop("article_event_id", None) or event_id

    sources = conn.execute(
        """SELECT id, title, source, url, published_at, source_score, source_type, is_canonical
           FROM articles
           WHERE event_id = ?
           ORDER BY is_canonical DESC, source_score DESC""",
        (article_event_id,),
    ).fetchall()
    detail["sources"] = [dict(s) for s in sources]

    conn.close()
    return detail


def get_event_clusters(topic_id=None, limit=30, offset=0, sort="relevance", status="active"):
    """Kept for backward compatibility — delegates to get_event_card_summaries()."""
    return get_event_card_summaries(topic_id=topic_id, limit=limit, offset=offset, sort=sort, status=status)


def get_event_sources(event_id: str) -> list[dict]:
    """Return all articles belonging to this event cluster, ordered canonical-first."""
    conn = _conn()
    rows = conn.execute(
        """SELECT id, title, source, url, published_at, source_score, source_type, is_canonical
           FROM articles
           WHERE event_id = ?
           ORDER BY is_canonical DESC, source_score DESC""",
        (event_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def archive_event_cluster(event_id: str):
    """Archive the canonical article of this event cluster."""
    conn = _conn()
    conn.execute(
        "UPDATE articles SET status = 'archived' WHERE event_id = ? AND is_canonical = 1",
        (event_id,),
    )
    conn.commit()
    conn.close()


def restore_event_cluster(event_id: str):
    """Restore the canonical article of this event cluster."""
    conn = _conn()
    conn.execute(
        "UPDATE articles SET status = 'active' WHERE event_id = ? AND is_canonical = 1",
        (event_id,),
    )
    conn.commit()
    conn.close()


def delete_event_cluster(event_id: str) -> bool:
    """Delete all articles in this cluster and the events_v2 entry."""
    conn = _conn()
    conn.execute("DELETE FROM articles WHERE event_id = ?", (event_id,))
    cur = conn.execute("DELETE FROM events_v2 WHERE id = ?", (event_id,))
    conn.commit()
    conn.close()
    return cur.rowcount > 0


def deduplicate_events(topic_id: int, similarity_threshold: float = 0.40) -> int:
    """Find near-duplicate events for a topic and merge the weaker one into the stronger.

    Two events are considered duplicates when their titles have similarity >=
    similarity_threshold.  The event with more sources (higher stability_score)
    is kept; articles belonging to the weaker event are re-assigned to the keeper
    and the weaker events_v2 row is deleted.

    Returns the number of merge operations performed.
    """
    from difflib import SequenceMatcher
    import re as _re

    _CJK = _re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf]")

    def _norm(t: str) -> str:
        return _re.sub(r"[^\w\s]", "", t, flags=_re.UNICODE).lower().strip()

    def _ngrams(t: str, n: int = 2) -> set:
        grams: set = set()
        for tok in t.split():
            if not _CJK.search(tok) and len(tok) >= 3:
                grams.add(tok)
        cjk = "".join(_CJK.findall(t))
        for i in range(len(cjk) - n + 1):
            grams.add(cjk[i:i + n])
        return grams

    def _sim(a: str, b: str) -> float:
        na, nb = _norm(a), _norm(b)
        seq = SequenceMatcher(None, na, nb).ratio()
        wa, wb = _ngrams(na), _ngrams(nb)
        if not wa or not wb:
            return seq
        overlap = len(wa & wb) / min(len(wa), len(wb))
        return max(seq, overlap)

    conn = _conn()
    rows = conn.execute(
        """SELECT id, title, stability_score
           FROM events_v2 WHERE topic_id = ? AND status != 'archived'
           ORDER BY stability_score DESC""",
        (topic_id,),
    ).fetchall()
    events = [dict(r) for r in rows]

    merged: set[str] = set()
    merge_count = 0

    for i, ev_a in enumerate(events):
        if ev_a["id"] in merged:
            continue
        for ev_b in events[i + 1:]:
            if ev_b["id"] in merged:
                continue
            if _sim(ev_a["title"], ev_b["title"]) >= similarity_threshold:
                # Keep ev_a (higher stability_score), absorb ev_b into it
                conn.execute(
                    "UPDATE articles SET event_id = ? WHERE event_id = ?",
                    (ev_a["id"], ev_b["id"]),
                )
                conn.execute("DELETE FROM events_v2 WHERE id = ?", (ev_b["id"],))
                merged.add(ev_b["id"])
                merge_count += 1

    conn.commit()
    conn.close()
    return merge_count


def toggle_event_kept(event_id: str, is_kept: int):
    """Toggle is_kept on the canonical article of this event cluster."""
    conn = _conn()
    conn.execute(
        "UPDATE articles SET is_kept = ? WHERE event_id = ? AND is_canonical = 1",
        (is_kept, event_id),
    )
    conn.commit()
    conn.close()


# ── Legacy helpers (kept for backward compatibility) ───────────────────────────


def get_events_grouped(topic_id=None, limit=30, offset=0, sort="relevance", status="active"):
    """Deprecated: use get_event_clusters(). Returns canonical articles as event proxies."""
    return get_event_clusters(topic_id=topic_id, limit=limit, offset=offset, sort=sort, status=status)


def get_event_alternatives(event_id: str):
    """Return non-canonical articles sharing the same event_id."""
    conn = _conn()
    rows = conn.execute(
        "SELECT * FROM articles WHERE event_id = ? AND is_canonical = 0 ORDER BY source_score DESC",
        (event_id,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_topics_overview(hours=24, archived_only: bool = False):
    """Return stats for dashboard cards (active topics, or archived-only when archived_only=True)."""
    conn = _conn()
    if archived_only:
        topics = conn.execute(
            """SELECT * FROM topics
               WHERE is_active = 1 AND archived_at IS NOT NULL
               ORDER BY archived_at DESC"""
        ).fetchall()
    else:
        topics = conn.execute(
            """SELECT * FROM topics
               WHERE is_active = 1 AND archived_at IS NULL
               ORDER BY created_at"""
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
              AND COALESCE(status, 'active') = 'active'
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
              AND COALESCE(status, 'active') = 'active'
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
              AND COALESCE(status, 'active') = 'active'
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
                  AND COALESCE(status, 'active') = 'active'
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
    base_where = "WHERE COALESCE(status, 'active') = 'active'"
    params: list = []

    if topic_id is not None:
        base_where += " AND topic_id = ?"
        params.append(topic_id)

    current_params = params + [f"-{window_hours} hours"]
    prev_params = params + [f"-{window_hours * 2} hours", f"-{window_hours} hours"]

    analysis_ts = _analysis_ts_expr()
    current_count = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where} AND {analysis_ts} >= datetime('now', ?)",
        current_params,
    ).fetchone()[0]

    previous_count = conn.execute(
        f"SELECT COUNT(*) FROM articles {base_where} AND {analysis_ts} >= datetime('now', ?) AND {analysis_ts} < datetime('now', ?)",
        prev_params,
    ).fetchone()[0]

    trend_delta = current_count - previous_count

    sentiment_rows = conn.execute(
        f"SELECT sentiment, COUNT(*) as cnt FROM articles {base_where} AND {analysis_ts} >= datetime('now', ?) GROUP BY sentiment",
        current_params,
    ).fetchall()
    sentiment_dist = {r["sentiment"]: r["cnt"] for r in sentiment_rows}

    tag_rows = conn.execute(
        f"SELECT tags FROM articles {base_where} AND {analysis_ts} >= datetime('now', ?)",
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

    analysis_ts = _analysis_ts_expr()
    # Daily article count + sentiment breakdown
    daily_rows = conn.execute(
        f"""SELECT date({analysis_ts}) as day,
                  COUNT(*) as total,
                  SUM(CASE WHEN sentiment='positive' THEN 1 ELSE 0 END) as pos,
                  SUM(CASE WHEN sentiment='neutral' THEN 1 ELSE 0 END) as neu,
                  SUM(CASE WHEN sentiment='negative' THEN 1 ELSE 0 END) as neg,
                  AVG(importance) as avg_importance,
                  AVG(topic_relevance) as avg_relevance
           FROM articles
           WHERE topic_id = ? AND COALESCE(status, 'active') = 'active' AND {analysis_ts} >= datetime('now', ?)
           GROUP BY date({analysis_ts})
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
        f"SELECT key_entities FROM articles WHERE topic_id = ? AND COALESCE(status, 'active') = 'active' AND {analysis_ts} >= datetime('now', ?)",
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
        f"SELECT AVG(topic_relevance) as avg_rel FROM articles WHERE topic_id = ? AND COALESCE(status, 'active') = 'active' AND {analysis_ts} >= datetime('now', ?)",
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


# ── Claims CRUD ────────────────────────────────────────────────────────────────

def update_claim_status(claim_id: str, status: str) -> bool:
    """Update the status of a claim. Returns True if a row was updated."""
    from datetime import datetime, timezone
    conn = _conn()
    cur = conn.execute(
        "UPDATE claims SET status = ?, updated_at = ? WHERE id = ?",
        (status, datetime.now(timezone.utc).isoformat(), claim_id),
    )
    conn.commit()
    updated = cur.rowcount > 0
    conn.close()
    return updated


def delete_claim(claim_id: str) -> bool:
    """Permanently delete a claim by ID. Returns True if a row was deleted."""
    conn = _conn()
    cur = conn.execute("DELETE FROM claims WHERE id = ?", (claim_id,))
    conn.commit()
    deleted = cur.rowcount > 0
    conn.close()
    return deleted
