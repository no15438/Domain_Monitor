# English release deployment

The user authorized publication on 2026-11-17. The target is the existing Render workspace and public GitHub repository `no15438/Domain_Monitor`, using `main` without a force push.

## Services

| Component | Configuration |
| --- | --- |
| Backend | Existing `Domain_Monitor`, service `srv-d77quoqa214c73dhicm0`, Ohio, free Docker service; repository-root build context; `backend/Dockerfile`; `uvicorn app:app --host 0.0.0.0 --port 10000`. URL: `https://domain-monitor-uf81.onrender.com`. |
| Frontend | `domain-monitor-frontend-no15438`, Ohio, free Docker service; root `frontend`, `Dockerfile`, `node server.js`, port 10000. `INTERNAL_API_BASE=https://domain-monitor-uf81.onrender.com` must be set during the Docker build as well as runtime, because Next.js builds proxy rewrites into the output. |

No API credentials were present in the old Render service. External calls and scheduling stay disabled for this acceptance deployment. Do not upload local configuration or private databases implicitly. Host/origin restrictions do not provide authentication; do not put private documents into this public acceptance instance.

The free backend uses ephemeral storage under `/tmp/domain-monitor`. This is an online acceptance deployment, not durable production storage: inactivity can delay startup and restarts/redeploys can lose records. No paid disk or plan has been purchased. Persistent production use requires an explicitly chosen durable host/storage configuration.

## English scope and local checks

- English interface, accessibility labels, dates, errors, original offline interface, synthetic fixtures, setup comments, and project documentation.
- English generation instructions at both regular and streamed model boundaries and in each analysis prompt. Original source text, quotes, user data, identifiers, and stored historical evidence remain unchanged.
- English fixtures use new IDs/source keys to avoid rewriting older immutable demo evidence.
- **218 Python tests passed**, including five new mocked provider/Render-host regressions. Three pre-existing fixture warnings remain.
- **18 frontend behavior checks passed**, including late topic/save responses, historical read-only controls, chat state, and API retries/errors.
- Frontend production build with webpack passed TypeScript and all five routes. The Dockerfile uses that tested build mode.
- No real model/news calls were made. Provider instruction delivery is tested with mocks; actual provider availability and compliance remain unverified.

Online service status, final commit, and browser acceptance evidence will be appended after the rollout is observed.
