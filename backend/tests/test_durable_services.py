from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace as NS
import sqlite3
import pytest
import llm_client
import pipeline
from collectors import feed_reader


@pytest.mark.parametrize("streaming", [False, True])
def test_dashscope_bounded_english_requests(monkeypatch, streaming):
    calls = []
    def create(**kwargs):
        calls.append(kwargs)
        if streaming:
            return iter([NS(choices=[]), NS(choices=[NS(delta=NS(content="Ready"))])])
        return NS(choices=[NS(message=NS(content="Ready"))])
    monkeypatch.setattr(llm_client, "_get_client", lambda: NS(chat=NS(completions=NS(create=create))))
    monkeypatch.setattr(llm_client.settings, "llm_provider", "dashscope")
    monkeypatch.setattr(llm_client.settings, "llm_daily_request_limit", 0)
    f = llm_client.llm_chat_stream if streaming else llm_client.llm_chat
    assert "".join(f([{"role": "user", "content": "Hello"}])) == "Ready"
    assert calls[0]["extra_body"] == {"enable_thinking": False}
    assert calls[0]["timeout"] == 90
    assert calls[0]["max_tokens"] == 4096
    assert llm_client.ENGLISH_OUTPUT_POLICY in calls[0]["messages"][0]["content"]


def test_daily_budget_is_atomic_and_persistent(monkeypatch, tmp_path):
    monkeypatch.setattr(llm_client.settings, "database_path", str(tmp_path / "monitor.db"))
    monkeypatch.setattr(llm_client.settings, "llm_daily_request_limit", 3)
    def reserve(_):
        try:
            llm_client._reserve_request()
            return True
        except RuntimeError:
            return False
    with ThreadPoolExecutor(8) as pool:
        assert sum(pool.map(reserve, range(12))) == 3
    with sqlite3.connect(tmp_path / "ai-usage.sqlite3") as conn:
        assert conn.execute("SELECT requests FROM usage").fetchone()[0] == 3
    with pytest.raises(RuntimeError, match="Daily AI request limit"):
        llm_client._reserve_request()


def test_news_uses_configured_sources_and_honors_limits(monkeypatch):
    settings = pipeline.settings
    for field, value in [("tavily_api_key", "test"), ("newsapi_key", None),
                         ("event_registry_api_key", None), ("max_search_terms", 1),
                         ("max_results_per_keyword", 2)]:
        monkeypatch.setattr(settings, field, value)
    calls = []
    def collect(keyword, max_results):
        calls.append((keyword, max_results))
        return [{"url": "https://example.invalid/news"}]
    monkeypatch.setattr(pipeline.googlenews_collector, "collect", collect)
    monkeypatch.setattr(pipeline.tavily_collector, "collect", collect)
    results = pipeline._collect_for_keywords(["AI", "AI", "other"], 10)
    assert calls == [("AI", 2), ("AI", 2)]
    assert {r["_source_type"] for r in results} == {"googlenews", "tavily"}
    assert pipeline._collect_for_keywords([], 10) == []


def test_feed_timeout_and_size_limit(monkeypatch):
    class Response:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == feed_reader.MAX_FEED_BYTES + 1
            return b"x" * size
    def open_feed(request, timeout):
        assert timeout == 20
        return Response()
    monkeypatch.setattr(feed_reader, "urlopen", open_feed)
    with pytest.raises(ValueError, match="size limit"):
        feed_reader.read_feed("https://example.invalid/feed")
    with pytest.raises(ValueError, match="HTTP"):
        feed_reader.read_feed("file:///tmp/private")


def test_storage_fails_closed_without_mount_or_with_escaping_paths(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config.settings, "persistent_data_root", str(tmp_path))
    monkeypatch.setattr(config.os.path, "ismount", lambda path: False)
    with pytest.raises(RuntimeError, match="not mounted"):
        config.validate_storage()
    monkeypatch.setattr(config.os.path, "ismount", lambda path: True)
    monkeypatch.setattr(config.settings, "database_path", "/tmp/outside.db")
    with pytest.raises(RuntimeError, match="inside"):
        config.validate_storage()
    for field in ("database_path", "chroma_persist_dir", "event_memory_database_path"):
        monkeypatch.setattr(config.settings, field, str(tmp_path / field))
    config.validate_storage()


def test_news_budget_preserves_rss_and_is_shared_with_chat(monkeypatch, tmp_path):
    import search_budget
    import search_client
    from collectors import tavily_collector
    monkeypatch.setattr(search_budget.settings, "database_path", str(tmp_path / "monitor.db"))
    monkeypatch.setattr(search_budget.settings, "tavily_api_key", "test")
    monkeypatch.setattr(search_budget.settings, "tavily_daily_request_limit", 1)
    assert search_budget.reserve_search()
    assert not search_budget.reserve_search()
    monkeypatch.setattr(search_client, "_get_client", lambda: pytest.fail("No paid search after ceiling"))
    monkeypatch.setattr(tavily_collector, "_get_client", lambda: pytest.fail("No paid search after ceiling"))
    assert search_client.search("AI") == []
    assert tavily_collector.collect("AI") == []


def test_news_stream_flushes_immediately_and_cleans_up():
    import asyncio
    import main
    async def exercise():
        before = len(main.sse_clients)
        response = await main.stream(NS())
        assert response.headers["x-accel-buffering"] == "no"
        assert await asyncio.wait_for(anext(response.body_iterator), timeout=0.25) == ": connected\n\n"
        assert len(main.sse_clients) == before + 1
        await response.body_iterator.aclose()
        assert len(main.sse_clients) == before
    asyncio.run(exercise())
