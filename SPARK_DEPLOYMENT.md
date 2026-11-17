# Spark LAN deployment

Active deployment: **http://spark-f74d.local:3870** (same LAN). Current IP fallback: **http://192.168.1.116:3870**. The frontend is the only published application port; the backend stays inside the dedicated Docker network. No public cloud subscription was configured.

## Services and storage

- Existing `spark-lan` ARM64 host; independent Compose project `domain-monitor`.
- Application: `/srv/domain-monitor/app`; private configuration: `/srv/domain-monitor/config`. Credentials are excluded from Git, images and data backups.
- SQLite and Chroma indexes: `/srv/domain-monitor/data`, bind-mounted at `/app/data`. Missing mounts or data paths outside that mount prevent backend startup.
- CPU embedding model cache: `/srv/domain-monitor/cache/chroma`, preserved across container replacement. Text generation uses Alibaba Qwen.
- `domain-monitor.service` starts the stack after Docker/network on boot. Containers restart on process failure. Docker health checks cover both services; logs rotate at 10 MB × 3 per container.
- Idle news streams flush an initial frame immediately and send 15-second heartbeats, so proxy connections can open before new articles arrive.
- Frontend uses Node 24 LTS. Both images are built for ARM64 on Spark. The original desktop databases were not imported or altered; the deployment retains the existing English public-news topic and earlier isolated acceptance records.

## AI and collection limits

Existing Alibaba DashScope international credentials are reused for `qwen3.5-flash`. Existing Tavily credentials support news and assistant search. Google News RSS and configured RSS feeds also work without a search key. The BBC technology feed is the global feed; topic feeds remain editable in the English interface.

- Collection every 60 minutes, active/unarchived topics only.
- At most 4 distinct search terms, 3 results per keyword/provider and 4 enriched event representatives per topic/run.
- At most 100 model requests and 20 Tavily searches per UTC day, shared by scheduled and manual work. Counts persist in `ai-usage.sqlite3`; failed attempts count too. RSS remains available after the Tavily ceiling. These are request ceilings, not currency-denominated spending guarantees; account pricing/free allowances still apply.
- Model timeout: 90 seconds; output limit: 4,096 tokens; no DashScope SDK retry; thinking disabled. Feed timeout: 20 seconds; maximum feed size: 4 MB. Search timeout: 20 seconds.
- AI text is requested in English. Original evidence and quotations are preserved.

## Backups and recovery

`domain-monitor-backup.timer` runs around **04:00 Australia/Sydney**, with up to two minutes of jitter. It stops the writer, copies SQLite WAL and Chroma files together, checks the archive, then restarts the backend even if archiving fails. Expect a brief API interruption during backup. It retains 14 days under `/srv/domain-monitor/backups`, with SHA-256 sidecars.

The Mac login job `net.domain-monitor.backup-sync` mirrors backups over SSH around **04:30 local time** and on login to `~/.local/share/domain-monitor/backups`. It verifies checksums and retains existing local copies. Spark must be reachable and the Mac logged in; the first archive has already been mirrored. This is a second copy on another disk.

Restore into a **new** directory; the verifier refuses existing destinations and unsafe archive paths:

```sh
python3 scripts/verify-backup.py /path/to/domain-monitor-TIMESTAMP.tar.gz /new/restore-directory
```

The adjacent `.sha256` file is required. For actual recovery, stop `domain-monitor.service`, retain the old `data` directory under a new name, install the verified restored directory at `/srv/domain-monitor/data`, then start the service. Never overwrite open SQLite/Chroma files or remove the old copy before acceptance.

## Operations

```sh
ssh spark-lan
systemctl status domain-monitor.service
systemctl list-timers domain-monitor-backup.timer
cd /srv/domain-monitor/app
docker compose --env-file /srv/domain-monitor/config/deployment.env -f compose.spark.yaml ps
systemctl start domain-monitor-backup.service
```

