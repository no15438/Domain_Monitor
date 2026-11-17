# Branch management

The integrated event workflow is developed on the new branch `feat/event-memory-workflow`, created from `feat/event-memory-v1` at `9ca4a2e`. It preserves the earlier event engine and Spark deployment work. The outcome-led review is in `DESIGN_REVIEW.md`; implementation scope is in `WORKFLOW_IMPLEMENTATION.md`. Production data, credentials and generated verification evidence remain outside source commits.

The previous deployment branch's seven commits were fast-forwarded into `main` at `2529f3f023a0a411c3b749d462eb9e29f610a826`. Before the English deployment work, GitHub had only `main` and the event-memory worktree was on `feat/event-memory-v1` at `b9d8405`.

The event work was developed in an isolated worktree to preserve the original checkout's uncommitted README and local data. That worktree is attached to the current Codex chat. Attaching it did not move the directory or change the sidebar project's root.

The previously redundant local branches `deploy`, `feat/knowledge-lineage-refactor`, `feat/topic-mobile-research-news-20260404`, and `feat/render-blueprint-deploy`, plus the remote deployment branch, were already cleaned up before this deployment task. The earlier read-only inventory remains in `artifacts/branch-audit.json`; it is a historical snapshot, not the current branch list.

The integrated commits include mobile topic workspaces, the Render deployment configuration and startup command, OpenAI-compatible model routing, chat persistence/Markdown tables, and topic-switch state cleanup. They are ancestors of the event-memory work rather than unrelated changes to discard.

Use `main` for published code and short-lived feature/fix branches for new work. Publish with a normal fast-forward push after checking the remote head; never force-push. Preserve local databases, credentials, and the original checkout's README. Generated evidence, databases, environment files, and local dependencies must stay out of commits and container build contexts.

The current deployment is explicitly authorized by the user. Deployment status and its tested commit are recorded separately in `DEPLOYMENT.md` after verification.
