# Full-system repair and validation — 2026-11-17

The system repair at `b9d8405` builds on event-memory integration at `0850815`. This document records that completed local validation; the subsequent English release and online checks are recorded in `DEPLOYMENT.md`.

## Repairs

- Added `app:app` and `scripts/run-local.py` so one backend serves topics, articles, chat, and event memory. The frontend proxy uses that same backend.
- Added port/readiness checks and cleanup of owned processes. Dependencies use a durable cache outside iCloud-managed source directories. Storage paths resolve from the repository root with explicit data/config overrides.
- Disabled external calls and scheduling by default in the local launcher. Disabled or unconfigured services return a readable error before creating a job. The page displays local mode.
- Restricted automatic retries to GET/HEAD. Failed reads retain server error details; writes reach the toast parser without duplicate submissions.
- Prevented duplicate chat starts, unlocked failures, cleared loading after fast completion, and rejected late responses belonging to another topic.
- Revalidated vector candidates against SQLite body, topic, and lifecycle; excluded superseded, missing, inactive, and cross-topic records.
- Stopped age-only expiry of stable fact/structural claims and automatic revival of terminal states.
- Captured event/claim content at snapshot association insertion. Later changes, deletion, and restarts do not change captures. Missing old captures remain explicitly unavailable.
- Included the new event module in Docker/Render build inputs and made Compose's local environment file optional.

## Completed local verification at b9d8405

| Check | Observed result |
| --- | --- |
| Python suite | **213 passed**, including 179 existing tests plus event memory, legacy regressions, and full-app integration. Three existing fixture deprecation warnings. |
| Full application | **39 checks**, included in one test above: actual ASGI lifespan, SQLite, Chroma writes/search/delete/reopen, topic/keyword/RSS/document APIs, chat SSE, persisted jobs, restart recovery, isolation, and unavailable-provider boundaries. |
| Frontend behavior | **18 checks**: 8 topic/chat state, 5 event-page late requests/date/history protections, 5 API error/retry checks. Network responses are synthetic. |
| API and button contracts | Nine API contracts plus button state/copy checks passed through the actual frontend proxy. |
| Production frontend build | `npm run build -- --webpack` passed TypeScript checks and all five routes. |
| Startup/shutdown | Both services started on isolated ports; SIGTERM released both ports without orphaning children. |
| Browser | Created a synthetic topic; checked a readable local-mode chat failure with input retained; exercised current/history evidence, archive/recall/restore. No homepage load error. |
| Configuration | Compose config, `pip check`, and `git diff --check` passed. |

The original checkout's README and Chroma SQLite matched their preserved SHA-256 hashes. No original data or credentials were imported, and no private documents were uploaded. Local synthetic acceptance records remain available for review. Earlier screenshots and `artifacts/system-verification.json` intentionally retain their historical wording.

## Boundaries

Integration tests replace external response generators and block outbound connections. Chroma uses deterministic test embeddings without downloading a model. No real paid model/news calls or embedding-quality evaluation were performed. The Docker engine was not running during this local validation, so configuration checks did not establish that an image built or deployed successfully.

The original chatbot/ingestion still use the legacy knowledge store. New field-level bitemporal projection has not replaced that pipeline. Missing past snapshot content cannot be recreated.

## Repeat

From the repository root:

```bash
python3 scripts/run-local.py --install
python3 scripts/run-local.py --check
PYTHONPATH="$PWD/backend:$PWD" ~/.cache/domain-monitor/venv/bin/python -m pytest backend/tests tests -q
~/.cache/domain-monitor/venv/bin/python scripts/validate-system.py
node scripts/validate-topic-isolation.cjs "$PWD"
node scripts/validate-api-errors.cjs
node scripts/validate-event-memory-ui.cjs /path/to/test/node_modules
```

Stop this checkout's development server before building:

```bash
cd frontend
INTERNAL_API_BASE=http://127.0.0.1:8000 npm run build -- --webpack
```

Historical acceptance artifacts: `artifacts/system-verification.json`, `artifacts/system-memory-current.jpg`, `artifacts/system-memory-history.jpg`, and `artifacts/system-chat-local-mode.jpg`.
