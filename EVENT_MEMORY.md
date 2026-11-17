# Domain Monitor: event identity and layered memory

The event module is an executable vertical slice: stable identity → immutable source revisions → field assertions → bitemporal projection → history → recoverable memory policies → Markdown indexes. Its Python 3.10+ core uses only SQLite and the standard library; it makes no model calls. The full FastAPI / Next.js application lives in `backend/` and `frontend/`.

The interface, system messages, synthetic demo, and generated analysis use English. Source documents, evidence quotations, user input, and historical records retain their original language. Language instructions apply at the shared model boundary for both regular and streamed responses; they do not guarantee that an external provider will follow instructions.

## Run the complete application

From the repository root:

```bash
python3 scripts/run-local.py --install
# Open http://127.0.0.1:3870/
python3 scripts/run-local.py --check
```

The launcher waits for the full backend before starting the frontend. It checks ports, reports occupied ports without killing unrelated processes, and collects its own child processes on exit. Dependencies are cached under `~/.cache/domain-monitor` to reduce iCloud eviction problems. Later starts can omit `--install`.

The default files are `data/monitor.db`, `data/eventkb.sqlite3`, and `data/chroma/`. Use `--data-dir` to isolate a run. Existing repository data and credentials are never imported automatically. Local mode disables external calls and scheduling. To opt in, explicitly supply `--env-file /absolute/path/to/backend/.env --enable-external`; scheduled collection additionally requires `--schedule`. These options can call configured external services. An unavailable model returns a readable error before creating a background job.

`app:app` exposes the Topic workspace and `/event-memory` together. The first integrated workflow now connects real collection, validated `ModelRelease` candidates, field-level event memory, Topic Updates / Review and original-evidence chat. See [WORKFLOW_IMPLEMENTATION.md](WORKFLOW_IMPLEMENTATION.md) for scope and validation. Other event types retain legacy research coverage; old records have not been silently migrated. Vector candidates still recheck authoritative SQLite content, stable facts retain their history, and snapshots capture their input content.

## Offline demo

```bash
python3 -m eventkb --db data/demo.sqlite3 demo
python3 -m eventkb --db data/demo.sqlite3 memory
python3 -m eventkb --db data/demo.sqlite3 serve --port 8769
python3 -m eventkb --db data/demo.sqlite3 show acquisition-demo-en
python3 -m eventkb --db data/demo.sqlite3 show acquisition-demo-en --valid-at 2026-01-15T00:00:00Z
```

Open `http://127.0.0.1:8769`. The demo contains a synthetic acquisition and conflicting rumours, with `example.invalid` source URLs that the page does not fetch. English demo identities and source keys have their own namespace; rerunning them preserves earlier immutable fixtures. Replay reuses facts but appends policy records. Never run the demo against real evidence.

The effective dates are in January–February 2026. Known-by timestamps are generated at insertion time, so a cutoff before the demo was inserted returns no known facts. Tests use a controlled clock to distinguish knowledge available then from later reconstruction.

