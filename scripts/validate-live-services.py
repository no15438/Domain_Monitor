#!/usr/bin/env python3
"""Bounded acceptance run against a configured deployment, using public news only."""
import argparse
import json
import re
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("--base", required=True)
parser.add_argument("--real-external", action="store_true", help="Authorize real configured AI/news calls")
parser.add_argument("--output", required=True)
parser.add_argument("--reuse-data", action="store_true", help="Reuse collected news when resuming acceptance")
args = parser.parse_args()
if not args.real_external:
    parser.error("This run needs --real-external and uses the deployment's configured limits.")
base = args.base.rstrip("/")
checks = []


def request(path, body=None, method=None):
    req = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None,
                                 method=method, headers={"Content-Type": "application/json", "Origin": base})
    with urllib.request.urlopen(req, timeout=40) as response:
        return json.load(response)


def check(name, condition):
    if not condition:
        raise AssertionError(name)
    checks.append(name)
    print("PASS " + name, flush=True)


def wait(path, terminal=None):
    deadline = time.monotonic() + 240
    while time.monotonic() < deadline:
        state = request(path)
        if state.get("error"):
            raise AssertionError(state["error"])
        done = state.get("status") in terminal if terminal else not state.get("running", state.get("generating", False))
        if done:
            return state
        time.sleep(2)
    raise TimeoutError(path)


runtime = request("/api/runtime")
check("Alibaba deployment reports configured AI and enabled collection/scheduling", all(runtime[k] for k in
      ("model_configured", "external_calls_enabled", "scheduler_enabled", "event_memory_enabled")))
topics = request("/api/topics")["topics"]
topic = next((t for t in topics if t["name"] == "AI industry monitor"), None)
tid = topic["id"] if topic else request("/api/topics", {"name": "AI industry monitor"})["id"]
if not args.reuse_data:
    request(f"/api/topics/{tid}/generate-research-plan", {"prompt": "Monitor public English news about artificial intelligence, Alibaba Qwen, AI chips and infrastructure. Use only two broad search keywords and at most two entities."})
    wait(f"/api/topics/{tid}/generate-research-plan/status")
topic = next(t for t in request("/api/topics")["topics"] if t["id"] == tid)
check("Real Qwen research plan saved in English", bool(topic.get("research_brief")) and not re.search(r"[\u4e00-\u9fff]", topic["research_brief"]))
if not args.reuse_data:
    request("/api/keywords", {"keyword": "artificial intelligence", "topic_id": tid})
    request(f"/api/fetch-now?topic_id={tid}", {})
    wait(f"/api/fetch-now/status?topic_id={tid}")
articles = request(f"/api/articles?topic_id={tid}")["articles"]
check("Real news collected, enriched and persisted", len(articles) > 0)
canonicals = [a for a in articles if a.get("is_canonical")]
check("News keeps source URLs and English AI analysis", bool(canonicals) and all(a.get("url", "").startswith(("http://", "https://")) and a.get("summary") and not re.search(r"[\u4e00-\u9fff]", a["summary"]) for a in canonicals))
events = request(f"/api/topics/{tid}/events/active")["events"]
check("News produced persisted event cards", bool(events))
check("News produced source evidence", bool(request(f"/api/topics/{tid}/evidence")["evidence"]))
check("News produced analytical claims", bool(request(f"/api/topics/{tid}/claims")["claims"]))
request(f"/api/topics/{tid}/ai-summary/generate?hours=168", {})
wait(f"/api/topics/{tid}/ai-summary/status")
summary = request(f"/api/topics/{tid}/ai-summary")
check("Real English AI summary persisted", bool(summary["content"]) and not re.search(r"[\u4e00-\u9fff]", summary["content"]))
chat = request("/api/chat/tasks", {"topic_id": tid, "message": "Summarize the two most important findings already in this topic, citing the stored sources. Do not perform a web search. Answer in three short English sentences."})
wait(f"/api/chat/tasks/{chat['task_id']}/status", {"done", "error"})
conversation = request(f"/api/chat/conversations/{chat['conversation_id']}")
answers = [m for m in conversation["messages"] if m["role"] == "assistant"]
check("Real chat completes and persists English answer", bool(answers and answers[-1].get("content")) and not re.search(r"[\u4e00-\u9fff]", answers[-1]["content"]))
result = {"checked_at": datetime.now(timezone.utc).isoformat(), "base": base, "checks": checks,
          "count": len(checks), "topic_id": tid, "article_count": len(articles),
          "event_count": len(events), "conversation_id": chat["conversation_id"], "external_calls": "Real Alibaba AI and configured public-news services"}
Path(args.output).write_text(json.dumps(result, indent=2) + "\n")
print(json.dumps(result, indent=2))
