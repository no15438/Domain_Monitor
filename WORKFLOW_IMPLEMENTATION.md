# Integrated event workflow

Implementation branch: `feat/event-memory-workflow`.

The first integrated domain model is **ModelRelease v1**. Collection, original source revisions, candidate extraction, event assertions, Updates, review and question-specific evidence retrieval now share the Topic workspace. Other domains retain the existing source reading, research brief, analytical claims, snapshots and long-term analysis.

## Data and authority

- Every collected source revision is captured before URL / similarity filtering in the existing event-memory database. Documents can belong to several Topics. Original URLs and retained text remain separate from comparison keys.
- Exact developer, model family and release version determine the Topic-scoped release identity. Version punctuation is significant. A small explicit alias registry normalizes known developer aliases; ambiguous identities require review.
- Bounded batch enrichment produces both the existing analysis and a structured release candidate. Deferred release revisions remain in the durable queue for subsequent runs within the configured AI limits. Failed attempts preserve source content and do not generate successful default facts.
- Source-supported, unambiguous observations can enter eventkb as machine-only records. Conflicting states, replacements and uncertain time remain candidates. An accepted observation is not a claim of external verification.
- Store transactions cover the candidate decision, event, evidence, all assertions and passage links. A failed commit rolls back as a whole; an interrupted automatic outbox job can be retried without another model request.
- The source revision, original quotation and offsets are retained for each assertion. Event history and known-by queries never replace the source with a newly generated summary.
- Existing historical records are not silently migrated or backdated. A document's old publication or capture time is not the knowledge time of a newly extracted assertion.

All workflow tables are additive in `eventkb.sqlite3`, covered by the existing Spark data mount and backup procedure. Text indexes and current caches are disposable; retained source revisions, assertions, reviews and published reports remain durable.

## Review policy

The accepted release path currently requires an **explicit timezone-aware effective timestamp in retained source text**. A publication date, a date without timezone or a model guess cannot satisfy it. Such material remains visible under Review and can be read as source material. Leave the candidate unresolved when the evidence cannot support an effective time.

Review shows the original source, identity, business state, effective time, target assertion and reason. Users can select an existing matching identity or create a new one, accept, reject or defer. Target state/version is loaded when association changes. The server rechecks the version under the same transaction as acceptance; a stale decision returns `409` and requires a fresh review.

Transitions advance a target's effective interval. Corrections preserve its interval and keep the original assertion. Contrary observations remain explicit conflicts when no reviewed replacement is established. Negation, future promises and rumours cannot automatically become available-state facts.

## Workspace and answers

- **Updates** shows accepted new events, state changes, corrections and conflicts with evidence inspection.
- **Sources** retains the previous news reading view and unprocessed source material.
- **Review** exposes unresolved candidates and concrete reasons rather than hiding extraction failure.
- **Briefing** preserves current and long-term analysis. New briefings read authoritative release projections, retain their input versions and label other coverage as legacy analysis. Older / changed-input briefings display a refresh notice.
- Asking about an event preserves its facts and evidence in the workspace and sends the explicit event and temporal scope to chat.
- Retrieval uses question relevance and exact versions instead of a total-record threshold. Scoped release facts come from eventkb. Historical questions exclude current summaries, prior assistant assertions and live web results.
- Bound `[S1]` citations open the retained original passage, revision and source link. Unbound labels do not become apparent evidence controls. Raw document recall is labelled unstructured source material; it cannot substitute for an accepted historical fact.

Interface and generated prose remain English. Original quotations and user input keep their original language.

## API

All endpoints validate the existing numeric Topic and enforce the configured event-memory host / origin boundary:

```text
GET  /api/topics/{topic_id}/memory/updates?q=&valid_at=&known_at=&limit=
GET  /api/topics/{topic_id}/memory/events/{event_id}?valid_at=&known_at=
GET  /api/topics/{topic_id}/memory/candidates
POST /api/topics/{topic_id}/memory/candidates/{candidate_id}/review
```

Review accepts `action`, `reason`, `expected_version` and optional corrected `developer`, `model`, `version`, `status`, `valid_from`, `valid_to`, `quote`, `event_id`, `relation`, `target_id`. Quotes and timestamps are validated against the retained source. Request bodies reject unknown fields.

Both chat APIs accept optional `event_id`, `valid_at` and `known_at` alongside the existing Topic and message fields. A Topic is required for scoped questions. Invalid or foreign scopes fail before creating a background chat task.

The AI-summary and global-overview responses add `event_memory_stale` and `event_memory_notice`. Old snapshots remain retained; this status does not rewrite them.

## Reproducible validation

Run in the repository root with the full backend environment:

```sh
DOMAIN_MONITOR_ENV_FILE=/dev/null EXTERNAL_CALLS_ENABLED=false SCHEDULER_ENABLED=false \
  python -m pytest backend/tests tests -q
python scripts/validate-workflow.py --output /tmp/workflow-verification.json
node scripts/validate-workflow-ui.cjs /path/to/optional/react-test-renderer/node_modules
cd frontend
npm run build -- --webpack
```

The isolated workflow acceptance uses real RSS parsing, the actual pipeline, temporary SQLite / Chroma and the real API / retrieval layers, with synthetic source content and model responses and blocked outbound sockets. It checks collection through accepted events, original evidence, review transitions and corrections, known-by answers, Topic isolation, stale / origin rejection, persisted chat and reopen consistency. These checks establish executable contracts; they do not measure production news or model accuracy.

The original test and operational suites remain required. Spark release verification must additionally check health, actual bounded news / Alibaba operation, source / candidate persistence, service recreation and backup restore. Preserve `/srv/domain-monitor/{config,data,cache,backups}` and retain rollback images before upgrading.

## Subsequent scope

More event types, richer date precision, partial-interval corrections, retractions, editable domain models and broader document parsing can extend this slice. A graph database or a free-form ontology editor is not required for the integrated workflow.
