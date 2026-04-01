"use client";

import { Fragment } from "react";
import type { AnalysisCitation } from "@/lib/api";

/** Matches inline citation markers like [E1], [A2], [E12] and pseudo-citations like [Claim-12], [Event-7] */
const INLINE_RE = /\*\*(.+?)\*\*|\*([^*\n]+?)\*|\[([EA]\d+)\]|\[(Claim|Event|Evidence|Evolution)\s*[-–—]\s*(\d+)\]/gi;

function renderInline(
  text: string,
  citationMap: Map<string, AnalysisCitation>,
  keyPrefix: string,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  const re = new RegExp(INLINE_RE.source, "g");
  let match: RegExpExecArray | null;

  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }

    if (match[1] !== undefined) {
      // **bold**
      parts.push(<strong key={`${keyPrefix}-b${match.index}`}>{match[1]}</strong>);
    } else if (match[2] !== undefined) {
      // *italic*
      parts.push(<em key={`${keyPrefix}-i${match.index}`}>{match[2]}</em>);
    } else if (match[3] !== undefined) {
      // [E1] or [A2] catalog citation
      const id = match[3].toUpperCase();
      const c = citationMap.get(id);
      if (c) {
        parts.push(
          <a
            key={`${keyPrefix}-c${match.index}`}
            href={c.url}
            target="_blank"
            rel="noreferrer"
            title={c.title}
            className="inline-flex items-center rounded border border-accent/40 bg-accent/5 px-1 py-px text-[9px] font-medium text-accent/90 hover:bg-accent/15 hover:text-accent transition-colors mx-0.5 no-underline align-baseline"
            onClick={(e) => e.stopPropagation()}
          >
            {id}
          </a>,
        );
      } else {
        parts.push(match[0]);
      }
    } else if (match[4] !== undefined) {
      // [Claim-12] / [Event-7] / [Evidence-3] / [Evolution-2] pseudo-citation from old artifacts
      // Downgrade to plain readable text with no brackets so it doesn't look like a broken button
      const kind = match[4].charAt(0).toUpperCase() + match[4].slice(1).toLowerCase();
      const num = match[5];
      parts.push(`${kind} ${num}`);
    }

    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length ? parts : [text];
}