For the standalone FastAPI adapter:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-event-memory.txt
.venv/bin/python -m eventkb --db data/demo.sqlite3 api --port 8770
# In frontend/, after npm ci:
EVENT_MEMORY_API_BASE=http://127.0.0.1:8770 npm run dev -- --webpack --hostname 127.0.0.1 --port 3870
```

Open `/event-memory` directly. This standalone adapter does not serve the legacy topic or chat APIs.

## Query and UI contract

`GET /api/event-memory/query?topic=synthetic` requires a topic. Optional parameters are `q`, `event_id`, `valid_at`, `known_at`, `include_archived`, and `limit` (1–100). Results contain only the selected projection's fields, explicitly unresolved alternatives, source metadata, and revisions. They exclude historical assertions, source bodies, chat history, old summaries, and vector text. Bodies are available through the separate history request for traceability. Agreement among stored values does not mean external verification.

The page supports isolated topics, effective-field search, effective/known-by dates, conflicts, citations, original evidence, importance, pinning, archiving, and restoration. Historical policies are read-only. Date inputs use the explicit English format `YYYY-MM-DD HH:mm` in the browser's local time zone; displayed results use Sydney time. Invalid formats and calendar dates are rejected before a query. Scope changes hide stale results immediately and cancel obsolete requests. Late query responses and late save callbacks cannot restore a previous topic. Unsafe evidence URLs are not rendered as links.

The adapter also provides `GET /health`, `GET /topics`, `POST /events`, `POST /evidence`, `GET /events/{id}/state`, `GET /events/{id}/history`, `POST /events/{id}/assertions`, and `POST /events/{id}/memory`, under `/api/event-memory`. Detail, history, and write requests validate topic ownership. Callers cannot backdate known-by timestamps. Responses disable caching.

`uvicorn app:app` mounts the new router by default. Starting `backend/main:app` directly requires `EVENT_MEMORY_ENABLED=true`. Scheduling requires both `SCHEDULER_ENABLED=true` and `EXTERNAL_CALLS_ENABLED=true`. Storage paths resolve relative to the repository root. Docker builds must use the repository root as the backend context so they include `eventkb` and `app.py`. Configure hosts with `EVENT_MEMORY_HOSTS` and browser origins with `CORS_ORIGINS`; the default host list includes Render's own `RENDER_EXTERNAL_HOSTNAME` when present. Host/origin checks are not authentication or multi-user access control.

## Data model

- `events`: stable IDs, a topic-scoped unique identity key, immutable display label, and event kind. Mutable headlines belong in field assertions. Title similarity does not automatically merge identities.
- `assertions`: event, field, JSON value, effective interval, server-recorded timestamp, evidence, confidence, idempotency key, relation, target, and review reason. Participants include entity IDs and roles; amounts, locations, and statuses evolve independently.
- `evidence`: source key, revision, publisher, URL, publication date, original text, SHA-256, and recorded time. A source revision is immutable. A revised source does not automatically rewrite facts; add an explicit targeted correction.
- `memory_policy`: importance, pinning, active/summary/archived tier, reason, and timestamp. Append-only policy audit is separate from factual truth.

SQL triggers reject updates and deletes on authoritative tables. Writes use transactions and foreign keys. Clock rollback rejects writes rather than rewriting history. `Store(clock=...)` exists for controlled offline replay tests. All timestamps require a time zone and normalize to UTC. Intervals are `[valid_from, valid_to)`; an absent end means no declared termination.

## Evolution rules

1. An **observation** requires evidence and effective time. Replaying the same message and content returns its original ID without refreshing recorded time. Reusing a key for different content fails.
2. A **transition** targets an assertion in the same event and field, moves effective time forward, and requires `reviewed: true` plus a reason. It closes the predecessor from the transition time. If a finite successor interval ends, the predecessor does not revive; the field becomes unknown.
3. A **correction** preserves the original and targets it explicitly. Effective interval boundaries must match exactly; complex partial restatements must be split upstream. Correcting an amount leaves participants and status unchanged.
4. Concurrent opposing values without explicit replacement remain a conflict: `value: null`, both assertions and their evidence. Recency, source count, or confidence does not choose a winner. `confirmed` means the projection's active values agree, not external fact verification. Confidence is not probability calibrated.
5. A late report with an explicitly ended effective interval can enrich history without changing the present. Publication and recorded times cannot substitute for effective time. Unknown validity remains unresolved for review.
6. Correcting a closed historical state does not revive it. Correcting a transition retains its closure of the predecessor.

State queries first select assertions known by `known_at`, then project at `valid_at`. History returns the append-only records and immutable source revisions; it does not manufacture history by mutating current rows.

## Retrieval and selective forgetting

Search matches reconstructed field values, not historical bodies or stale vector caches. Conflict alternatives are not treated as confirmed search values. An event label can still locate an unresolved event. Historical queries reconstruct their own fields rather than reuse a current summary.

Stable facts do not become false as news ages. Attention decays with a prototype 90-day half-life: `importance * 2^(-policy_age_days/90)`, multiplied by 0.5 for summary tier; pinned weight is 1. Results explain the score. This is an interpretable prototype policy, not a validated business optimum. Archived events disappear from default lists but remain retrievable by ID or `include_archived=true` and can return to active. Facts, evidence, and transitions are retained.

The `memory` command regenerates disposable indexes:

```text
memory/MEMORY.md        # Up to 20 active entries
memory/archive.md       # Archived and overflow entries
memory/events/<id>.md   # Projection, evolution, evidence, and policy history
```

Editing Markdown does not alter SQLite. Regenerate after writes; automatic background refresh is not implemented. Complete event files currently have no length budget and will need pagination at scale. This design does not copy personal memories or claim to reproduce private ChatGPT internals.

## Validation and remaining work

See `SYSTEM_VALIDATION.md` for full-system checks. The targeted React harness additionally needs a matching optional `react-test-renderer@19.2.4` outside product dependencies:

```bash
node scripts/validate-event-memory-ui.cjs /path/to/test/node_modules
```

Legacy vector results now contribute IDs only; SQLite revalidates body, topic, and lifecycle. Stable fact/structural claims no longer expire from age alone; terminal states require explicit restoration. New snapshots capture associated content at insertion. Missing captures in old snapshots are marked unavailable rather than filled with current content.

The integrated ModelRelease slice adds identity candidates, strict source-supported effective-time extraction, assertion review, a small explicit alias registry and bitemporal chat projection. Broader audited migration, field-level permissions, richer aliases/merges and time precision, partial-interval correction, retractions and scalable indexes remain subsequent work. Policy editing on the standalone page is separate from assertion review in Topic. The standalone standard-library HTTP server binds only to localhost and must not be treated as a public authenticated service.
