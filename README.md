# Domain Monitor — AI-Powered Industry Intelligence

Real-time industry monitoring system powered by AI. Automatically fetches, deduplicates, clusters, summarizes, and categorizes industry news from multiple sources. Builds a structured, time-aware knowledge base over time, and exposes it through an AI chatbot that uses a multi-layer RAG pipeline to answer questions with full temporal awareness.

---

## Table of Contents

- [System Architecture](#system-architecture)
- [Features](#features)
  - [Topic Management](#topic-management)
  - [Research Brief](#research-brief)
  - [Data Pipeline](#data-pipeline)
  - [Knowledge Base & Event Lifecycle](#knowledge-base--event-lifecycle)
  - [AI Analysis (Realtime Tab)](#ai-analysis-realtime-tab)
  - [Global Overview](#global-overview)
  - [Alert Signals](#alert-signals)
  - [AI Assistant — Multi-Layer RAG Chatbot](#ai-assistant--multi-layer-rag-chatbot)
- [RAG Pipeline — How It Works](#rag-pipeline--how-it-works)
- [Context Engineering](#context-engineering)
- [Tech Stack](#tech-stack)
- [Quick Start](#quick-start)
- [Environment Variables](#environment-variables)
- [API Reference](#api-reference)

---

## System Architecture

```
┌──────────────────────────────────────────────────────────────────────────┐
│  DATA INGESTION                                                          │
│                                                                          │
│  Sources: NewsAPI · Google News RSS · User RSS Feeds ·                   │
│           Event Registry · Tavily Web Search                             │
│    ↓                                                                     │
│  Stage 1  Collect        parallel fetch from all sources                 │
│  Stage 2  URL dedup      normalize + drop exact-URL duplicates           │
│  Stage 3  Semantic dedup TF-IDF cosine; keep most-authoritative per      │
│                          near-duplicate cluster (threshold: 0.82)        │
│  Stage 4  Relevance      3-tier keyword match; drop off-topic articles   │
│  Stage 5  Event cluster  group semantically related articles → events    │
│  Stage 6  Canonical sel. score by authority + coverage; pick best repr.  │
│  Stage 7  LLM enrich     batch: summary / tags / sentiment /             │
│                          importance (1–10) / topic analysis              │
│    ↓                                                                     │
│  Storage: SQLite (structured) + ChromaDB (vector embeddings)             │
│    ↓                                                                     │
│  SSE Push → Frontend                                                     │
├──────────────────────────────────────────────────────────────────────────┤
│  KNOWLEDGE SYNTHESIS (scheduled)                                         │
│                                                                          │
│  Snapshot engine    daily AI snapshots of domain state                   │
│  Claim tracker      extract & evolve key claims (fresh→stale→superseded) │
│  Global Overview    long-term macro synthesis from all snapshots         │
│  Evolution Report   narrative of how the domain changed over time        │
├──────────────────────────────────────────────────────────────────────────┤
│  FRONTEND (Next.js App Router)                                           │
│                                                                          │
│  Homepage:    Topic cards (create / rename / delete)                     │
│  Topic page:  3-column layout                                            │
│    Left:      Research Brief (AI-generated research plan, CRUD)          │
│    Middle:    Event feed (right-click context menu)                      │
│    Right:     Analysis Panel                                             │
│               Realtime tab: AI Analysis + Alert Signals                  │
│               Overview tab: Global Overview · Snapshots ·                │
│                             Core Articles · Macro Signals                │
│  AI Chatbot:  RAG-powered chat (replaces right panel while open)         │
└──────────────────────────────────────────────────────────────────────────┘
```

---

## Features

### Topic Management

- Create multiple independent monitoring topics (e.g., "AI in Healthcare", "China Macro")
- Each topic has its own color label, research brief, keyword list, RSS feeds, event feed, AI analysis, and chat history
- Topics can be archived or deleted; archived topics remain queryable

### Research Brief

Natural-language research direction → AI-generated structured plan:

- **Keywords** — search terms used by all collectors
- **RSS Feeds** — auto-suggested relevant feeds, user-editable
- **Research Angles** — thematic lenses to monitor
- **Key Entities** — companies, people, or organizations to track
- **Geographic & Sector Scope** — filters for the pipeline

All generated items are fully user-editable (CRUD). The brief is re-injectable at any time to regenerate the plan.

### Data Pipeline

Multi-stage recall-then-precision pipeline triggered on schedule (default: every 15 minutes) or manually via "Fetch Now":

| Stage | What happens |
|---|---|
| **1. Collect** | Parallel fetch from NewsAPI, Google News RSS, user-added RSS feeds, Event Registry, Tavily |
| **2. URL dedup** | Normalize URLs; drop exact-URL duplicates |
| **3. Semantic dedup** | TF-IDF cosine similarity; clusters near-duplicates and keeps the most authoritative source (highest domain authority + coverage score) |
| **4. Relevance filter** | Three-tier keyword matching (exact phrase → space-collapsed → any-word); configurable minimum threshold |
| **5. Event clustering** | Groups semantically similar articles into event clusters using TF-IDF similarity |
| **6. Canonical selection** | Scores each source within a cluster by authority signals + number of other sources covering the same story; elects one canonical article per cluster |
| **7. LLM enrichment** | Single batch LLM call per canonical article: generates summary, tags, sentiment (positive/neutral/negative), importance score (1–10), and topic-specific analysis |

### Knowledge Base & Event Lifecycle

#### Events

Each **event** is a semantically deduplicated cluster of related news articles that the pipeline groups together into a single named story. It is not a raw article — it is the system's best understanding of one discrete development, backed by one or more source articles.

**How an event is created:**

1. The deduplication stage groups near-duplicate articles using TF-IDF cosine similarity
2. The canonical selection stage elects the most authoritative article in each cluster as the representative
3. The LLM enrichment stage generates a short event **summary**, **tags**, **sentiment**, and **importance score** for the canonical article only
4. The event is stored in `events_v2` with references back to all contributing source articles in `event_sources`

**What an event contains:**

| Field | Description |
|---|---|
| `title` | LLM-generated headline |
| `summary` | LLM-written summary of the cluster (≤ 240 chars displayed) |
| `canonical_article_id` | The elected best-representative article |
| `first_seen_at` / `last_seen_at` | Observation window — when this story was first and most recently seen |
| `stability_score` | 0–1 score reflecting how consistently this event has been covered across multiple independent sources; high stability = well-confirmed story |
| `fact_confidence` | Confidence in the factual claims within the event |
| `status` | `active`, `archived`, `superseded` |
| `supersedes_event_id` | If this event supersedes an older one, links to the predecessor |

**Source citations on events** — every event maintains an `event_sources` link table connecting it to all raw news articles that contributed to the cluster. In the UI, clicking an event card shows the canonical source; expanding the card reveals all alternative sources that covered the same story.

**Article states** (managed via right-click context menu on any article card):

| State | Meaning |
|---|---|
| **Active** | Visible in the main event feed |
| **Knowledge Base** | Bookmarked as important; surfaced in Overview → Core Articles |
| **Archived** | Hidden from main feed; visible in collapsible section |
| **Deleted** | Permanently removed |

**Importance decay** — article importance scores apply exponential time decay (half-life ≈ 7 days), so older items naturally drop in sort order relative to new arrivals.

---

#### Claims

A **claim** is a structured, reusable piece of knowledge extracted from the event stream — a distilled assertion about the domain that can be tracked, strengthened, or invalidated as new evidence arrives. Claims live independently of individual articles; they are the system's long-term memory.

**Claim types (`claim_type`):**

| Type | Example |
|---|---|
| `fact` | "China's QFII quota was expanded by $50B on March 31, 2026" |
| `trend` | "Institutional foreign inflows into A-shares have been increasing for 6 consecutive weeks" |
| `risk` | "Escalating tariff uncertainty is suppressing IPO activity in the TMT sector" |
| `signal` | "PMI fell below 50 for the second consecutive month" |

**Claim lifecycle:**

| State | Meaning |
|---|---|
| **Fresh** | Actively supported by recent evidence; safe to present as current |
| **Stale** | No new supporting signal in the past N days; treat with caution |
| **Superseded** | A newer, contradictory or updated claim has replaced this one |
| **Inactive** | Claim stopped receiving any support; demoted but preserved for archive |

Each claim carries `last_validated_at` (when it last received supporting evidence) and a configurable `decay_policy` (`fast` / `medium` / `slow`) that controls how quickly it transitions from fresh → stale.

**How claims relate to events:**

- Claims are linked to the events that support them via `supporting_evidence_ids`
- Each event can spawn one or more claims; each claim can be supported by multiple events
- When a new event contradicts an existing claim, the system can mark the old claim as `superseded` and create a replacement, recording the transition in `claim_evolution`

**Claim evolution log** — every time a claim's status changes, a `claim_evolution` record is written:

```
relation_type: strengthened | weakened | superseded | reinstated
reason:        "New trade data confirms Q1 export growth"
created_at:    2026-03-25
```

This log is surfaced directly in the RAG chatbot's timeline layer, giving the LLM an explicit change-log of how the domain's key assertions have evolved over time rather than requiring it to infer change from static snapshots.

---

#### Snapshots & Deltas

The system periodically generates a **temporal snapshot** — an AI-written summary of the domain state at a point in time. Each snapshot:

- Records which events (`snapshot_events`) and claims (`snapshot_claims`) were active at that moment
- Is stored alongside computed statistics (`stats_metadata`)

When a new snapshot is created, the system computes a **snapshot delta** against the previous one:

```
change_summary:           "Regulatory tone shifted from restrictive to accommodative;
                           two new QFII quota expansions announced."
new_event_ids:            [...] — events that appeared since last snapshot
resolved_event_ids:       [...] — events that dropped out
strengthened_claim_ids:   [...] — claims that gained supporting evidence
weakened_claim_ids:       [...] — claims that lost support
superseded_claim_ids:     [...] — claims replaced by newer ones
```

Deltas are exposed in the RAG chatbot's timeline layer under `[Snapshot Deltas — What Changed]`, making temporal evolution queries highly accurate without requiring the LLM to diff two large documents.

### AI Analysis (Realtime Tab)

LLM-generated narrative analysis of the topic, updated on demand or on a schedule:

- Synthesizes the most recent events, claims, and signals into a coherent narrative
- Includes **Notable Signals** (alert-worthy developments) and an **Outlook** section
- Contains inline **cite buttons** linking to source articles:
  - Article cite → opens original article URL
  - Event cite → opens event canonical source URL
  - Hovering shows source title; missing citation data falls back gracefully to plain text

### Global Overview

Long-term macro analysis synthesized from all historical AI snapshots:

- Covers domain evolution, persistent themes, key entity trajectories, and trend direction
- Narrative evolution (event turnover, claim strengthening/weakening/superseding) is merged into the overview text rather than kept as a separate panel
- Regenerable on demand; the most recent artifact is cached and served instantly

### Alert Signals

Rule-based signals computed over the configured time window:

| Signal | Threshold |
|---|---|
| High negative sentiment | ≥ 40% of recent articles are negative |
| Elevated negative sentiment | ≥ 30% of recent articles are negative |
| Volume surge | Current-period article count ≥ 2× the previous period |
| High importance density | ≥ 40% of articles with importance ≥ 8 |

Time-window metrics use `published_at` as the primary timestamp, falling back to `created_at` when publish time is unavailable.

### AI Assistant — Multi-Layer RAG Chatbot

RAG-powered conversational assistant with full temporal awareness. See [RAG Pipeline — How It Works](#rag-pipeline--how-it-works) for the full technical breakdown.

**Key user-facing features:**

- **Article context injection** — clicking "Ask AI" on an event card pre-loads that article's full metadata and content into the chat context
- **Inline citation buttons** — responses contain clickable `[Source Title]` chips; clicking a knowledge-base item (event, snapshot) navigates directly to it in the Overview panel without opening a new page
- **RAG thinking bar** — shows a concise trace of which knowledge layers were activated, how many records were retrieved, and the final execution path; expandable for step-by-step detail
- **Multi-turn history** — the last 8 messages are passed to the LLM for conversational continuity
- **Per-topic persistence** — chat history is saved to `localStorage` per topic and survives page refreshes

---

## RAG Pipeline — How It Works

Every chat message goes through a fully automated 9-step pipeline. Users send a plain question; the system decides everything else.

```
User question
      │
      ▼
 1. Classify intent          lightweight LLM call (temp=0)
    → which layers needed?   needs_current_state / needs_timeline / needs_archive
    → how far back?          time_window_days (7 / 14 / 30 / 60 / 90 / 180)
    → fallback               rule-based regex if LLM confidence < 0.40
      │
      ▼
 2. Retrieve current state   DB-first (always when needs_current_state=true)
    ├─ Active events          last 21 days, up to 8 events
    ├─ Fresh claims           actively supported, up to 12
    ├─ Stale claims           aging signal, up to 4
    ├─ Latest AI snapshot     most recent daily briefing
    └─ Global overview        long-term synthesis artifact
      │
      ▼
 3. Retrieve timeline         DB-first (when needs_timeline=true)
    ├─ Timeline events        time-window events sorted oldest→newest, up to 12
    ├─ Snapshot deltas        what changed between snapshots, up to 3
    └─ Claim evolution        strengthened / weakened / superseded signals, up to 15
      │
      ▼
 4. Retrieve archive          DB-first (when needs_archive=true)
    ├─ Superseded claims      replaced by newer findings, up to 6
    ├─ Inactive claims        no recent support, up to 4
    └─ Older snapshots        historical snapshots (excluding latest), up to 2
      │
      ▼
 5. Freshness resolution      label and format each section before LLM sees anything
    ├─ Annotate each item     [FRESH] / [STALE · Nd ago] / [SUPERSEDED] / [INACTIVE]
    ├─ Include date ranges    first_seen_at → last_seen_at per event
    └─ Tag stability scores   confidence signal for how well-supported each event is
      │
      ▼
 6. Vector supplement         ChromaDB (only when DB data is thin: <2 events AND <2 claims)
    ├─ Skipped if ≥5 nodes    structured DB already provided enough context
    ├─ Scoped by intent       archive mode → snapshots+artifacts+claims
    │                         timeline mode → snapshots+events+claims
    │                         current mode  → events+claims
    └─ Filters inactive       suppresses inactive/archived items unless archive mode
      │
      ▼
 7. Web search fallback       Tavily (only when both DB and vector return nothing)
    └─ Last resort            real-time web results labeled [Live web search results]
      │
      ▼
 8. Compose context           assemble final prompt context string (max 6000 chars)
    ├─ Topic preamble         "[Topic: <name>]"
    ├─ Article context        if user clicked "Ask AI" on a card (max 800 chars)
    ├─ === CURRENT STATE ===
    ├─ === RECENT EVOLUTION ===
    ├─ === HISTORICAL BACKGROUND ===
    └─ [SUPPLEMENTAL — ...]  vector/web results, clearly labeled
      │
      ▼
 9. Stream LLM answer         temperature=0.5; SSE token-by-token to frontend
    └─ Emit sources list      structured {id, title, url, type} for UI citation chips
```

### Intent Classification

The intent classifier is the routing brain of the pipeline. It runs a small, fast LLM call at temperature=0 to decide which DB layers to query. The output is a structured JSON:

```json
{
  "needs_current_state": true,
  "needs_timeline": false,
  "needs_archive": false,
  "time_window_days": 14,
  "reason": "user asking about current situation",
  "confidence": 0.85
}
```

If confidence < 0.40 or the LLM call fails, it falls back to a rule-based classifier using regex keyword matching (English and Chinese):

- Timeline keywords: `evolv`, `trend`, `changed`, `over time`, `变化`, `演变`, …
- Archive keywords: `history`, `origin`, `before`, `previous`, `历史`, `以前`, …

### Why DB-First, Not Vector-First

Most RAG systems query a vector store immediately. Domain Monitor inverts this for temporal accuracy:

1. **Vector embeddings don't encode time** — a vector search for "current China trade policy" may return a high-similarity match from 18 months ago with no indication it's stale
2. **SQLite knows exactly what is fresh** — claims have explicit `status` fields (fresh/stale/superseded) and validated timestamps; events have `first_seen_at` and `last_seen_at`
3. **Vector search is used as a gap-filler** — only activated when structured retrieval returns fewer than 5 nodes total, ensuring it supplements rather than dominates the context

---

## Context Engineering

The system does not simply dump raw documents into the prompt. Each layer of context goes through a deliberate formatting and labeling process before the LLM sees it.

### Section Headers & Priority Anchors

The assembled context uses named sections as explicit priority signals to the LLM:

```
=== CURRENT STATE ===          ← always answer from here first
=== RECENT EVOLUTION ===       ← add when it enriches the answer
=== HISTORICAL BACKGROUND ===  ← background only; never present as current fact
[SUPPLEMENTAL — ...]           ← vector/web fill; clearly secondary
```

The system prompt instructs the LLM to follow this exact hierarchy, and to explicitly surface conflicts rather than silently preferring one source over another.

### Freshness Labels

Every retrieved item is annotated inline with its temporal status before formatting:

```
[FRESH]                  actively supported by recent evidence
[STALE · 12d ago]        last signal 12 days ago; treat with caution
[SUPERSEDED]             a newer claim replaced this one
[INACTIVE · 45d ago]     no longer tracked; shown in archive only
[ARCHIVED]               resolved or irrelevant
```

This means the LLM cannot accidentally cite a superseded claim as current fact — the label is physically present in the context window.

### Event Date Ranges & Stability

Active events are formatted with their observation window and stability score:

```
1. [2026-03-15 → 2026-03-31] China expands overseas investment quotas (stability: 0.87)
   Summary text truncated to 240 chars...
```

The stability score (0–1) reflects how consistently the event has been covered across multiple source citations over time. High stability = well-confirmed; low stability = may be a single-source report.

### Timeline Ordering

When the timeline layer is activated, events are explicitly sorted **oldest → newest** before formatting. This forces the LLM to read history in chronological order, making trend and evolution questions significantly more accurate.

### Claim Evolution Log

The timeline layer also includes a claim evolution log — a chronological record of how individual claims have changed:

```
[Claim Evolution Signals]
  1. [2026-03-10] strengthened — New trade data confirms Q1 export growth
  2. [2026-03-18] weakened — PMI reading below expectations; growth narrative challenged
  3. [2026-03-25] superseded — New policy announcement invalidates earlier export claim
```

This gives the LLM an explicit change-log rather than requiring it to infer change from static snapshots.

### Snapshot Deltas

Each AI snapshot includes a `change_summary` delta against the previous snapshot, formatted as:

```
[Snapshot Deltas — What Changed]
  [2026-03-28] Regulatory tone shifted from restrictive to accommodative; 
               two new QFII quota expansions announced. Previous concerns 
               about capital outflow restrictions appear to have eased.
```

### Context Budget Management

The final context string is hard-capped at **6,000 characters** to stay within model context windows without sacrificing quality. The budget allocation priority is:

1. Topic preamble (topic name anchor)
2. Article context (if user triggered from a specific card) — max 800 chars
3. Current state section
4. Timeline section
5. Historical background section
6. Supplemental (vector/web) — appended last, truncated first if over budget

### Citation Protocol

The system prompt explicitly instructs the LLM to use `[Source Title]` syntax for inline citations — wrapping the exact title of a source document in square brackets. The frontend detects these tokens and renders them as interactive citation chips. Rules enforced in the prompt:

- Only wrap titles that appear verbatim in the provided context
- Do not wrap generic section labels like `[Current Claims]` or `[CURRENT STATE]`
- Do not invent titles
- Respond in the same language as the user's question

The frontend's citation renderer fuzzy-matches the LLM's `[Source Title]` tokens against the structured sources list (emitted as a separate SSE event) using normalized string comparison, then renders each match as either:
- An **internal navigation chip** (event/snapshot/artifact) — navigates to the item in the Overview panel
- An **external link chip** — opens the original article URL in a new tab
- A **passive chip** — displays the label without a link (knowledge-base items without a direct URL)

---

## Tech Stack

| Layer | Technology |
|---|---|
| **Frontend** | Next.js 16 (App Router), TailwindCSS v4, Zustand (persist), Framer Motion |
| **Backend** | Python FastAPI, APScheduler, Uvicorn |
| **AI / LLM** | OpenAI / Anthropic / LM Studio / DashScope (Qwen) — switchable via env |
| **Data Sources** | NewsAPI · Google News RSS · RSS Feeds · Event Registry · Tavily |
| **Storage** | SQLite (structured data + claim/event lifecycle) + ChromaDB (vector embeddings) |
| **Real-time** | Server-Sent Events (SSE) — article push and streaming chat responses |

---

## Quick Start

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

cp ../.env.example .env
# Edit .env with your API keys and LLM provider settings

python -m uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open [http://localhost:3000](http://localhost:3000)

### 3. Docker Compose

```bash
cp backend/.env.example backend/.env
# Edit backend/.env with your API keys and LLM provider settings

docker compose up --build
```

Open [http://localhost:3000](http://localhost:3000)

- The frontend proxies `/api/*` to the backend container automatically
- SQLite and ChromaDB data persist in the named Docker volume `backend_data`
- You usually do not need `NEXT_PUBLIC_API_BASE` for Docker or single-VM deployment

### 4. Usage

1. **Create a topic** on the homepage (e.g., "AI in Healthcare")
2. Go to the topic page; in the **Research Brief** panel (left), describe your research direction and click **Generate** — AI creates keywords, RSS feeds, research angles, key entities, and geographic/sector scope
3. Click **Fetch Now** in the header to immediately pull articles, or wait for the scheduled interval (default: every 15 min)
4. Browse the **Event feed** (middle column); right-click any article card for options: Pin for tracking / Archive / Delete / Change sentiment or importance
5. Check the **Realtime** tab (right panel) for live AI Analysis and Alert Signals; switch to **Overview** for the Global Overview, historical AI snapshots, and Knowledge Base articles
6. Click the chat icon (top right) to open the **AI Assistant** — ask questions about the domain; the system automatically decides which knowledge layers to use

---

## Environment Variables

Copy `backend/.env.example` to `backend/.env` and fill in the values you need.

`frontend/.env.example` documents optional public frontend variables. For Docker Compose and single-VM deployment, you can usually leave frontend variables unset and let Next.js proxy `/api/*` to the backend internally.

### LLM Provider

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` \| `anthropic` \| `lmstudio`（本机）\| `openai_compat`（第三方 OpenAI 兼容，如 ichonhui）\| `dashscope` | `openai` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OPENAI_MODEL` | OpenAI model name | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `ANTHROPIC_MODEL` | Anthropic model name | `claude-3-5-haiku-20241022` |
| `LMSTUDIO_BASE_URL` | 本机 LM Studio OpenAI 兼容 base（请求 `{URL}/chat/completions`） | `http://localhost:1234/v1` |
| `LMSTUDIO_MODEL` | LM Studio 模型 id | `local-model` |
| `LMSTUDIO_API_KEY` | LM Studio 用占位 key 即可 | `lm-studio` |
| `OPENAI_COMPAT_BASE_URL` | 第三方 OpenAI 兼容网关 base（如 ichonhui；非 LM Studio） | — |
| `OPENAI_COMPAT_MODEL` | 与网关 `GET /v1/models` 中 `id` 一致 | — |
| `OPENAI_COMPAT_API_KEY` | 网关 Bearer；可空则使用内置占位 | — |
| `DASHSCOPE_API_KEY` | Alibaba Cloud DashScope API key | — |
| `DASHSCOPE_MODEL` | DashScope model name | `qwen3.5-flash` |
| `DASHSCOPE_BASE_URL` | DashScope endpoint | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |

### Data Sources

| Variable | Description |
|---|---|
| `NEWSAPI_KEY` | NewsAPI.org key (free tier: 100 req/day) |
| `EVENT_REGISTRY_API_KEY` | newsapi.ai / Event Registry key |
| `TAVILY_API_KEY` | Tavily web search key (fallback / supplemental) |
| `GLOBAL_RSS_FEEDS` | Comma-separated RSS URLs applied to all topics |

### Pipeline Tuning

| Variable | Description | Default |
|---|---|---|
| `FETCH_INTERVAL_MINUTES` | Scheduled fetch interval in minutes | `15` |
| `MAX_RESULTS_PER_KEYWORD` | Articles fetched per keyword per source | `15` |
| `RELEVANCE_MIN_SCORE` | Minimum relevance score to keep an article | `0.05` |
| `DEDUP_THRESHOLD` | Semantic deduplication cosine threshold | `0.82` |

### Storage & Server

| Variable | Description | Default |
|---|---|---|
| `DATABASE_PATH` | SQLite database path | `./data/monitor.db` |
| `CHROMA_PERSIST_DIR` | ChromaDB persistence directory | `./data/chroma` |
| `CORS_ORIGINS` | Comma-separated allowed browser origins for direct API access | `http://localhost:3000` |
| `LOG_LEVEL` | Logging level (`DEBUG`/`INFO`/`WARNING`/`ERROR`) | `INFO` |

### Frontend

| Variable | Description | Default |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | Optional public backend API base URL; leave unset to use same-origin `/api` proxy | same-origin `/api` |
| `INTERNAL_API_BASE` | Docker build-time backend URL used by Next.js rewrites | `http://backend:8000` in Compose |

---

## Ubuntu VM Deployment

Default first-stage production path: run both containers on one Ubuntu host with Docker Compose, keep SQLite + ChromaDB in the Docker volume, and expose the frontend on port `3000`.

### 0. Cloud checklist (do this in the cloud console first)

- Create an **Ubuntu 22.04 or 24.04 LTS** VM (recommended: **2 vCPU / 4GB RAM / 40GB+** disk).
- Security group / firewall: allow inbound **TCP 22** (SSH) and **TCP 3000** (frontend).
- Do **not** expose **TCP 8000** publicly; the backend stays on the Docker network and is reached via the frontend `/api` proxy.
- For a **private** GitHub repo: add a read-only **Deploy key**, or clone with **HTTPS + PAT** (rotate tokens carefully).

### Optional: bootstrap script on the VM

After cloning the repo on the server, run from the repository root:

```bash
chmod +x scripts/cloud-vm-bootstrap.sh
./scripts/cloud-vm-bootstrap.sh
```

This installs Docker (if missing), copies `backend/.env.example` to `backend/.env` when needed, runs `docker compose up -d --build`, and prints basic smoke-check output. If Docker was just installed and you see permission errors, **log out and SSH back in**, then run the script again.

### 1. Prepare the server

```bash
sudo apt-get update
sudo apt-get install -y ca-certificates curl git
curl -fsSL https://get.docker.com | sh
sudo usermod -aG docker "$USER"
```

Reconnect to the server after the group change, then clone the repo.

### 2. Configure the app

```bash
git clone <your-repo-url>
cd Domain_Monitor
cp backend/.env.example backend/.env
```

Edit `backend/.env` with your real API keys and provider settings.

### 3. Start the stack

```bash
docker compose up -d --build
```

### 4. Verify

```bash
docker compose ps
docker compose logs -f backend
docker compose logs -f frontend
```

Then open `http://YOUR_SERVER_IP:3000`.

### 5. Persisted data

- SQLite database is stored in the Docker volume mounted at `/app/data/monitor.db`
- ChromaDB persistence directory is mounted at `/app/data/chroma`
- Recreating containers does not delete data unless you remove the `backend_data` volume

### 6. Optional hardening

- Put Nginx or Caddy in front of the frontend container for ports `80/443`
- Add HTTPS with Let's Encrypt before exposing the service publicly
- If you do not need direct API access, keep port `8000` internal-only as in the provided Compose file

---

## API Reference

### Topics

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/topics` | List all topics |
| `GET` | `/api/topics/overview` | List topics with article stats (`?hours=24`) |
| `POST` | `/api/topics` | Create topic |
| `PUT` | `/api/topics/{id}` | Update topic (name, color, research_brief, pipeline_config) |
| `DELETE` | `/api/topics/{id}` | Delete topic |
| `POST` | `/api/topics/{id}/generate-research-plan` | AI-generate research plan from brief |

### Keywords & RSS Feeds

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/keywords` | List keywords for a topic (`?topic_id=`) |
| `POST` | `/api/keywords` | Add keyword |
| `DELETE` | `/api/keywords/{id}` | Delete keyword |
| `GET` | `/api/topics/{id}/feeds` | List RSS feeds for a topic |
| `POST` | `/api/topics/{id}/feeds` | Add RSS feed |
| `DELETE` | `/api/feeds/{id}` | Delete RSS feed |

### Articles & Events

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/articles` | List articles (`topic_id`, `status`, `sort`, `limit`, `offset`) |
| `GET` | `/api/events` | List event clusters (`topic_id`, `status`, `sort`, `limit`, `offset`) |
| `GET` | `/api/events/{id}` | Get single event with alternative sources |
| `PUT` | `/api/articles/{id}` | Update article (sentiment, importance, status) |
| `PUT` | `/api/articles/{id}/keep` | Toggle Knowledge Base flag |
| `PUT` | `/api/articles/{id}/archive` | Archive article |
| `PUT` | `/api/articles/{id}/restore` | Restore article to Active |
| `DELETE` | `/api/articles/{id}` | Permanently delete article |
| `GET` | `/api/stream` | SSE stream for new article notifications |

### Fetch & Insights

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/fetch-now` | Trigger immediate fetch (`?topic_id=`) |
| `GET` | `/api/fetch-now/status` | Poll fetch status (`?topic_id=`) |
| `GET` | `/api/insights/summary` | Insight summary stats (`?topic_id=`, `?hours=`) |
| `GET` | `/api/insights/topic` | Detailed topic insights (`?topic_id=`, `?window=`) |
| `GET` | `/api/topics/{id}/trending` | Trending data for charts |

### AI Analysis

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/topics/{id}/ai-summary` | Get cached Realtime AI Analysis |
| `POST` | `/api/topics/{id}/ai-summary/generate` | Trigger AI Analysis regeneration |
| `GET` | `/api/topics/{id}/ai-summary/status` | Poll generation status |
| `GET` | `/api/topics/{id}/global-overview` | Get cached Global Overview content |
| `GET` | `/api/topics/{id}/synthesis/global-overview` | Get Global Overview synthesis artifact |
| `POST` | `/api/topics/{id}/synthesis/global-overview/generate` | Trigger Global Overview regeneration |
| `GET` | `/api/topics/{id}/synthesis/global-overview/status` | Poll generation status |
| `GET` | `/api/topics/{id}/synthesis/evolution-report` | Get Evolution synthesis artifact |
| `POST` | `/api/topics/{id}/synthesis/evolution-report/generate` | Trigger Evolution report regeneration |
| `GET` | `/api/topics/{id}/synthesis/evolution-report/status` | Poll Evolution generation status |

### Knowledge Base (Snapshots)

| Method | Path | Description |
|---|---|---|
| `GET` | `/api/topics/{id}/snapshots` | List historical AI snapshots |
| `PUT` | `/api/snapshots/{id}` | Update snapshot |
| `DELETE` | `/api/snapshots/{id}` | Delete snapshot |
| `GET` | `/api/topics/{id}/kept-articles` | List Knowledge Base articles |

### Chat

| Method | Path | Description |
|---|---|---|
| `POST` | `/api/chat` | Streaming AI chat — SSE response (`message`, `topic_id`, `article_context`, `history`) |

### Project Structure

```
Domain_Monitor/
├── .env.example
├── README.md
├── backend/
│   ├── main.py               # FastAPI app, all API routes
│   ├── config.py             # Pydantic settings (reads .env)
│   ├── database.py           # SQLite schema + CRUD helpers
│   ├── pipeline.py           # Multi-stage data pipeline orchestrator
│   ├── relevance.py          # TF-IDF dedup + keyword relevance scoring
│   ├── chatbot.py            # Multi-layer RAG chatbot (intent → DB → vector → LLM)
│   ├── topic_summary.py      # AI Analysis, Global Overview, claim tracking
│   ├── llm_client.py         # Unified LLM client (OpenAI-compat API)
│   ├── vector_store.py       # ChromaDB wrapper (upsert / query)
│   ├── scheduler.py          # APScheduler jobs (fetch + summary)
│   ├── sse_manager.py        # Server-Sent Events broadcast
│   ├── search_client.py      # Tavily search helper
│   ├── requirements.txt
│   ├── collectors/
│   │   ├── newsapi_collector.py
│   │   ├── googlenews_collector.py
│   │   ├── rss_collector.py
│   │   ├── eventregistry_collector.py
│   │   └── tavily_collector.py
│   └── data/
│       ├── monitor.db        # SQLite database
│       └── chroma/           # ChromaDB vector store
└── frontend/
    ├── src/
    │   ├── app/
    │   │   ├── page.tsx               # Homepage — topic cards
    │   │   ├── layout.tsx             # Root layout + ToastContainer
    │   │   └── topic/[id]/
    │   │       └── page.tsx           # Topic detail — 3-column layout
    │   ├── components/
    │   │   ├── TopicCard.tsx
    │   │   ├── TopicHeader.tsx
    │   │   ├── ResearchBriefPanel.tsx
    │   │   ├── EventFeed.tsx
    │   │   ├── EventCard.tsx
    │   │   ├── NewsCard.tsx
    │   │   ├── ArticleContextMenu.tsx
    │   │   ├── AnalysisPanel.tsx
    │   │   ├── MacroAnalysisPanel.tsx
    │   │   ├── ChatBot.tsx            # AI Assistant with RAG thinking bar
    │   │   └── ToastContainer.tsx
    │   ├── lib/
    │   │   ├── api/
    │   │   │   ├── index.ts
    │   │   │   ├── chat.ts            # streamChat — SSE parser for chat events
    │   │   │   └── types.ts           # ChatEvent, ChatTracePayload, ChatSource
    │   │   ├── constants.ts
    │   │   └── utils.ts
    │   └── stores/
    │       └── useStore.ts            # Zustand store (persists chat + UI state per topic)
    └── package.json
```
