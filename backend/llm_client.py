import re

from config import settings

_client = None

_THINK_RE = re.compile(r"<think>[\s\S]*?</think>\s*", re.DOTALL)


def _get_client():
    global _client
    if _client is not None:
        return _client

    provider = settings.llm_provider

    if provider in ("openai", "lmstudio", "dashscope"):
        from openai import OpenAI

        if provider == "openai":
            _client = OpenAI(api_key=settings.openai_api_key)
        elif provider == "lmstudio":
            _client = OpenAI(
                base_url=settings.lmstudio_base_url, api_key="lm-studio"
            )
        else:  # dashscope
            _client = OpenAI(
                base_url=settings.dashscope_base_url,
                api_key=settings.dashscope_api_key,
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
) -> str:
    """Call the LLM and return the response text.

    Pass response_format={"type": "json_object"} to enable JSON mode on
    OpenAI-compatible providers.  Anthropic silently ignores this flag.
    """
    client = _get_client()
    provider = settings.llm_provider

    if provider in ("openai", "lmstudio", "dashscope"):
        kwargs: dict = {"model": _model(), "messages": messages, "temperature": temperature}
        if response_format is not None:
            kwargs["response_format"] = response_format
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
            max_tokens=2048,
            system=system_msg,
            messages=filtered,
            temperature=temperature,
        )
        return _strip_thinking(resp.content[0].text)

    return ""


def llm_chat_stream(messages: list[dict], temperature: float = 0.5):
    """Yields text chunks, filtering out <think>…</think> blocks."""
    client = _get_client()
    provider = settings.llm_provider

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

    if provider in ("openai", "lmstudio", "dashscope"):
        stream = client.chat.completions.create(
            model=_model(), messages=messages, temperature=temperature, stream=True
        )

        def _raw():
            for chunk in stream:
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
            max_tokens=2048,
            system=system_msg,
            messages=filtered,
            temperature=temperature,
        ) as stream:
            yield from _filter_thinking(stream.text_stream)
