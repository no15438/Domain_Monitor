# Domain Monitor — AI-Powered Industry Intelligence

Real-time industry monitoring system powered by AI. Automatically fetches, deduplicates, clusters, summarizes, and categorizes industry news from multiple sources. Includes a RAG-powered AI chatbot for interactive exploration.

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Scheduled / Manual Fetch                                       │
│    ↓                                                            │
│  Stage 1 — Recall: NewsAPI · Google News RSS · RSS Feeds ·     │
│            Event Registry · Tavily                             │
│    ↓                                                            │
│  Stage 2 — Precision: URL dedup → Semantic dedup (TF-IDF) →   │
│            Keyword relevance → Event clustering →              │
│            Canonical selection (authority + coverage score)    │
│    ↓                                                            │
│  Stage 3 — Enrich: LLM batch summarize / tag / sentiment /    │
│            importance / topic analysis (canonical only)        │
│    ↓                                                            │
│  Stage 4 — Store: SQLite + ChromaDB vector store               │
│    ↓                                                            │
│  SSE Push → Frontend                                           │
├─────────────────────────────────────────────────────────────────┤
│  Frontend (Next.js App Router)                                  │
│    Homepage: Topic cards (create / rename / delete)            │
│    Topic page: 3-column layout                                 │
│      Left:   Research Brief (AI-generated plan, CRUD)          │
│      Middle: Event feed (right-click context menu)             │
│      Right:  Analysis Panel                                    │
│                Realtime tab: AI Analysis + Signals             │
│                Overview tab: Global Overview + Snapshots +     │
│                             Core Articles + Macro Signals      │
│    AI Chatbot (RAG: articles + snapshots + global overview)    │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer     | Technology                                              |
|-----------|---------------------------------------------------------|
| Frontend  | Next.js 15, TailwindCSS v4, Zustand (persist), Framer Motion |
| Backend   | Python FastAPI, APScheduler, Uvicorn                   |
| AI        | OpenAI / LM Studio / DashScope (Qwen) — switchable via env |
| Data      | NewsAPI · Google News RSS · RSS Feeds · Event Registry · Tavily |
| Storage   | SQLite + ChromaDB (vector / RAG)                       |
| Real-time | Server-Sent Events (SSE)                               |

## Project Structure

```
Domain_Monitor/
├── .env.example              # Root-level env template (copy to backend/.env)
├── README.md
├── backend/
│   ├── main.py               # FastAPI app, all API routes
│   ├── config.py             # Pydantic settings (reads .env)
│   ├── database.py           # SQLite schema + CRUD helpers
│   ├── pipeline.py           # Multi-stage data pipeline orchestrator
│   ├── relevance.py          # TF-IDF dedup + keyword relevance scoring
│   ├── chatbot.py            # RAG chatbot (hybrid search + LLM streaming)
│   ├── topic_summary.py      # AI Analysis & Global Overview generation
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
    │   │   ├── TopicCard.tsx          # Homepage topic card (inline rename/delete)
    │   │   ├── TopicHeader.tsx        # Topic page header (Fetch Now, fetch status)
    │   │   ├── ResearchBriefPanel.tsx # Left panel — AI research plan + CRUD
    │   │   ├── EventFeed.tsx          # Middle panel — article/event list
    │   │   ├── EventCard.tsx          # Event cluster card (right-click menu)
    │   │   ├── NewsCard.tsx           # Single-article card
    │   │   ├── ArticleContextMenu.tsx # Right-click portal menu
    │   │   ├── AnalysisPanel.tsx      # Right panel — Realtime / Overview tabs
    │   │   ├── ChatBot.tsx            # AI Assistant panel
    │   │   └── ToastContainer.tsx     # Toast notifications
    │   ├── lib/
    │   │   ├── api.ts         # Typed API client (fetchWithRetry, streamChat, …)
    │   │   ├── constants.ts   # Shared constants (colors, thresholds, timings)
    │   │   └── utils.ts       # Helpers (effectiveImportance, timeAgo, parseTags)
    │   └── stores/
    │       └── useStore.ts    # Zustand store (persists chat history per topic)
    └── package.json
```

## Quick Start

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
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

### 3. Usage

1. **Create a topic** on the homepage (e.g., "AI in Healthcare")
2. Go to the topic page; in the **Research Brief** panel (left), describe your research direction and click **Generate** — AI creates keywords, RSS feeds, research angles, key entities, and geographic/sector scope
3. Click **Fetch Now** in the header to immediately pull articles, or wait for the scheduled interval (default: every 15 min)
4. Browse the **Event feed** (middle column); right-click any article card for options: Pin for tracking / Archive / Delete / Change sentiment or importance
5. Check the **Realtime** tab (right panel) for live AI Analysis and Alert Signals; switch to **Overview** for the Global Overview, historical AI snapshots, and Knowledge Base articles
6. Click the chat icon (top right) to open the **AI Assistant** — this replaces the right panel while open; ask questions using RAG over stored articles, snapshots, and the Global Overview

