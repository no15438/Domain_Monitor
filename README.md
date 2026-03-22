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
│      Left: Research Brief (AI-generated plan, CRUD)            │
│      Middle: Event feed (right-click context menu)             │
│      Right: Analysis Panel                                     │
│        Realtime tab: Live Insights + AI Analysis               │
│        Overview tab: Historical Snapshots + Core Articles      │
│    AI Chatbot (RAG over articles + snapshots)                  │
└─────────────────────────────────────────────────────────────────┘
```

## Tech Stack

| Layer     | Technology                                              |
|-----------|---------------------------------------------------------|
| Frontend  | Next.js 15, TailwindCSS v4, Zustand, Framer Motion     |
| Backend   | Python FastAPI, APScheduler, Uvicorn                   |
| AI        | OpenAI / Anthropic / LM Studio / DashScope (switchable)|
| Data      | NewsAPI · Google News RSS · RSS Feeds · Event Registry |
| Storage   | SQLite + ChromaDB (vector / RAG)                       |
| Real-time | Server-Sent Events (SSE)                               |

## Quick Start

### 1. Backend

```bash
cd backend
python -m venv venv
source venv/bin/activate   # Windows: venv\Scripts\activate
pip install -r requirements.txt

# Configure environment
cp ../.env.example .env
# Edit .env with your API keys and LLM provider

uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

Open http://localhost:3000

### 3. Usage

1. **Create a topic** on the homepage (e.g., "AI in Healthcare")
2. Go to the topic page; in the **Research Brief** panel, type a research direction and click "Generate Plan" — AI creates keywords, RSS feeds, angles, and scope
3. Click **Fetch Now** in the header to immediately pull articles, or wait for the scheduled interval
4. Browse the **Event feed** (middle column); right-click any article for sentiment, importance, bookmark, archive, or delete
5. Check the **Realtime** tab for live insights and **AI Analysis**; switch to **Overview** for historical snapshots and Knowledge Base articles
6. Open the **AI Assistant** (chat icon, top right) to ask questions about the topic using RAG over stored articles and snapshots

## Environment Variables

Copy `.env.example` to `backend/.env` and fill in the values you need.

| Variable | Description | Default |
|---|---|---|
| `LLM_PROVIDER` | `openai` \| `anthropic` \| `lmstudio` \| `dashscope` | `lmstudio` |
| `OPENAI_API_KEY` | OpenAI API key | — |
| `OPENAI_MODEL` | OpenAI model name | `gpt-4o-mini` |
| `ANTHROPIC_API_KEY` | Anthropic API key | — |
| `ANTHROPIC_MODEL` | Anthropic model name | `claude-3-5-haiku-20241022` |
| `LMSTUDIO_BASE_URL` | LM Studio server URL | `http://localhost:1234/v1` |
| `LMSTUDIO_MODEL` | LM Studio model identifier | `local-model` |
| `DASHSCOPE_API_KEY` | Alibaba Cloud DashScope API key | — |
| `DASHSCOPE_MODEL` | DashScope model name | `qwen-plus` |
| `DASHSCOPE_BASE_URL` | DashScope endpoint (intl or CN) | `https://dashscope-intl.aliyuncs.com/compatible-mode/v1` |
| `TAVILY_API_KEY` | Tavily web search API key | — |
| `NEWSAPI_KEY` | NewsAPI.org key (free tier available) | — |
| `EVENT_REGISTRY_API_KEY` | newsapi.ai / Event Registry key | — |
| `GLOBAL_RSS_FEEDS` | Comma-separated RSS feed URLs | — |
| `FETCH_INTERVAL_MINUTES` | Scheduled fetch interval | `15` |
| `MAX_RESULTS_PER_KEYWORD` | Articles pulled per keyword | `15` |
| `DATABASE_PATH` | SQLite database path | `./data/monitor.db` |
| `CHROMA_PERSIST_DIR` | ChromaDB persistence directory | `./data/chroma` |
| `CORS_ORIGINS` | Comma-separated allowed CORS origins | `http://localhost:3000` |
| `LOG_LEVEL` | Logging level (`DEBUG`/`INFO`/`WARNING`/`ERROR`) | `INFO` |
| `NEXT_PUBLIC_API_BASE` | Frontend: backend API base URL | `http://localhost:8000` |

## Article Lifecycle

Articles progress through states managed via the right-click context menu:

- **Active** — visible in the main feed
- **Archived** — hidden from main feed; collapsible "N archived" section at the bottom of each feed
- **Knowledge Base** — articles marked Important (importance ≥ 6 after time decay) or Bookmarked appear in the Overview tab's "Core Articles" section
- **Deleted** — permanently removed from the database

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/health` | Health check |
| `GET` | `/api/topics` | List all topics |
| `POST` | `/api/topics` | Create topic |
| `PUT` | `/api/topics/{id}` | Update topic |
| `DELETE` | `/api/topics/{id}` | Delete topic |
| `GET` | `/api/events` | List event clusters (supports `status`, `sort`, `limit`, `offset`) |
| `GET` | `/api/articles` | List articles (supports `status`, `sort`, `limit`, `offset`) |
| `PUT` | `/api/articles/{id}/archive` | Archive article |
| `PUT` | `/api/articles/{id}/restore` | Restore article |
| `DELETE` | `/api/articles/{id}` | Delete article |
| `POST` | `/api/fetch-now` | Trigger immediate fetch |
| `GET` | `/api/topics/{id}/ai-summary` | Get cached AI analysis |
| `POST` | `/api/topics/{id}/ai-summary/generate` | Trigger AI analysis generation |
| `GET` | `/api/insights/summary` | Get insight summary stats |
| `POST` | `/api/chat` | Streaming AI chat (SSE) |
