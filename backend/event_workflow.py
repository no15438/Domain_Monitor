"""Source-preserving ModelRelease ingestion and review over the event memory store.

The workflow owns extraction candidates, never an alternative factual projection.
Its durable queue and source revisions share the event database and its backups.
"""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from functools import wraps
from functools import lru_cache
from pathlib import Path

from eventkb.store import Store, encoded, timestamp, utcnow


MODEL_VERSION = 1
MODEL = {"kind": "ModelRelease", "version": MODEL_VERSION,
         "identity_fields": ["developer", "model", "version"],
         "statuses": ["announced", "available", "withdrawn"],
         "review_required": ["transition", "correction", "conflict", "unknown_effective_time"]}
ALIASES = {"alibaba group": "Alibaba", "alibaba cloud": "Alibaba", "alibaba": "Alibaba",
           "qwen team": "Alibaba", "google deepmind": "Google", "google": "Google",
           "meta platforms": "Meta", "meta": "Meta", "openai": "OpenAI",
           "anthropic": "Anthropic", "deepseek": "DeepSeek", "mistral ai": "Mistral"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS workflow_models (
 kind TEXT NOT NULL, version INTEGER NOT NULL, definition_json TEXT NOT NULL,
 created_at TEXT NOT NULL, PRIMARY KEY(kind, version)
);
CREATE TABLE IF NOT EXISTS workflow_entities (
 id TEXT PRIMARY KEY, canonical_name TEXT NOT NULL, entity_type TEXT NOT NULL,
 aliases_json TEXT NOT NULL, recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_event_entities (
 event_id TEXT NOT NULL REFERENCES events(id), entity_id TEXT NOT NULL REFERENCES workflow_entities(id),
 role TEXT NOT NULL, recorded_at TEXT NOT NULL, PRIMARY KEY(event_id,entity_id,role)
);
CREATE TABLE IF NOT EXISTS workflow_documents (
 id TEXT PRIMARY KEY, document_id TEXT NOT NULL, original_url TEXT NOT NULL,
 normalized_url TEXT NOT NULL, title TEXT NOT NULL, body TEXT NOT NULL,
 content_sha256 TEXT NOT NULL, publisher TEXT NOT NULL, source_type TEXT NOT NULL,
 published_at TEXT NOT NULL, captured_at TEXT NOT NULL, content_status TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_topic_documents (
 topic_id INTEGER NOT NULL, revision_id TEXT NOT NULL REFERENCES workflow_documents(id),
 captured_at TEXT NOT NULL, PRIMARY KEY(topic_id, revision_id)
);
CREATE TABLE IF NOT EXISTS workflow_jobs (
 topic_id INTEGER NOT NULL, revision_id TEXT NOT NULL REFERENCES workflow_documents(id),
 state TEXT NOT NULL, attempts INTEGER NOT NULL DEFAULT 0, error TEXT NOT NULL DEFAULT '',
 updated_at TEXT NOT NULL, PRIMARY KEY(topic_id, revision_id)
);
CREATE TABLE IF NOT EXISTS workflow_candidates (
 id TEXT PRIMARY KEY, topic_id INTEGER NOT NULL, revision_id TEXT NOT NULL,
 payload_json TEXT NOT NULL, review_status TEXT NOT NULL, issues_json TEXT NOT NULL,
 event_id TEXT, expected_version TEXT NOT NULL, created_at TEXT NOT NULL,
 updated_at TEXT NOT NULL, model_version INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_reviews (
 seq INTEGER PRIMARY KEY AUTOINCREMENT, candidate_id TEXT NOT NULL,
 action TEXT NOT NULL, reason TEXT NOT NULL, payload_json TEXT NOT NULL,
 recorded_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflow_assertions (
 assertion_id TEXT PRIMARY KEY, candidate_id TEXT NOT NULL, revision_id TEXT NOT NULL,
 evidence_id TEXT NOT NULL, field TEXT NOT NULL, quote TEXT NOT NULL,
 start_offset INTEGER NOT NULL, end_offset INTEGER NOT NULL, review_status TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS workflow_candidates_topic ON workflow_candidates(topic_id, review_status);
CREATE INDEX IF NOT EXISTS workflow_jobs_pending ON workflow_jobs(topic_id, state, updated_at);
"""


def _digest(*parts):
    return hashlib.sha256("\0".join(str(p) for p in parts).encode()).hexdigest()


def _normal(value):
    return re.sub(r"\s+", " ", str(value or "").strip()).casefold()


def _search_tokens(text):
    prepared = re.sub(r"(?<=[\u3400-\u9fff])(?=[A-Za-z0-9])|(?<=[A-Za-z0-9])(?=[\u3400-\u9fff])", " ", text)
    result = []
    for token in re.findall(r"[^\W_]+(?:[.\-/][^\W_]+)*", prepared.casefold()):
        joined = re.fullmatch(r"([^\W\d_]+)(v?\d+(?:\.\d+)*)", token)
        if re.fullmatch(r"v?\d+(?:\.\d+)*(?:[-/][a-z0-9]+)*", token):
            result.append(re.sub(r"^v(?=\d)", "", token))
        elif joined:
            result.extend(joined.groups())
        else:
            result.extend(part for part in re.split(r"[-/]", token) if part)
    return set(result)


def _matches_query(state, query):
    """Typed names and exact versions are conjunctive, never title OR hints."""
    stop = {"a", "an", "the", "and", "model", "models", "release", "version", "status", "模型", "发布", "版本", "状态"}
    terms = _search_tokens(query) - stop
    if not terms:
        return True
    text = encoded({"title": state["event"]["title"],
                    "fields": {key: field.get("value") for key, field in state["fields"].items()}}).casefold()
    tokens = _search_tokens(text)
    return all((term in text if re.search(r"[\u3400-\u9fff]", term) else term in tokens) for term in terms)


def _source_text(item):
    return (str(item.get("title") or "") + "\n\n" + str(item.get("content") or "")).strip()


def _publication(raw):
    """Keep unknown publication times unknown; never infer effective time here."""
    if not raw:
        return ""
    try:
        return timestamp(str(raw))
    except (ValueError, TypeError):
        try:
            parsed = parsedate_to_datetime(str(raw))
            return timestamp(parsed.isoformat()) if parsed.tzinfo else ""
        except (ValueError, TypeError, OverflowError):
            return ""


def looks_like_release(item):
    text = _source_text(item).casefold()
    return bool(re.search(r"\b(model|qwen|gpt|llama|gemini|deepseek|claude|mistral)\b", text)
                and re.search(r"\b(releas\w*|launch\w*|availab\w*|announc\w*|withdraw\w*|withdrew)\b", text))


def _transactional(fn):
    @wraps(fn)
    def run(self, *args, **kwargs):
        with self.store.atomic():
            return fn(self, *args, **kwargs)
    return run


class Workflow:
    def __init__(self, path, *, clock=utcnow):
        self.store = Store(path, clock=clock)
        with self.store.connection(write=True) as db:
            db.executescript(SCHEMA)
            db.execute("INSERT OR IGNORE INTO workflow_models VALUES(?,?,?,?)",
                       ("ModelRelease", MODEL_VERSION, encoded(MODEL), self._now()))
            for table in ("workflow_models", "workflow_entities", "workflow_event_entities", "workflow_documents", "workflow_topic_documents", "workflow_reviews", "workflow_assertions"):
                for action in ("UPDATE", "DELETE"):
                    db.execute(f"CREATE TRIGGER IF NOT EXISTS immutable_{table}_{action} BEFORE {action} ON {table} "
                               "BEGIN SELECT RAISE(ABORT, 'append-only workflow record'); END")

    def _now(self):
        return timestamp(self.store.clock())

    @staticmethod
    def topic_key(topic_id):
        if not isinstance(topic_id, int) or isinstance(topic_id, bool) or topic_id <= 0:
            raise ValueError("A positive Topic ID is required")
        return f"topic:{topic_id}"

    def capture_documents(self, topic_id, items):
        """Capture every revision before selection; annotate the caller's items."""
        self.topic_key(topic_id)
        captured = []
        now = self._now()
        with self.store.connection(write=True) as db:
            for item in items:
                original = str(item.get("_original_url") or item.get("url") or "").strip()
                if not original or not original.startswith(("http://", "https://")):
                    continue
                body = _source_text(item)
                if not body:
                    continue
                document_id = "doc_" + _digest(original)[:32]
                digest = _digest(body)
                published = str(item.get("published_date") or item.get("published_at") or "")
                publisher = str(item.get("source") or "Unknown publisher")
                revision_id = "rev_" + _digest(document_id, body, published, publisher)[:40]
                source_type = str(item.get("_source_type") or "search")
                content_status = str(item.get("content_status") or (
                    "title_only" if not item.get("content") else
                    "search_excerpt" if source_type in ("tavily", "googlenews", "search") else "feed_text"))
                db.execute("INSERT OR IGNORE INTO workflow_documents VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                           (revision_id, document_id, original, str(item.get("normalized_url") or original),
                            str(item.get("title") or ""), body, digest, publisher, source_type, published, now, content_status))
                db.execute("INSERT OR IGNORE INTO workflow_topic_documents VALUES(?,?,?)", (topic_id, revision_id, now))
                db.execute("INSERT OR IGNORE INTO workflow_jobs VALUES(?,?,'pending',0,'',?)", (topic_id, revision_id, now))
                job = db.execute("SELECT * FROM workflow_jobs WHERE topic_id=? AND revision_id=?", (topic_id, revision_id)).fetchone()
                item["_workflow_revision_id"] = revision_id
                item["_workflow_should_process"] = job["state"] in ("pending", "failed") and job["attempts"] < 3
                item["_original_url"] = original
                if looks_like_release(item):
                    candidate_id = self._candidate_id(topic_id, revision_id)
                    payload = {"developer": "", "model": "", "version": "", "status": "", "valid_from": "",
                               "quote": body[:1200], "relation": "observation", "target_id": None,
                               "title": str(item.get("title") or "Model release candidate")}
                    db.execute("INSERT OR IGNORE INTO workflow_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                               (candidate_id, topic_id, revision_id, encoded(payload), "pending",
                                encoded(["Awaiting structured extraction"]), None, "new", now, now, MODEL_VERSION))
                captured.append(item)
        return captured

    @staticmethod
    def _candidate_id(topic_id, revision_id):
        return "candidate_" + _digest(topic_id, revision_id)[:32]

    def pending_documents(self, topic_id, limit=50):
        self.topic_key(topic_id)
        with self.store.connection() as db:
            rows = db.execute("SELECT d.* FROM workflow_jobs j JOIN workflow_documents d ON d.id=j.revision_id "
                              "WHERE j.topic_id=? AND j.state IN ('pending','failed') AND j.attempts<3 "
                              "ORDER BY j.updated_at,d.id LIMIT ?", (topic_id, limit)).fetchall()
        return [{"title": r["title"], "content": r["body"].partition("\n\n")[2], "url": r["original_url"],
                 "source": r["publisher"], "published_date": r["published_at"], "_source_type": r["source_type"],
                 "content_status": r["content_status"], "_workflow_revision_id": r["id"],
                 "_workflow_should_process": True, "_original_url": r["original_url"]} for r in rows]

    def _document(self, topic_id, revision_id):
        with self.store.connection() as db:
            row = db.execute("SELECT d.* FROM workflow_documents d JOIN workflow_topic_documents t ON t.revision_id=d.id "
                             "WHERE t.topic_id=? AND d.id=?", (topic_id, revision_id)).fetchone()
        if not row:
            raise KeyError("Source revision not found in this Topic")
        return dict(row)

    def _identity(self, payload):
        developer = ALIASES.get(_normal(payload.get("developer")), str(payload.get("developer") or "").strip())
        family = str(payload.get("model") or "").strip()
        version = str(payload.get("version") or "").strip()
        version = re.sub(r"^[vV](?=\d)", "", version)
        # Do not discard version punctuation: 3.5 and 3.6 must remain different.
        key = "ModelRelease:" + ":".join(_normal(v) for v in (developer, family, version))
        return developer, family, version, key

    def _find_event(self, topic_id, payload):
        _, _, _, key = self._identity(payload)
        with self.store.connection() as db:
            row = db.execute("SELECT id FROM events WHERE topic=? AND identity_key=?", (self.topic_key(topic_id), key)).fetchone()
        return row[0] if row else None

    def _event_version(self, event_id):
        if not event_id:
            return "new"
        history = self.store.history(event_id)
        return _digest(encoded([{k: a[k] for k in ("id", "field", "value", "relation", "target_id")}
                                for a in history["assertions"]]))

    @staticmethod
    def _time_supported(value, quote):
        """An explicit timezone datetime is required; dates alone remain pending."""
        try:
            target = timestamp(value)
        except (ValueError, TypeError):
            return False
        candidates = re.findall(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})", quote)
        for raw in candidates:
            try:
                if timestamp(raw.replace(" Z", "Z")) == target:
                    return True
            except ValueError:
                continue
        return False

    @staticmethod
    def _version_supported(model, version, text):
        value = re.sub(r"^[vV](?=\d)", "", str(version or ""))
        if not value:
            return False
        # Match the whole version, including after a joined family name. A
        # request for 3.5 must never borrow evidence describing 13.5 or 3.50.
        return bool(re.search(r"(?<![\w.])v?" + re.escape(value) + r"(?![\w.])", text, re.I)
                    or re.search(re.escape(str(model or "")) + r"\s*[-_]?\s*v?" + re.escape(value) + r"(?![\w.])", text, re.I))

    def _supporting_clauses(self, payload, quote, status_pattern):
        """Bind identity, action and time locally rather than across a report."""
        clauses = re.split(r"(?<=[.!?。！？])\s+(?=[A-Z\u3400-\u9fff])|[\n;；]+", quote)
        developer, model, version = (str(payload.get(key) or "") for key in ("developer", "model", "version"))
        canonical_version = re.sub(r"^[vV](?=\d)", "", version).casefold()
        supported = []
        for clause in clauses:
            if (_normal(developer) not in _normal(clause) or _normal(model) not in _normal(clause)
                    or not self._version_supported(model, version, clause)
                    or not self._time_supported(payload.get("valid_from"), clause)
                    or not re.search(status_pattern, clause, re.I)):
                continue
            mentioned_versions = {match.casefold() for match in re.findall(
                re.escape(model) + r"\s*[-:]?\s*v?(\d+(?:\.\d+)*(?:-[A-Za-z0-9]+)?)", clause, re.I)}
            if mentioned_versions and mentioned_versions != {canonical_version}:
                continue
            explicit_times = re.findall(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?\s*(?:Z|[+-]\d{2}:?\d{2})", clause)
            try:
                observed_times = {timestamp(raw.replace(" Z", "Z")) for raw in explicit_times}
                expected_times = {timestamp(payload["valid_from"])}
                if payload.get("valid_to"):
                    expected_times.add(timestamp(payload["valid_to"]))
                if observed_times != expected_times:
                    continue
            except (TypeError, ValueError):
                continue
            supported.append(clause)
        return supported

    def _validate(self, payload, document):
        issues = []
        quote = str(payload.get("quote") or "")
        if not quote or quote not in document["body"]:
            issues.append("An exact supporting passage from the captured source is required")
        if len(quote) > 2400:
            issues.append("Use a focused supporting passage of at most 2400 characters")
        developer, model, version, _ = self._identity(payload)
        for field, value in (("developer", str(payload.get("developer") or "")), ("model", model), ("version", version)):
            if not value.strip():
                issues.append(f"Missing {field}")
            elif field == "version" and not self._version_supported(model, version, quote):
                issues.append("The supporting passage does not contain the exact version")
            elif field != "version" and _normal(value) not in _normal(quote):
                issues.append(f"The supporting passage does not contain the {field}")
        status = payload.get("status")
        if status not in MODEL["statuses"]:
            issues.append("Availability must be announced, available or withdrawn")
        status_words = {"announced": r"\b(announc\w*|unveil\w*)\b",
                        "available": r"\b(available|released|releases|launched|launches|opened)\b",
                        "withdrawn": r"\b(withdraw\w*|withdrew|retir\w*|discontinu\w*)\b"}
        if status in status_words and not re.search(status_words[status], quote, re.I):
            issues.append("The supporting passage does not state this availability")
        support = self._supporting_clauses(payload, quote, status_words.get(status, r"(?!)"))
        if not support:
            issues.append("Developer, model, exact version, availability and effective timestamp must be supported in the same unambiguous release sentence")
        uncertainty = (r"\b(not|never|no longer|not yet|no announcement|no release|unavailable|unconfirmed|rumou?r\w*|reportedly|allegedly|"
                       r"will|would|could|might|may be|plans? to|expected to|scheduled to|soon|upcoming|planned|proposed|if)\b")
        if support and all(re.search(uncertainty, clause, re.I) for clause in support):
            issues.append("The passage includes negation, uncertainty or a future condition; use direct supported wording or defer")
        if not self._time_supported(payload.get("valid_from"), quote):
            issues.append("An explicit source-supported timezone timestamp is required; publication time is not effective time")
        if payload.get("valid_to"):
            try:
                if timestamp(payload["valid_to"]) <= timestamp(payload["valid_from"]):
                    issues.append("The effective interval must be nonempty")
                if not self._time_supported(payload["valid_to"], quote):
                    issues.append("The effective end needs a source-supported timezone timestamp")
            except (TypeError, ValueError):
                issues.append("Invalid effective end")
        return issues

    def ingest_extraction(self, topic_id, item, parsed):
        """Persist an outbox candidate, then idempotently project accepted observations."""
        if not item.get("_workflow_revision_id"):
            self.capture_documents(topic_id, [item])
        revision_id = item.get("_workflow_revision_id")
        if not revision_id:
            return {"status": "skipped", "reason": "No capturable source"}
        document = self._document(topic_id, revision_id)
        candidate_id = self._candidate_id(topic_id, revision_id)
        now = self._now()
        release = parsed.get("model_release") if isinstance(parsed, dict) else None
        failed = not isinstance(parsed, dict) or bool(parsed.get("_extraction_failed"))
        with self.store.connection(write=True) as db:
            old = db.execute("SELECT * FROM workflow_candidates WHERE id=?", (candidate_id,)).fetchone()
            if old and old["review_status"] in ("accepted", "rejected"):
                return self._candidate(dict(old), document)
            db.execute("UPDATE workflow_jobs SET attempts=attempts+1,state=?,error=?,updated_at=? WHERE topic_id=? AND revision_id=?",
                       ("failed" if failed else "processed", "Structured extraction failed" if failed else "", now, topic_id, revision_id))
        if failed or not isinstance(release, dict):
            if old:
                issues = ["Structured extraction failed; source preserved for retry"] if failed else ["No supported structured release was extracted; review the source"]
                with self.store.connection(write=True) as db:
                    db.execute("UPDATE workflow_candidates SET issues_json=?,updated_at=? WHERE id=?", (encoded(issues), now, candidate_id))
                return next(c for c in self.list_candidates(topic_id, include_resolved=True) if c["id"] == candidate_id)
            return {"status": "failed" if failed else "not_applicable", "revision_id": revision_id}
        payload = {k: release.get(k) for k in ("developer", "model", "version", "status", "valid_from", "valid_to", "quote")}
        payload.update(title=release.get("title") or document["title"], relation="observation", target_id=None)
        issues = self._validate(payload, document)
        event_id = self._find_event(topic_id, payload) if not any(not payload.get(k) for k in ("developer", "model", "version")) else None
        if event_id:
            status_field = self.store.state(event_id)["fields"].get("status")
            if status_field and (status_field["status"] == "conflict" or status_field["value"] != payload.get("status")):
                issues.append("A different current availability exists; review a transition, correction or unresolved conflict")
                payload["target_id"] = status_field["assertion_ids"][0]
                payload["relation"] = "transition" if payload.get("valid_from") else "observation"
        with self.store.connection(write=True) as db:
            db.execute("INSERT INTO workflow_candidates VALUES(?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
                       "payload_json=excluded.payload_json,issues_json=excluded.issues_json,event_id=excluded.event_id,"
                       "expected_version=excluded.expected_version,updated_at=excluded.updated_at",
                       (candidate_id, topic_id, revision_id, encoded(payload), "pending", encoded(issues), event_id,
                        self._event_version(event_id), now, now, MODEL_VERSION))
        if not issues:
            with self.store.connection(write=True) as db:
                db.execute("UPDATE workflow_jobs SET state='committing' WHERE topic_id=? AND revision_id=?", (topic_id, revision_id))
            return self._commit(topic_id, candidate_id, payload, reviewed=False, reason="Source-supported machine observation")
        return next(c for c in self.list_candidates(topic_id, include_resolved=True) if c["id"] == candidate_id)

    def _candidate(self, row, document=None):
        payload = json.loads(row["payload_json"])
        document = document or self._document(row["topic_id"], row["revision_id"])
        event_id = row["event_id"] or self._find_event(row["topic_id"], payload)
        return {**payload, "id": row["id"], "topic_id": row["topic_id"], "revision_id": row["revision_id"],
                "event_id": event_id, "review_status": row["review_status"], "issues": json.loads(row["issues_json"]),
                "expected_version": self._event_version(event_id), "created_at": row["created_at"],
                "model_version": row["model_version"], "source": {**document, "url": document["original_url"], "revision": document["id"]}}

    def list_candidates(self, topic_id, include_resolved=False):
        self.topic_key(topic_id)
        with self.store.connection() as db:
            rows = db.execute("SELECT * FROM workflow_candidates WHERE topic_id=? " +
                              ("" if include_resolved else "AND review_status IN ('pending','deferred','failed') ") +
                              "ORDER BY created_at DESC,id", (topic_id,)).fetchall()
        return [self._candidate(dict(row)) for row in rows]

    @_transactional
    def review_candidate(self, topic_id, candidate_id, action, reason, **edits):
        if action not in ("accept", "reject", "defer") or not str(reason).strip():
            raise ValueError("Review action and a nonempty reason are required")
        with self.store.connection() as db:
            row = db.execute("SELECT * FROM workflow_candidates WHERE id=? AND topic_id=?", (candidate_id, topic_id)).fetchone()
        if not row:
            raise KeyError("Candidate not found in this Topic")
        row = dict(row)
        if row["review_status"] in ("accepted", "rejected"):
            raise ValueError("This candidate has already been resolved")
        payload = json.loads(row["payload_json"])
        allowed = {"developer", "model", "version", "status", "valid_from", "valid_to", "quote", "event_id", "relation", "target_id", "expected_version"}
        if set(edits) - allowed:
            raise ValueError("Unknown review fields")
        supplied_version = edits.pop("expected_version", None)
        payload.update(edits)
        event_id = payload.get("event_id") or self._find_event(topic_id, payload)
        if event_id:
            state = self.store.state(event_id)
            if state["event"]["topic"] != self.topic_key(topic_id):
                raise KeyError("Event not found in this Topic")
            if state["event"]["identity_key"] != self._identity(payload)[3]:
                raise ValueError("Selected event does not match developer, model and version")
        if action == "accept":
            if supplied_version is None or supplied_version != self._event_version(event_id):
                raise ValueError("Stale review: refresh the current event before accepting")
            return self._commit(topic_id, candidate_id, payload, reviewed=True, reason=reason)
        now = self._now()
        with self.store.connection(write=True) as db:
            status = "rejected" if action == "reject" else "deferred"
            db.execute("UPDATE workflow_candidates SET review_status=?,updated_at=? WHERE id=?", (status, now, candidate_id))
            db.execute("INSERT INTO workflow_reviews(candidate_id,action,reason,payload_json,recorded_at) VALUES(?,?,?,?,?)",
                       (candidate_id, action, reason, encoded(payload), now))
        row["review_status"] = status
        return self._candidate(row)

    @_transactional
    def _commit(self, topic_id, candidate_id, payload, *, reviewed, reason):
        with self.store.connection() as db:
            row = dict(db.execute("SELECT * FROM workflow_candidates WHERE id=? AND topic_id=?", (candidate_id, topic_id)).fetchone())
        if row["review_status"] in ("accepted", "rejected"):
            return self._candidate(row)
        document = self._document(topic_id, row["revision_id"])
        issues = self._validate(payload, document)
        if issues:
            raise ValueError("; ".join(issues))
        developer, model, version, key = self._identity(payload)
        event_id = self._find_event(topic_id, payload) or "release_" + _digest(topic_id, key)[:32]
        title = f"{developer} {model} {version} release"
        with self.store.connection() as db:
            old_event = db.execute("SELECT * FROM events WHERE id=?", (event_id,)).fetchone()
        if old_event and not reviewed:
            # Extraction and retry can be separated by another worker's commit.
            # Recheck within the writer transaction before turning an observation
            # into facts; a changed availability must still pass human review.
            status_field = self.store.state(event_id)["fields"].get("status")
            if status_field and (status_field["status"] == "conflict" or status_field["value"] != payload["status"]):
                payload = {**payload, "relation": "transition", "target_id": status_field["assertion_ids"][0]}
                issues = ["A different current availability exists; review a transition, correction or unresolved conflict"]
                now = self._now()
                with self.store.connection(write=True) as db:
                    db.execute("UPDATE workflow_candidates SET review_status='pending',payload_json=?,issues_json=?,event_id=?,"
                               "expected_version=?,updated_at=? WHERE id=?",
                               (encoded(payload), encoded(issues), event_id, self._event_version(event_id), now, candidate_id))
                    db.execute("UPDATE workflow_jobs SET state='processed',error='',updated_at=? WHERE topic_id=? AND revision_id=?",
                               (now, topic_id, document["id"]))
                    refreshed = dict(db.execute("SELECT * FROM workflow_candidates WHERE id=?", (candidate_id,)).fetchone())
                return self._candidate(refreshed, document)
        event = self.store.create_event(event_id=event_id, topic=self.topic_key(topic_id), identity_key=key,
                                       title=old_event["title"] if old_event else title, kind="ModelRelease")
        entity_id = "entity_" + _digest("Organization", _normal(developer))[:32]
        with self.store.connection(write=True) as db:
            db.execute("INSERT OR IGNORE INTO workflow_entities VALUES(?,?,?,?,?)",
                       (entity_id, developer, "Organization", encoded([k for k, name in ALIASES.items() if name == developer]), self._now()))
            db.execute("INSERT OR IGNORE INTO workflow_event_entities VALUES(?,?,?,?)", (event_id, entity_id, "developer", self._now()))
        publication = _publication(document["published_at"])
        evidence = self.store.add_evidence(source_key=document["document_id"], revision=document["id"], publisher=document["publisher"],
                                           url=document["original_url"], published_at=publication, body=document["body"])
        relation = payload.get("relation") or "observation"
        target_id = payload.get("target_id")
        if relation != "observation" and not reviewed:
            raise ValueError("Transitions and corrections require review")
        state = self.store.state(event_id)
        target = None
        if target_id:
            history = self.store.history(event_id)
            target = next((a for a in history["assertions"] if a["id"] == target_id and a["field"] == "status"), None)
            if not target:
                raise ValueError("Target must identify a status assertion in this event")
            if relation == "transition" and target_id not in state["fields"].get("status", {}).get("assertion_ids", []):
                raise ValueError("Stale review: selected transition target is no longer current")
            if relation == "transition" and (timestamp(payload["valid_from"]) <= target["valid_from"] or
                    (target["valid_to"] and timestamp(payload["valid_from"]) >= target["valid_to"])):
                raise ValueError("A transition must advance within the target interval")
            if relation == "correction" and (timestamp(payload["valid_from"]) != target["valid_from"] or
                    (timestamp(payload["valid_to"]) if payload.get("valid_to") else None) != target["valid_to"]):
                raise ValueError("A correction must preserve the target effective interval")
        elif relation != "observation":
            raise ValueError("A transition or correction requires a target assertion")
        if relation == "observation" and target_id:
            raise ValueError("An observation cannot replace an assertion; clear the target or choose a replacement relation")
        values = {"developer": developer, "model": model, "version": version, "status": payload["status"]}
        for field in ("developer", "model", "version"):
            existing = state["fields"].get(field, {})
            if existing.get("status") == "confirmed" and _normal(existing.get("value")) == _normal(values[field]):
                values[field] = existing["value"]
        quote = payload["quote"]
        start = document["body"].index(quote)
        for field, value in values.items():
            is_status = field == "status"
            assertion = self.store.assert_fact(event_id, field=field, value=value,
                valid_from=payload["valid_from"], valid_to=payload.get("valid_to") if is_status else None,
                evidence_id=evidence["id"], message_key=f"{candidate_id}:{field}", confidence=1.0,
                relation=relation if is_status else "observation", target_id=target_id if is_status else None,
                reason=reason if is_status else "Source-supported identity", reviewed=reviewed)
            with self.store.connection(write=True) as db:
                db.execute("INSERT OR IGNORE INTO workflow_assertions VALUES(?,?,?,?,?,?,?,?,?)",
                           (assertion["id"], candidate_id, document["id"], evidence["id"], field, quote, start, start+len(quote),
                            "human_reviewed" if reviewed else "machine_only"))
        now = self._now()
        with self.store.connection(write=True) as db:
            db.execute("UPDATE workflow_candidates SET review_status='accepted',payload_json=?,event_id=?,issues_json='[]',updated_at=? WHERE id=?",
                       (encoded(payload), event_id, now, candidate_id))
            db.execute("INSERT INTO workflow_reviews(candidate_id,action,reason,payload_json,recorded_at) VALUES(?,?,?,?,?)",
                       (candidate_id, "accept" if reviewed else "machine_observation", reason, encoded(payload), now))
            db.execute("UPDATE workflow_jobs SET state='processed',error='',updated_at=? WHERE topic_id=? AND revision_id=?",
                       (now, topic_id, document["id"]))
        return next(c for c in self.list_candidates(topic_id, include_resolved=True) if c["id"] == candidate_id)

    def resume_commits(self, topic_id):
        """Resume acknowledged extraction without another model call after a crash."""
        with self.store.connection() as db:
            rows = db.execute("SELECT c.* FROM workflow_candidates c JOIN workflow_jobs j "
                              "ON j.topic_id=c.topic_id AND j.revision_id=c.revision_id "
                              "WHERE c.topic_id=? AND c.review_status='pending' AND j.state='committing'", (topic_id,)).fetchall()
        completed = []
        for row in rows:
            payload = json.loads(row["payload_json"])
            completed.append(self._commit(topic_id, row["id"], payload, reviewed=False, reason="Source-supported machine observation"))
        return completed

    def event_detail(self, topic_id, event_id, valid_at=None, known_at=None):
        state = self.store.state(event_id, valid_at=valid_at, known_at=known_at)
        if state["event"]["topic"] != self.topic_key(topic_id):
            raise KeyError("Event not found in this Topic")
        history = self.store.history(event_id, known_at=known_at)
        known_assertions = {assertion["id"] for assertion in history["assertions"]}
        evidence = history["evidence"]
        with self.store.connection() as db:
            entities = [dict(r) for r in db.execute("SELECT e.*,l.role FROM workflow_entities e JOIN workflow_event_entities l ON l.entity_id=e.id "
                                                   "WHERE l.event_id=? AND l.recorded_at<=?", (event_id, history["known_at"]))]
            for source in evidence:
                rows = db.execute("SELECT w.*,d.content_status,d.original_url FROM workflow_assertions w "
                                  "JOIN workflow_documents d ON d.id=w.revision_id WHERE w.evidence_id=?", (source["id"],)).fetchall()
                source["passages"] = [{"quote": r["quote"], "start": r["start_offset"], "end": r["end_offset"],
                                       "field": r["field"], "assertion_id": r["assertion_id"]} for r in rows if r["assertion_id"] in known_assertions]
                source["content_status"] = rows[0]["content_status"] if rows else "unknown"
        return {"state": state, "history": history, "evidence": evidence, "entities": entities, "model_version": MODEL_VERSION,
                "expected_version": self._event_version(event_id) if not known_at else None}

    def list_updates(self, topic_id, q="", limit=50, valid_at=None, known_at=None):
        self.topic_key(topic_id)
        limit = max(1, min(100, int(limit)))
        events = self.store.search(topic=self.topic_key(topic_id), valid_at=valid_at, known_at=known_at)
        if q.strip():
            events = [event for event in events if _matches_query(event, q)]
        updates = []
        cutoff = timestamp(known_at or self.store.clock())
        effective = timestamp(valid_at or self.store.clock())
        with self.store.connection() as db:
            for state in events:
                eid = state["event"]["id"]
                history = self.store.history(eid, known_at=cutoff)
                by_id = {a["id"]: a for a in history["assertions"]}
                source_hashes = {e["body_sha256"] for e in history["evidence"]}
                rows = db.execute("SELECT a.*,w.review_status FROM assertions a JOIN workflow_assertions w ON w.assertion_id=a.id "
                                  "WHERE a.event_id=? AND a.field='status' AND a.recorded_at<=? AND a.valid_from<=? ORDER BY a.seq",
                                  (eid, cutoff, effective)).fetchall()
                for row in rows:
                    old = by_id.get(row["target_id"])
                    current_value = json.loads(row["value_json"])
                    duplicate = row["relation"] == "observation" and any(u["event_id"] == eid and u["value"] == current_value for u in updates)
                    if duplicate:
                        continue
                    updates.append({"id": row["id"], "event_id": eid, "title": state["event"]["title"],
                        "kind": "correction" if row["relation"] == "correction" else "field_changed" if row["relation"] == "transition" else "new_event" if not any(u["event_id"] == eid for u in updates) else "conflict",
                        "field": "status", "previous_value": old["value"] if old else None, "value": current_value,
                        "valid_from": row["valid_from"], "recorded_at": row["recorded_at"],
                        "review_status": row["review_status"], "source_count": len(source_hashes), "has_conflicts": state["has_conflicts"]})
        updates.sort(key=lambda u: (u["recorded_at"], u["id"]), reverse=True)
        return {"updates": updates[:limit], "events": events[:limit], "pending_count": len(self.list_candidates(topic_id)),
                "coverage": {"model": "ModelRelease", "version": MODEL_VERSION, "authority": "eventkb", "migrated_kinds": ["ModelRelease"]}}

    def search_documents(self, topic_id, q="", known_at=None, limit=8):
        self.topic_key(topic_id)
        cutoff = timestamp(known_at or self.store.clock())
        def document_tokens(text):
            tokens = _search_tokens(text)
            # Hyphen splitting exposes Qwen4 inside Qwen4-Max; split that
            # joined identifier too so a family query for Qwen can recall it.
            return tokens | {part for token in tokens for part in _search_tokens(token)}
        terms = document_tokens(q)
        with self.store.connection() as db:
            rows = db.execute("SELECT d.*,t.captured_at topic_captured_at FROM workflow_documents d "
                              "JOIN workflow_topic_documents t ON t.revision_id=d.id WHERE t.topic_id=? AND t.captured_at<=? "
                              "ORDER BY t.captured_at DESC,d.id LIMIT 500", (topic_id, cutoff)).fetchall()
        scored = []
        for raw in rows:
            row = dict(raw)
            tokens = document_tokens(row["body"])
            hits = len(terms.intersection(tokens))
            if terms and not hits:
                continue
            row.update(url=row["original_url"], revision=row["id"], score=hits)
            scored.append(row)
        return sorted(scored, key=lambda r: (-r["score"], r["id"]))[:max(1, min(30, int(limit)))]


@lru_cache(maxsize=16)
def _workflow_for_path(path):
    return Workflow(path)


def get_workflow():
    from config import settings
    return _workflow_for_path(str(Path(settings.event_memory_database_path).expanduser().resolve()))
