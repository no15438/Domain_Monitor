const baseUrl = process.env.FRONTEND_SMOKE_API_BASE ?? "http://127.0.0.1:8000";
const topicId = Number(process.env.FRONTEND_SMOKE_TOPIC_ID ?? "11");

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

function ensure(condition, message) {
  if (!condition) throw new Error(message);
}

async function main() {
  await expectJson("/api/topics", (data, path) => {
    ensure(Array.isArray(data.topics), `${path} must return topics[]`);
  });

  await expectJson("/api/topics/archived/overview?hours=24", (data, path) => {
    ensure(Array.isArray(data.topics), `${path} must return topics[]`);
  });

  await expectJson(`/api/topics/${topicId}/claims`, (data, path) => {
    ensure(Array.isArray(data.claims), `${path} must return claims[]`);
    if (data.claims.length > 0) {
      const claim = data.claims[0];
      ensure(
        typeof claim.last_refreshed_at === "string" || claim.last_refreshed_at == null,
        `${path} must expose last_refreshed_at`,
      );
      ensure(
        typeof claim.claim_kind === "string" || claim.claim_kind == null,
        `${path} must expose claim_kind`,
      );
    }
  });

  await expectJson(`/api/topics/${topicId}/evidence`, (data, path) => {
    ensure(Array.isArray(data.evidence), `${path} must return evidence[]`);
    if (data.evidence.length > 0) {
      const evidence = data.evidence[0];
      ensure(
        typeof evidence.support_score === "number" || evidence.support_score == null,
        `${path} must expose support_score`,
      );
    }
  });

  await expectJson(`/api/topics/${topicId}/snapshots?window=daily`, (data, path) => {
    ensure(Array.isArray(data), `${path} must return snapshot array`);
  });

  await expectJson(`/api/topics/${topicId}/snapshot-deltas`, (data, path) => {
    ensure(Array.isArray(data.deltas), `${path} must return deltas[]`);
  });

  await expectJson(`/api/topics/${topicId}/claim-lifecycle-audit`, (data, path) => {
    ensure(Array.isArray(data.audit), `${path} must return audit[]`);
  });

  await expectJson(`/api/topics/${topicId}/synthesis/global-overview`, (data, path) => {
    ensure(
      data.artifact == null || typeof data.artifact.content === "string",
      `${path} must return artifact.content string or null`,
    );
  });

  await expectJson(`/api/topics/${topicId}/synthesis/evolution-report`, (data, path) => {
    ensure(
      data.artifact == null || typeof data.artifact.content === "string",
      `${path} must return artifact.content string or null`,
    );
  });

  console.log(
    JSON.stringify(
      {
        status: "ok",
        baseUrl,
        topicId,
        checks: [
          "topics",
          "archived-topics-overview",
          "claims",
          "evidence",
          "snapshots",
          "snapshot-deltas",
          "claim-lifecycle-audit",
          "global-overview",
          "evolution-report",
        ],
      },
      null,
      2,
    ),
  );
}

main().catch((error) => {
  console.error(
    JSON.stringify(
      {
        status: "error",
        baseUrl,
        topicId,
        message: error instanceof Error ? error.message : String(error),
      },
      null,
      2,
    ),
  );
  process.exit(1);
});
