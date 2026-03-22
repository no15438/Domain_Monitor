import asyncio

sse_clients: list[asyncio.Queue] = []
_loop: asyncio.AbstractEventLoop | None = None


def set_event_loop(loop: asyncio.AbstractEventLoop):
    global _loop
    _loop = loop


def notify_clients(articles: list[dict]):
    """Thread-safe: push new articles to all connected SSE clients."""
    if _loop and sse_clients:
        asyncio.run_coroutine_threadsafe(_broadcast(articles), _loop)


async def _broadcast(articles: list[dict]):
    for queue in list(sse_clients):
        try:
            await queue.put(articles)
        except Exception:
            pass
