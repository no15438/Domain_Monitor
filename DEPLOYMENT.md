# English release deployment

The user authorized publication on 2026-11-17. The target is the existing Render workspace and public GitHub repository `no15438/Domain_Monitor`, using `main` without a force push.

## Services

| Component | Configuration |
| --- | --- |
| Backend | Existing `Domain_Monitor`, service `srv-d77quoqa214c73dhicm0`, Ohio, free Docker service; repository-root build context; `backend/Dockerfile`; `uvicorn app:app --host 0.0.0.0 --port 10000`. URL: `https://domain-monitor-uf81.onrender.com`. |
| Frontend | `domain-monitor-frontend-no15438`, service `srv-dbu39kjm8hqs73e0b6f0`, Ohio, free Docker service; root `frontend`, `Dockerfile`, `node server.js`, port 10000. URL: `https://domain-monitor-frontend-no15438-yf92.onrender.com`. `INTERNAL_API_BASE=https://domain-monitor-uf81.onrender.com` must be set during the Docker build as well as runtime, because Next.js builds proxy rewrites into the output. |

No API credentials were present in the old Render service. External calls and scheduling stay disabled for this acceptance deployment. Do not upload local configuration or private databases implicitly. Host/origin restrictions do not provide authentication; do not put private documents into this public acceptance instance.

The free backend uses ephemeral storage under `/tmp/domain-monitor`. This is an online acceptance deployment, not durable production storage: inactivity can delay startup and restarts/redeploys can lose records. No paid disk or plan has been purchased. Persistent production use requires an explicitly chosen durable host/storage configuration.

## English scope and local checks

- English interface, accessibility labels, dates, errors, original offline interface, synthetic fixtures, setup comments, and project documentation.
- English generation instructions at both regular and streamed model boundaries and in each analysis prompt. Original source text, quotes, user data, identifiers, and stored historical evidence remain unchanged.
- English fixtures use new IDs/source keys to avoid rewriting older immutable demo evidence.
- **218 Python tests passed**, including five new mocked provider/Render-host regressions. Three pre-existing fixture warnings remain.
- **20 frontend behavior checks passed**, including late topic/save responses, historical read-only controls, chat state, and API retries/errors.
- Frontend production build with webpack passed TypeScript and all five routes. The Dockerfile uses that tested build mode.
- No real model/news calls were made. Provider instruction delivery is tested with mocks; actual provider availability and compliance remain unverified.

Online service status, final commit, and browser acceptance evidence will be appended after the rollout is observed.

Both Docker services reached Live at application commit `9225fd63c29825efb6654f362075a656c09cca1f`. Backend health is `/health`; the frontend proxy returned event-memory health and runtime configuration successfully. Render assigned a suffix to the frontend URL, so its actual origin is reflected in `CORS_ORIGINS` and `render.yaml`. The services were configured directly in the dashboard; they are not linked to a Blueprint. A completed settings rollout actually cleared the first synthetic acceptance topic, confirming the ephemeral-storage limitation rather than restart durability. Final functional acceptance is recorded in `artifacts/deployment-verification.json` and browser screenshots when complete.

## Final online acceptance

Both services are Live at application commit `9225fd6`. All **27 real online API checks passed** through the frontend proxy, using only synthetic data: runtime boundaries, workspace APIs, event writes with the assigned frontend origin, transition/correction projection, effective and known-by cutoffs, topic isolation, cache policy, archive/recall/restore, immutable evidence history, and rejection of an untrusted origin. A first validation assertion was corrected to distinguish `body_sha256` metadata from the excluded `body` field; the completed run checks the actual field contract.

Browser acceptance confirmed English topic creation, workspace navigation, chat failure releasing loading while retaining input, current Completed state, January Announced state, historical read-only controls, English evidence/policy history, and return to the current view. The synthetic topic and event remain available until the free instance restarts. No model/news requests were made. See `artifacts/deployment-verification.json` and the four `deployment-*.jpg` screenshots listed there.

Only deployment configuration, documentation, and acceptance artifacts changed after the running application commit; `main` contains those records as well. The dashboard-managed services are not linked to a Blueprint. A future release must trigger and verify each service's deployment rather than assume a `render.yaml` edit is applied automatically.

## Browser-independent date language

Screenshot review found that native date controls used the operating system's Chinese placeholders despite the English document language. Both event-memory interfaces now use the explicit English format `YYYY-MM-DD HH:mm` in local time. Invalid formats, impossible calendar dates, and nonexistent local times are rejected before requesting a projection. The React regression harness adds two cases for invalid format/calendar dates, increasing frontend behavior checks to 20. Singular event/evidence counts also use correct English grammar. The frontend is redeployed for this change; backend behavior remains at `9225fd6`.

The final frontend rollout is Live at `6c8efacf157125556b9ba6840abcd1194a04d7b4` (deploy `dep-dbu3jj8u01pc73diqj00`); the backend remains Live at `9225fd6`. On the updated public page, an impossible February 30 date produced an English error without changing the current projection, January 15 noon reconstructed the Announced state with read-only policy controls, and Back to now restored Completed. The refreshed screenshots show English date placeholders and correct singular counts. Post-rollout checks also confirmed the English HTML, runtime proxy, and preserved event projection. The synthetic records were not deleted or migrated. The 27 backend/API checks remain applicable; the final frontend was additionally checked as described here rather than treating its newer commit as a backend redeployment.