Preserve `/srv/domain-monitor/{config,data,cache,backups}` during upgrades. Update application files, then use the same Compose command with `up -d --build --wait`. Never print credential files or put keys in command-line arguments. The frontend binds the host interfaces for trusted-LAN use. `spark-f74d.local` avoids depending on the current DHCP address.

## Event-workflow release

Branch `feat/event-memory-workflow` integrates collection, retained source revisions, ModelRelease candidates, field-level event memory, Updates, review and source-bound question answering. Other domains retain the existing research and analysis features. See `WORKFLOW_IMPLEMENTATION.md` for the implemented boundary and review policy.

Local verification passed 287 Python tests, 38 frontend behavior checks, 39 isolated system checks and 40 isolated workflow checks. The offline workflow checks use synthetic inputs with real temporary stores and no outbound network access; they do not measure production extraction accuracy. Six Python deprecation warnings remain.

Deployed application code: `db7bd252b5164f5a5cc912e0023adeeca51300e7`. The ARM64 build and all 40 isolated workflow checks also passed in the actual Spark backend image, without production mounts or networking.

Spark acceptance on this release:

- One bounded real collection received 88 items, retained 67 distinct source revisions and added 3 news articles. Two release candidates remain unresolved; no synthetic production event or unsupported effective time was added.
- Real Alibaba generation completed an English briefing and source-reporting answer. Three retained passages were returned; the used `[S#]` citations matched their stored source offsets. The answer explicitly distinguished unstructured reports from unavailable accepted facts. Trace confirmed event-memory retrieval with legacy/vector/web supplementation excluded.
- Twelve real-service checks, four additional source-reporting checks and six invalid-scope/origin checks passed. The deployed English interface opened the retained quotation, source revision and original link after container recreation.
- Both containers were forcibly recreated. Eleven fixed-time API projections, all rows in 38 SQLite tables and all document/metadata records in four Chroma collections were identical before and after. This includes source revisions, candidates, review history, chat, briefings and durable request counters.
- Final consistent backup `domain-monitor-20261117T175222Z.tar.gz` passed checksum and four SQLite integrity checks after isolated restore. With networking disabled, restored Chroma returned two semantic matches; all 67 retained source hashes and the new chat were intact. The archive was checksum-verified on the Mac mirror as well.
- The configured Reuters RSS endpoint returned HTTP 401 and was disabled without deleting its stored row. BBC, Google News and The Verge feeds remain configured; Reuters news can still arrive through search. One Google News keyword returned HTTP 429 during collection; other collectors completed and the run preserved their results.

Daily backup and service startup remain enabled. Rollback source directories and images are retained separately from the live configuration and data. Detailed generated verification records stay local under `artifacts/spark-workflow-*.json`; source and documentation changes are committed on the feature branch.

## Previous deployment acceptance

- 226 Python tests, 20 frontend behavior checks and 39 isolated system checks passed. Three pre-existing pytest fixture deprecation warnings remain.
- Real Alibaba and Tavily credentials verified with bounded calls. Nine real-service checks passed, covering research setup, collection/enrichment, provenance, events/evidence/claims, summary and chat. The first run collected 21 articles, including four enriched representatives; alternative source articles intentionally have no separate AI summary.
- 26 event-memory API checks passed through the Spark frontend: transitions, corrections, effective/known-by history, archive/restore, isolation and origin rejection.
- Eight API projections were identical after forced container recreation: topics, news, summary, chat, events, evidence, claims and the synthetic bitemporal projection.
- A consistent backup restored into an isolated directory. All four SQLite databases passed integrity checks. With networking disabled, restored Chroma contained 4 events, 8 evidence documents, 8 claims and 1 snapshot; semantic retrieval returned two matches using the persistent local model cache.

Results are in `artifacts/spark-*-verification.json`. Render remains an earlier ephemeral preview; Spark is the active AI/news and durable-storage service. The event-workflow release adds the first integrated ModelRelease slice; broader domain migration remains subsequent work.
