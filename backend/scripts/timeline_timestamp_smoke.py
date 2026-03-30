import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

ROOT = os.path.dirname(os.path.dirname(__file__))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from database import (
    create_topic,
    get_insight_summary,
    get_topic_insights,
    get_trending_data,
    init_db,
    insert_article,
)


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _article(article_id: str, topic_id: int, url: str, published_at: str) -> dict:
    return {
        "id": article_id,
        "title": f"Article {article_id}",
        "summary": "Smoke test article",
        "content": "Smoke test content",
        "source": "smoke",
        "url": url,
        "tags": "[]",
        "sentiment": "neutral",
        "importance": 5,
        "source_type": "search",
        "topic_id": topic_id,
        "published_at": published_at,
        "event_id": "",
        "is_canonical": 1,
        "event_size": 1,
        "source_score": 0.1,
        "source_breakdown": "{}",
        "topic_relevance": 0.5,
        "key_entities": "[]",
        "topic_analysis": "",
    }


def main() -> None:
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "smoke.db")
        init_db(db_path)
        topic_id = create_topic("timeline-smoke", "#6366f1")

        now = datetime.now(timezone.utc)
        very_old = now - timedelta(days=10)

        # A: normal fresh item (should be counted)
        insert_article(
            _article(
                "smoke-a",
                topic_id,
                "https://example.com/smoke-a",
                _iso(now - timedelta(minutes=20)),
            )
        )

        # B: late-arriving old news (published old, created now) — should NOT be counted.
        insert_article(
            _article(
                "smoke-b",
                topic_id,
                "https://example.com/smoke-b",
                _iso(very_old),
            )
        )

        # C: backfilled record (published recent, created old) — should be counted.
        insert_article(
            _article(
                "smoke-c",
                topic_id,
                "https://example.com/smoke-c",
                _iso(now - timedelta(minutes=45)),
            )
        )

        import sqlite3

        conn = sqlite3.connect(db_path)
        conn.execute(
            "UPDATE articles SET created_at = ? WHERE id = ?",
            (_iso(now), "smoke-b"),
        )
        conn.execute(
            "UPDATE articles SET created_at = ? WHERE id = ?",
            (_iso(very_old), "smoke-c"),
        )
        conn.commit()
        conn.close()

        summary = get_insight_summary(topic_id, 24)
        insight = get_topic_insights(topic_id, 24)
        trending = get_trending_data(topic_id, 1)

        assert summary["total_articles"] == 2, summary
        assert insight["article_count"] == 2, insight
        assert sum(day["total"] for day in trending["daily"]) == 2, trending

        print(
            {
                "status": "ok",
                "topic_id": topic_id,
                "summary_total": summary["total_articles"],
                "insight_count": insight["article_count"],
                "trending_total": sum(day["total"] for day in trending["daily"]),
            }
        )


if __name__ == "__main__":
    main()
