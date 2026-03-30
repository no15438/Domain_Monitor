import logging
from apscheduler.schedulers.background import BackgroundScheduler
from config import settings

log = logging.getLogger("scheduler")
_scheduler: BackgroundScheduler | None = None

SUMMARY_REFRESH_MINUTES = 60
METABOLISM_REFRESH_MINUTES = 30


def start_scheduler():
    global _scheduler
    _scheduler = BackgroundScheduler()
    _scheduler.add_job(
        _fetch_job,
        "interval",
        minutes=settings.fetch_interval_minutes,
        id="fetch_job",
        max_instances=1,
    )
    _scheduler.add_job(
        _metabolism_job,
        "interval",
        minutes=METABOLISM_REFRESH_MINUTES,
        id="metabolism_job",
        max_instances=1,
    )
    _scheduler.add_job(
        _summary_job,
        "interval",
        minutes=SUMMARY_REFRESH_MINUTES,
        id="summary_job",
        max_instances=1,
    )
    _scheduler.start()
    log.info(
        "started — fetch every %d min, metabolism every %d min, summaries every %d min",
        settings.fetch_interval_minutes, METABOLISM_REFRESH_MINUTES, SUMMARY_REFRESH_MINUTES,
    )


def stop_scheduler():
    if _scheduler:
        _scheduler.shutdown(wait=False)


def _fetch_job():
    """Scheduled fetch — shares the same in-memory mutex as manual fetch-now.
    Lazy imports avoid circular dependency with main.py."""
    from pipeline import run_pipeline_once
    from sse_manager import notify_clients
    from database import get_topics
    import main as _main  # lazy — avoids circular import at module load time

    topics = get_topics()
    for t in topics:
        tid = t["id"]
        key = f"fetch-{tid}"
        if not _main._bg_try_start(key):
            log.info("topic %d: skipping — fetch already running", tid)
            continue

        try:
            log.info("topic %d: running fetch …", tid)
            new_articles = run_pipeline_once(tid)
            if new_articles:
                notify_clients(new_articles)
            log.info("topic %d: done — %d new articles", tid, len(new_articles))
            _main._bg_finish(key, result=f"{len(new_articles)} new articles")
        except Exception as e:
            log.error("topic %d: error: %s", tid, e)
            _main._bg_finish(key, error=str(e))


def _summary_job():
    from topic_summary import refresh_all_summaries
    import main as _main  # lazy — avoids circular import at module load time

    key = "summary-all"
    if not _main._bg_try_start(key):
        log.info("summary job skipping — already running")
        return
    log.info("refreshing AI summaries …")
    try:
        refresh_all_summaries(hours=24)
        log.info("summaries refreshed")
        _main._bg_finish(key, result="summaries refreshed")
    except Exception as e:
        log.error("summary error: %s", e)
        _main._bg_finish(key, error=str(e))


def _metabolism_job():
    from claim_lifecycle import refresh_recent_topic_lifecycles
    from database import get_topics
    import main as _main

    key = "metabolism-all"
    if not _main._bg_try_start(key):
        log.info("metabolism job skipping — already running")
        return

    try:
        topics = [t["id"] for t in get_topics() if t.get("is_active", 1)]
        refresh_recent_topic_lifecycles(topics, source="scheduler")
        log.info("knowledge metabolism refreshed for %d topics", len(topics))
        _main._bg_finish(key, result=f"metabolism refreshed for {len(topics)} topics")
    except Exception as e:
        log.error("metabolism error: %s", e)
        _main._bg_finish(key, error=str(e))
