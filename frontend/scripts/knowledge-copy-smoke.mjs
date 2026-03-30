import { readFile } from "node:fs/promises";
import { resolve } from "node:path";

const files = [
  "src/components/MacroAnalysisPanel.tsx",
  "src/components/EvolutionPanel.tsx",
  "src/components/EventCard.tsx",
  "src/components/NewsCard.tsx",
  "src/components/ArticleContextMenu.tsx",
  "src/components/AnalysisPanel.tsx",
  "src/components/EventFeed.tsx",
];

const bannedTerms = [
  "Promote to Evidence",
  "validated ",
  "validated{",
  "validated",
  "EVD",
];

async function main() {
  const failures = [];
  for (const relativePath of files) {
    const content = await readFile(resolve(relativePath), "utf8");
    for (const banned of bannedTerms) {
      if (content.includes(banned)) {
        failures.push(`${relativePath} still contains banned copy: ${banned}`);
      }
    }
  }

  if (failures.length > 0) {
    console.error(JSON.stringify({ status: "error", failures }, null, 2));
    process.exit(1);
  }

  console.log(JSON.stringify({ status: "ok", checkedFiles: files }, null, 2));
}

main().catch((error) => {
  console.error(JSON.stringify({
    status: "error",
    message: error instanceof Error ? error.message : String(error),
  }, null, 2));
  process.exit(1);
});
