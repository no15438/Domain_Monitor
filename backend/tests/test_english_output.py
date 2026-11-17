"""Verify English requests at the provider boundary without external calls."""
from copy import deepcopy
from types import SimpleNamespace as NS

import pytest
import llm_client


@pytest.mark.parametrize("provider", ["openai_compat", "anthropic"])
@pytest.mark.parametrize("streaming", [False, True])
def test_language_policy_reaches_provider_without_mutating_history(monkeypatch, provider, streaming):
    received = []
    def create(**kwargs):
        received.append(kwargs)
        if provider == "anthropic":
            return NS(content=[NS(text="English response")])
        if streaming:
            return iter([NS(choices=[NS(delta=NS(content="English response"))])])
        return NS(choices=[NS(message=NS(content="English response"))])

    class Stream:
        text_stream = ["English response"]
        def __enter__(self): return self
        def __exit__(self, *args): pass

    def stream(**kwargs):
        received.append(kwargs)
        return Stream()

    fake = NS(chat=NS(completions=NS(create=create)), messages=NS(create=create, stream=stream))
    monkeypatch.setattr(llm_client, "_get_client", lambda: fake)
    monkeypatch.setattr(llm_client.settings, "llm_provider", provider)
    messages = [{"role": "system", "content": "Use the evidence; return JSON."},
                {"role": "system", "content": "Preserve citations."},
                {"role": "user", "content": "请分析 E5: https://example.invalid/source"}]
    original = deepcopy(messages)
    result = "".join(llm_client.llm_chat_stream(messages)) if streaming else llm_client.llm_chat(messages)
    assert result == "English response"
    assert messages == original
    request = received[0]
    system = request["system"] if provider == "anthropic" else request["messages"][0]["content"]
    assert llm_client.ENGLISH_OUTPUT_POLICY in system
    assert "Use the evidence; return JSON." in system
    assert "Preserve citations." in system
    assert request["messages"][-1] == original[-1]


def test_render_hostname_is_allowed_without_widening_other_hosts(monkeypatch):
    from config import Settings
    monkeypatch.setenv("RENDER_EXTERNAL_HOSTNAME", "domain-monitor-uf81.onrender.com")
    monkeypatch.delenv("EVENT_MEMORY_HOSTS", raising=False)
    config = Settings(_env_file=None)
    assert "domain-monitor-uf81.onrender.com" in config.event_memory_hosts.split(",")
    assert "*" not in config.event_memory_hosts
    explicit = Settings(_env_file=None, event_memory_hosts="localhost")
    assert explicit.event_memory_hosts == "localhost"
