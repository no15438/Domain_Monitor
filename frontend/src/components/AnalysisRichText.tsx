"use client";

import { Fragment } from "react";
import ReactMarkdown from "react-markdown";
import type { Components } from "react-markdown";
import type { AnalysisCitation } from "@/lib/api";

/** Matches inline citation markers like [E1], [A2], [E12] */
const CITE_RE = /\[([EA]\d+)\]/g;

function splitCitations(
  text: string,
  citationMap: Map<string, AnalysisCitation>,
): React.ReactNode[] {
  const parts: React.ReactNode[] = [];
  let lastIndex = 0;
  const re = new RegExp(CITE_RE.source, "g");
  let match: RegExpExecArray | null;
  while ((match = re.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    const id = match[1];
    const c = citationMap.get(id);
    if (c) {
      parts.push(
        <a
          key={`${id}-${match.index}`}
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
    lastIndex = match.index + match[0].length;
  }
  if (lastIndex < text.length) parts.push(text.slice(lastIndex));
  return parts.length ? parts : [text];
}

function processChildren(
  children: React.ReactNode,
  citationMap: Map<string, AnalysisCitation>,
): React.ReactNode {
  if (typeof children === "string") {
    const parts = splitCitations(children, citationMap);
    if (parts.length === 1 && typeof parts[0] === "string") return children;
    return (
      <>
        {parts.map((p, i) => (
          <Fragment key={i}>{p}</Fragment>
        ))}
      </>
    );
  }
  if (Array.isArray(children)) {
    return (
      <>
        {(children as React.ReactNode[]).map((child, i) => (
          <Fragment key={i}>{processChildren(child, citationMap)}</Fragment>
        ))}
      </>
    );
  }
  return children;
}

function makeComponents(
  citationMap: Map<string, AnalysisCitation>,
): Components {
  const wrap = (children: React.ReactNode) =>
    processChildren(children, citationMap);
  return {
    p: ({ children }) => <p>{wrap(children)}</p>,
    li: ({ children }) => <li>{wrap(children)}</li>,
    h1: ({ children }) => <h1>{wrap(children)}</h1>,
    h2: ({ children }) => <h2>{wrap(children)}</h2>,
    h3: ({ children }) => <h3>{wrap(children)}</h3>,
    strong: ({ children }) => <strong>{wrap(children)}</strong>,
    em: ({ children }) => <em>{wrap(children)}</em>,
  };
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

  return (
    <div className="ai-summary-content text-xs space-y-2">
      <ReactMarkdown components={makeComponents(citationMap)}>
        {content}
      </ReactMarkdown>
    </div>
  );
}
