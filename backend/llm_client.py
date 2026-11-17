import re
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from config import settings

_client = None


def _reserve_request():
    """Persistent, atomic daily ceiling shared by manual and scheduled calls."""
    limit = settings.llm_daily_request_limit
    if not limit:
        return
    path = Path(settings.database_path).with_name("ai-usage.sqlite3")
    path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(path, timeout=15) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS usage (day TEXT PRIMARY KEY, requests INTEGER NOT NULL)")
        conn.execute("BEGIN IMMEDIATE")
        day = datetime.now(timezone.utc).date().isoformat()
        row = conn.execute("SELECT requests FROM usage WHERE day = ?", (day,)).fetchone()
        if row and row[0] >= limit:
            raise RuntimeError("Daily AI request limit reached. Try again tomorrow or adjust the configured limit.")
        conn.execute("INSERT INTO usage VALUES (?, 1) ON CONFLICT(day) DO UPDATE SET requests = requests + 1", (day,))


def _request_options(timeout):
    options = {"timeout": timeout or settings.llm_timeout_seconds,
               "max_tokens": settings.llm_max_tokens}
    if settings.llm_provider == "dashscope":
        # Hybrid Qwen models otherwise spend output tokens on hidden reasoning.
        options["extra_body"] = {"enable_thinking": False}
    return options

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>\s*", re.DOTALL)
ENGLISH_OUTPUT_POLICY = (
    "Write all generated prose, summaries, labels, tags, and analytical text in English, "
    "regardless of the language of the user or source material. Preserve required JSON "
    "keys, enum values, identifiers, URLs, and verbatim source quotations."
)


def _english_messages(messages: list[dict]) -> list[dict]:
    """Apply the product language without changing the caller's conversation."""
    copied = [dict(message) for message in messages]
    systems = [message["content"] for message in copied if message["role"] == "system"]
    system = "\n\n".join([*systems, ENGLISH_OUTPUT_POLICY])
    return [{"role": "system", "content": system}, *[
        message for message in copied if message["role"] != "system"
    ]]


def configuration_issue():
    provider = settings.llm_provider
    required = {
        "openai": (settings.openai_api_key, settings.openai_model),
        "anthropic": (settings.anthropic_api_key, settings.anthropic_model),
        "dashscope": (settings.dashscope_api_key, settings.dashscope_model, settings.dashscope_base_url),
        "openai_compat": (settings.openai_compat_base_url, settings.openai_compat_model),
        "lmstudio": (settings.lmstudio_base_url, settings.lmstudio_model),
    }
    if provider not in required or not all(str(value or "").strip() for value in required[provider]):
        return "AI is not fully configured. Configure a model provider before generating content or chatting."
    return None


def _get_client():
    global _client
    if _client is not None:
        return _client
    issue = configuration_issue()
    if issue:
        raise ValueError(issue)

    provider = settings.llm_provider

    if provider in ("openai", "lmstudio", "openai_compat", "dashscope"):
        from openai import OpenAI

        if provider == "openai":
            _client = OpenAI(api_key=settings.openai_api_key, timeout=settings.llm_timeout_seconds, max_retries=1)
        elif provider == "lmstudio":
            _client = OpenAI(
                base_url=settings.lmstudio_base_url.rstrip("/"),
                api_key=settings.lmstudio_api_key or "lm-studio",
            )
        elif provider == "openai_compat":
            key = (settings.openai_compat_api_key or "").strip() or "lm-studio"
            _client = OpenAI(
                base_url=settings.openai_compat_base_url.rstrip("/"),
                api_key=key,
            )
        else:  # dashscope
            _client = OpenAI(
                base_url=settings.dashscope_base_url,
                api_key=settings.dashscope_api_key,
                timeout=settings.llm_timeout_seconds, max_retries=0,
            )
    elif provider == "anthropic":
        from anthropic import Anthropic

        _client = Anthropic(api_key=settings.anthropic_api_key)

    return _client


def _model():
    p = settings.llm_provider
    if p == "openai":
        return settings.openai_model
    if p == "anthropic":
        return settings.anthropic_model
    if p == "lmstudio":
        return settings.lmstudio_model
    if p == "openai_compat":
        return settings.openai_compat_model
    if p == "dashscope":
        return settings.dashscope_model
    return "qwen-plus"


def _strip_thinking(text: str) -> str:
    """Remove <think>…</think> blocks emitted by reasoning models."""
    return _THINK_RE.sub("", text).strip()


def llm_chat(
    messages: list[dict],
    temperature: float = 0.3,
    response_format: dict | None = None,
    timeout: float | None = None,
) -> str:
    """Call the LLM and return the response text.

    Pass response_format={"type": "json_object"} to enable JSON mode on
    OpenAI-compatible providers.  Anthropic silently ignores this flag.
    """
    client = _get_client()
    _reserve_request()
    provider = settings.llm_provider
    messages = _english_messages(messages)

    if provider in ("openai", "lmstudio", "openai_compat", "dashscope"):
        kwargs: dict = {"model": _model(), "messages": messages, "temperature": temperature}
        if response_format is not None:
            kwargs["response_format"] = response_format
        kwargs.update(_request_options(timeout))
        resp = client.chat.completions.create(**kwargs)
        return _strip_thinking(resp.choices[0].message.content or "")

    if provider == "anthropic":
        system_msg = ""
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                filtered.append(m)
        resp = client.messages.create(
            model=_model(),
            max_tokens=4096,
            system=system_msg,
            messages=filtered,
            temperature=temperature,
        )
        return _strip_thinking(resp.content[0].text)

    return ""


def llm_chat_stream(
    messages: list[dict],
    temperature: float = 0.5,
    timeout: float | None = None,
):
    """Yields text chunks, filtering out <think>…</think> blocks."""
    client = _get_client()
    _reserve_request()
    provider = settings.llm_provider
    messages = _english_messages(messages)

    def _filter_thinking(raw_stream):
        """Buffer while inside <think> tags, yield everything after."""
        inside_think = False
        buf = ""
        for tok in raw_stream:
            buf += tok
            if not inside_think:
                if "<think>" in buf:
                    inside_think = True
                    before = buf[: buf.index("<think>")]
                    if before:
                        yield before
                    buf = buf[buf.index("<think>"):]
                else:
                    yield buf
                    buf = ""
            if inside_think and "</think>" in buf:
                after = buf[buf.index("</think>") + len("</think>"):]
                inside_think = False
                buf = ""
                stripped = after.lstrip()
                if stripped:
                    yield stripped
        if buf and not inside_think:
            yield buf

    if provider in ("openai", "lmstudio", "openai_compat", "dashscope"):
        kwargs: dict = {
            "model": _model(),
            "messages": messages,
            "temperature": temperature,
            "stream": True,
        }
        kwargs.update(_request_options(timeout))
        stream = client.chat.completions.create(**kwargs)

        def _raw():
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta

        yield from _filter_thinking(_raw())
        return

    if provider == "anthropic":
        system_msg = ""
        filtered = []
        for m in messages:
            if m["role"] == "system":
                system_msg = m["content"]
            else:
                filtered.append(m)
        with client.messages.stream(
            model=_model(),
            max_tokens=4096,
            system=system_msg,
            messages=filtered,
            temperature=temperature,
        ) as stream:
            yield from _filter_thinking(stream.text_stream)
