import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const baseUrl = process.env.FRONTEND_SMOKE_API_BASE ?? "http://127.0.0.1:8000";
const topicId = Number(process.env.FRONTEND_SMOKE_TOPIC_ID ?? "11");

function ensure(condition, message) {
  if (!condition) throw new Error(message);
}

async function expectJson(path, assertFn) {
  const url = `${baseUrl}${path}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`${path} returned HTTP ${res.status}`);
  }
  const data = await res.json();
  await assertFn(data, path);
  return data;
}

async function checkStatusContracts() {
  const targets = [
    `/api/fetch-now/status?topic_id=${topicId}`,
    `/api/topics/${topicId}/ai-summary/status`,
    `/api/topics/${topicId}/synthesis/global-overview/status`,
    `/api/topics/${topicId}/synthesis/evolution-report/status`,
  ];

  for (const path of targets) {
    await expectJson(path, (data) => {
      ensure(typeof data === "object" && data !== null, `${path} must return object`);
      ensure("status" in data, `${path} must expose status`);
      ensure("error" in data, `${path} must expose error`);
      ensure("result_summary" in data, `${path} must expose result_summary`);
      ensure("finished_at" in data, `${path} must expose finished_at`);
    });
  }
}

async function checkActionWiring() {
  const checks = [
    ["src/stores/useStore.ts", "actionStates"],
    ["src/stores/useStore.ts", "task:fetch:"],
    ["src/stores/useStore.ts", "task:live-summary:"],
    ["src/stores/useStore.ts", "task:global-overview:"],
    ["src/components/TopicHeader.tsx", "task:fetch:"],
    ["src/components/AnalysisPanel.tsx", "task:live-summary:"],
    ["src/components/MacroAnalysisPanel.tsx", "task:global-overview:"],
    ["src/components/ArticleContextMenu.tsx", "runWithAction"],
    ["src/components/ResearchBriefPanel.tsx", "runWithAction"],
    ["src/components/TopicCard.tsx", "runWithAction"],
  ];

  for (const [file, marker] of checks) {
    const content = await readFile(resolve(file), "utf8");
    ensure(content.includes(marker), `${file} must include marker: ${marker}`);
  }
}

async function main() {
  await checkStatusContracts();
  await checkActionWiring();
  console.log(JSON.stringify({
    status: "ok",
    topicId,
    checks: ["status-contracts", "action-wiring-markers"],
  }, null, 2));
}

main().catch((error) => {
  console.error(JSON.stringify({
    status: "error",
    topicId,
    message: error instanceof Error ? error.message : String(error),
  }, null, 2));
  process.exit(1);
});