function renderBlocks(
  content: string,
  citationMap: Map<string, AnalysisCitation>,
): React.ReactNode[] {
  const lines = content.split("\n");
  const blocks: React.ReactNode[] = [];
  let listItems: React.ReactNode[] = [];
  let listOrdered = false;
  let paraLines: string[] = [];
  let tableRows: string[][] = [];
  let key = 0;

  const flushPara = () => {
    if (paraLines.length === 0) return;
    const text = paraLines.join(" ").trim();
    if (text) {
      blocks.push(
        <p key={key++}>
          {renderInline(text, citationMap, `p${key}`).map((n, i) => (
            <Fragment key={i}>{n}</Fragment>
          ))}
        </p>,
      );
    }
    paraLines = [];
  };

  const flushList = () => {
    if (listItems.length === 0) return;
    if (listOrdered) {
      blocks.push(<ol key={key++}>{listItems}</ol>);
    } else {
      blocks.push(<ul key={key++}>{listItems}</ul>);
    }
    listItems = [];
  };

  const flushTable = () => {
    if (tableRows.length === 0) return;
    // Detect separator row (e.g. :--- / --- / :-:) to identify the header
    const sepIdx = tableRows.findIndex((row) =>
      row.length > 0 && row.every((c) => /^:?-+:?$/.test(c.trim())),
    );
    const headerRow = sepIdx === 1 ? tableRows[0] : null;
    const bodyRows = headerRow ? tableRows.slice(2) : tableRows.filter((_, i) => i !== sepIdx);
    const tableKey = key++;
    blocks.push(
      <table key={tableKey}>
        {headerRow && (
          <thead>
            <tr>
              {headerRow.map((cell, i) => (
                <th key={i}>
                  {renderInline(cell.trim(), citationMap, `th${tableKey}-${i}`).map((n, j) => (
                    <Fragment key={j}>{n}</Fragment>
                  ))}
                </th>
              ))}
            </tr>
          </thead>
        )}
        <tbody>
          {bodyRows.map((row, ri) => (
            <tr key={ri}>
              {row.map((cell, ci) => (
                <td key={ci}>
                  {renderInline(cell.trim(), citationMap, `td${tableKey}-${ri}-${ci}`).map((n, j) => (
                    <Fragment key={j}>{n}</Fragment>
                  ))}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>,
    );
    tableRows = [];
  };

  for (const rawLine of lines) {
    const line = rawLine.trimEnd();
    const trimmed = line.trim();

    if (!trimmed) {
      flushList();
      flushTable();
      flushPara();
      continue;
    }

    // Headings: ## ... or ### ...
    const headingMatch = trimmed.match(/^(#{1,6})\s+(.+)$/);
    if (headingMatch) {
      flushList();
      flushTable();
      flushPara();
      const level = headingMatch[1].length;
      const headingText = headingMatch[2];
      const inlineContent = renderInline(headingText, citationMap, `h${level}-${key}`).map(
        (n, i) => <Fragment key={i}>{n}</Fragment>,
      );
      switch (level) {
        case 1: blocks.push(<h1 key={key++}>{inlineContent}</h1>); break;
        case 2: blocks.push(<h2 key={key++}>{inlineContent}</h2>); break;
        case 3: blocks.push(<h3 key={key++}>{inlineContent}</h3>); break;
        default: blocks.push(<h4 key={key++}>{inlineContent}</h4>); break;
      }
      continue;
    }

    // Table row: line starts and ends with |
    if (trimmed.startsWith("|") && trimmed.endsWith("|")) {
      flushPara();
      flushList();
      const cells = trimmed.slice(1, -1).split("|");
      tableRows.push(cells);
      continue;
    }

    // Unordered list item: - ... or * ...
    const ulMatch = trimmed.match(/^[-*]\s+(.+)$/);
    if (ulMatch) {
      flushTable();
      flushPara();
      if (listOrdered) flushList();
      listOrdered = false;
      const itemContent = renderInline(ulMatch[1], citationMap, `li${key}`).map(
        (n, i) => <Fragment key={i}>{n}</Fragment>,
      );
      listItems.push(<li key={key++}>{itemContent}</li>);
      continue;
    }

    // Ordered list item: 1. ... 2. ...
    const olMatch = trimmed.match(/^\d+\.\s+(.+)$/);
    if (olMatch) {
      flushTable();
      flushPara();
      if (!listOrdered && listItems.length > 0) flushList();
      listOrdered = true;
      const itemContent = renderInline(olMatch[1], citationMap, `li${key}`).map(
        (n, i) => <Fragment key={i}>{n}</Fragment>,
      );
      listItems.push(<li key={key++}>{itemContent}</li>);
      continue;
    }

    // Horizontal rule
    if (/^[-*_]{3,}$/.test(trimmed)) {
      flushList();
      flushTable();
      flushPara();
      blocks.push(<hr key={key++} className="border-border/40 my-2" />);
      continue;
    }

    // Regular paragraph text — accumulate consecutive lines
    flushList();
    flushTable();
    paraLines.push(trimmed);
  }

  flushList();
  flushTable();
  flushPara();

  return blocks;
}

export default function AnalysisRichText({
  content,
  citations,
}: {
  content: string;
  citations?: AnalysisCitation[] | null;
}) {
  const citationMap = new Map<string, AnalysisCitation>(
    (citations ?? [])
      .filter((c) => c && c.id && c.title && c.url)
      .map((c) => [c.id, c]),
  );

  if (!content?.trim()) return null;

  return (
    <div className="ai-summary-content text-xs space-y-2">
      {renderBlocks(content, citationMap).map((block, i) => (
        <Fragment key={i}>{block}</Fragment>
      ))}
    </div>
  );
}