---

## Environment Variables

Copy `.env.example` to `backend/.env` and fill in the values you need.

### LLM Provider

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` \| `anthropic` \| `lmstudio` \| `dashscope` | `openai` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OPENAI_MODEL` | OpenAI model name | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `ANTHROPIC_MODEL` | Anthropic model name | `claude-3-5-haiku-20241022` |
| `LMSTUDIO_BASE_URL` | LM Studio server URL | `http://localhost:1234/v1` |
| `LMSTUDIO_MODEL` | LM Studio model identifier | `local-model` |
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
| `CORS_ORIGINS` | Comma-separated allowed CORS origins | `http://localhost:3000` |
| `LOG_LEVEL` | Logging level (`DEBUG`/`INFO`/`WARNING`/`ERROR`) | `INFO` |

### Frontend

| Variable | Description | Default |
|---|---|---|
| `NEXT_PUBLIC_API_BASE` | Backend API base URL | `http://localhost:8000` |

---

## Article Lifecycle

Articles progress through states managed via the right-click context menu:

| State | Description |
|---|---|
| **Active** | Visible in the main event feed |
| **Knowledge Base** | Important/bookmarked articles; appear in Overview → Core Articles |
| **Archived** | Hidden from main feed; shown in a collapsible section at the bottom |
| **Deleted** | Permanently removed from the database |

Importance scores apply **time decay** (exponential) — articles older than ~7 days gradually lose importance for sorting/display, reflecting recency relevance.

---

## AI Features

### Research Brief
Natural-language research direction → AI generates a structured plan including keywords, RSS feeds, research angles, key entities, and geographic/sector scope. All generated items are user-editable (CRUD).

### Data Pipeline
Multi-stage recall-then-precision pipeline:
1. **Collect** — parallel fetching from NewsAPI, Google News RSS, user RSS feeds, Event Registry, Tavily
2. **URL dedup** — normalize URLs and drop exact duplicates
3. **Semantic dedup** — TF-IDF cosine similarity; keeps the most authoritative source per near-duplicate cluster
4. **Relevance filter** — three-tier keyword matching (exact phrase → space-collapsed → any-word); configurable threshold
5. **Event clustering** — group semantically similar articles into events
6. **Canonical selection** — score each source by authority signals + coverage; pick the best representative
7. **LLM enrichment** — batch call to generate summary, tags, sentiment, importance (1–10), and topic-specific analysis for canonical articles only

### AI Analysis (Realtime Tab)
LLM-generated narrative summary for the topic, cached and updated on demand or on schedule. Includes Notable Signals and Outlook sections.
Time-window metrics in Signals are computed on article timeline time: `published_at` first, and fallback to `created_at` when publish time is missing.
Long-form analysis now supports `cite` buttons for both article/event references:
- article cite button -> opens original article URL
- event cite button -> opens event canonical source URL
- hover displays source title; no citation data gracefully falls back to plain markdown text

### Global Overview (Overview Tab)
Long-term macro analysis synthesized from historical AI snapshots. Covers domain evolution, key entities, persistent themes, and trend trajectory.
Narrative evolution (event turnover + claim strengthening/weakening/superseding) is merged into existing overview/evolution text output, not a separate narrative panel.

### AI Assistant (Chatbot)
RAG-powered chat with:
- **Article context** — clicking "Ask AI" on a card pre-loads that article's full metadata and content
- **Vector search** — hybrid retrieval from ChromaDB (articles + snapshots) using the query + article title as the search key
- **Global Overview injection** — macro analysis always injected into system prompt
- **Multi-turn history** — last 8 messages passed to the LLM for conversational continuity
- **Per-topic persistence** — chat history saved to `localStorage` per topic

---

## Alert Signals

The Realtime tab shows automated alert signals based on:

| Signal | Threshold |
|---|---|
| High negative sentiment | ≥ 40% of recent articles are negative |
| Elevated negative sentiment | ≥ 30% of recent articles are negative |
| Volume surge | Current period articles ≥ 100% more than previous period |
| High important article density | ≥ 40% of articles with importance score ≥ 8 |

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
| `GET` | `/api/topics/{id}/synthesis/global-overview/status` | Poll generation status (includes error/result fields) |
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
