#!/usr/bin/env python3
"""
Multi-stage debug harness for the two-stage evolution report pipeline.

Inspect each stage independently without making real LLM calls (unless
--regenerate-* flags are passed).

Usage:
    cd backend
    python scripts/debug_evolution_prompt.py --topic 22
    python scripts/debug_evolution_prompt.py --topic 22 --stage context
    python scripts/debug_evolution_prompt.py --topic 22 --stage facts
    python scripts/debug_evolution_prompt.py --topic 22 --stage narrative
    python scripts/debug_evolution_prompt.py --topic 22 --regenerate-facts
    python scripts/debug_evolution_prompt.py --topic 22 --regenerate-narrative
    python scripts/debug_evolution_prompt.py --topic 22 --output /tmp/debug.json
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import settings
import database
import topic_summary
from topic_summary import (
    _load_evolution_fact_bundle,
    _build_evolution_citation_catalog,
    _render_evolution_debug_context,
    _build_extractor_user_message,
    _extract_diff_facts_llm,
    _build_rule_based_diff_facts,
    _build_narrator_user_message,
    _collect_stage_context_diagnostics,
    _collect_stage_facts_diagnostics,
    _collect_stage_narrative_diagnostics,
)


def _print_separator(title: str = "", width: int = 72):
    if title:
        pad = max(0, width - len(title) - 4)
        print(f"\n{'─' * 2} {title} {'─' * pad}")
    else:
        print("─" * width)


def _section_breakdown(ctx: str) -> list[dict]:
    names = re.findall(r"=== (.+?) ===", ctx)
    parts = re.split(r"=== .+? ===", ctx)
    result = []
    for i, name in enumerate(names):
        body = parts[i + 1].strip() if i + 1 < len(parts) else ""
        diff_markers = {
            "[NE]": body.count("[NE]"),
            "[RE]": body.count("[RE]"),
            "[NC]": body.count("[NC]"),
            "[DC]": body.count("[DC]"),
            "[PC]": body.count("[PC]"),
        }
        result.append({
            "section": name,
            "chars": len(body),
            "lines": body.count("\n"),
            "diff_markers": {k: v for k, v in diff_markers.items() if v > 0},
        })
    return result


def _dump_json(path: str, data: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    print(f"\n[debug] Output written to: {path}")


def show_context_stage(bundle, citations, debug_ctx, args):
    """Print Stage A: context assembly diagnostics."""
    _print_separator("Stage A — Context / EvolutionFactBundle")

    diag = _collect_stage_context_diagnostics(bundle, citations)
    print(f"  Tier             : {diag['tier']}")
    print(f"  Snapshots        : {diag['snapshot_count']}")
    print(f"  New events       : {diag['new_events_count']}")
    print(f"  Resolved events  : {diag['resolved_events_count']}")
    print(f"  New claims       : {diag['new_claims_count']}")
    print(f"  Dropped claims   : {diag['dropped_claims_count']}")
    print(f"  Persisted claims : {diag['persisted_claims_count']}")
    print(f"  Claim evolution  : {diag['claim_evolution_count']}")
    print(f"  Evidence sets    : {diag['evidence_sets_count']}")
    print(f"  Citations avail  : {len(diag['citation_ids_available'])} "
          f"({', '.join(diag['citation_ids_available'][:8])}...)")

    _print_separator("Debug Context Sections")
    sections = _section_breakdown(debug_ctx)
    print(f"  {'Section':<45} {'Chars':>7}  {'Lines':>5}  Diff markers")
    print(f"  {'─'*45} {'─'*7}  {'─'*5}  {'─'*20}")
    for s in sections:
        markers_str = ", ".join(f"{k}×{v}" for k, v in s["diff_markers"].items()) or "—"
        print(f"  {s['section']:<45} {s['chars']:>7,}  {s['lines']:>5}  {markers_str}")

    if args.show_full_ctx:
        _print_separator("Full Debug Context")
        print(debug_ctx)

    return diag, sections


def show_facts_stage(bundle, citations, regenerate: bool = False):
    """Print Stage B: extractor input and output."""
    _print_separator("Stage B — Fact Extraction")

    extractor_msg = _build_extractor_user_message(bundle, citations)
    print(f"  Extractor user msg length : {len(extractor_msg):,} chars")

    # Count diff markers in extractor input
    ne = extractor_msg.count("[NE-")
    re_ = extractor_msg.count("[RE-")
    nc = extractor_msg.count("[NC-")
    dc = extractor_msg.count("[DC-")
    pc = extractor_msg.count("[PC-")
    print(f"  Diff markers in extractor : [NE]×{ne} [RE]×{re_} [NC]×{nc} [DC]×{dc} [PC]×{pc}")

    print()
    print("  Extractor input (first 800 chars):")
    print("  " + extractor_msg[:800].replace("\n", "\n  "))

    diff_facts = None
    stage_facts_diag = None

    if regenerate:
        _print_separator("Calling Extractor LLM (real API call)")
        diff_facts, stage_facts_diag = _extract_diff_facts_llm(bundle, citations)
        print(f"  Hash            : {stage_facts_diag['raw_extractor_hash']}")
        print(f"  Raw length      : {stage_facts_diag['raw_extractor_length']:,}")
        print(f"  Is fallback     : {stage_facts_diag['is_fallback']}")
        if stage_facts_diag["validation_errors"]:
            print(f"  ⚠ Errors        : {stage_facts_diag['validation_errors']}")
        print(f"  top_changes            : {stage_facts_diag['top_changes_count']}")
        print(f"  event_transitions      : {stage_facts_diag['event_transitions_count']} "
              f"(reframed={stage_facts_diag['event_transitions_reframed']})")
        print(f"  claim_trajectories     : {stage_facts_diag['claim_trajectories_count']} "
              f"(priority1={stage_facts_diag['claim_trajectories_priority1']}, "
              f"bound_to_events={stage_facts_diag['claim_trajectories_bound_to_events']})")
        print(f"  strategic_implications : {stage_facts_diag['strategic_implications_count']}")
        _print_separator("Extracted DiffFacts")
        print(json.dumps({
            "top_changes": diff_facts.top_changes,
            "event_transitions": diff_facts.event_transitions,
            "claim_trajectories": diff_facts.claim_trajectories,
            "strategic_implications": diff_facts.strategic_implications,
        }, ensure_ascii=False, indent=2))
    else:
        print("\n  [Pass --regenerate-facts to call the extractor LLM]")
        # Show rule-based fallback as preview
        valid_ids = {c["id"] for c in citations}
        diff_facts = _build_rule_based_diff_facts(bundle, valid_ids)
        stage_facts_diag = _collect_stage_facts_diagnostics(diff_facts)
        print(f"\n  Rule-based fallback preview:")
        print(f"    event_transitions  : {len(diff_facts.event_transitions)}")
        print(f"    claim_trajectories : {len(diff_facts.claim_trajectories)}")

    return diff_facts, stage_facts_diag


def show_narrative_stage(diff_facts, citations, bundle, tier, regenerate: bool = False):
    """Print Stage C: narrator input and output."""
    _print_separator("Stage C — Narrative")

    narrator_msg = _build_narrator_user_message(diff_facts, citations, bundle, tier)
    print(f"  Narrator user msg length : {len(narrator_msg):,} chars")

    facts_json_len = len(json.dumps({
        "top_changes": diff_facts.top_changes,
        "event_transitions": diff_facts.event_transitions,
        "claim_trajectories": diff_facts.claim_trajectories,
        "strategic_implications": diff_facts.strategic_implications,
    }))
    print(f"  DiffFacts JSON size      : {facts_json_len:,} chars")
    print(f"  top_changes              : {len(diff_facts.top_changes)}")
    print(f"  event_transitions        : {len(diff_facts.event_transitions)}")
    print(f"  claim_trajectories       : {len(diff_facts.claim_trajectories)} "
          f"(p1={sum(1 for c in diff_facts.claim_trajectories if c.get('priority', 1) == 1)})")

    print()
    print("  Narrator input (first 1000 chars):")
    print("  " + narrator_msg[:1000].replace("\n", "\n  "))

    if regenerate:
        _print_separator("Calling Narrator LLM (real API call)")
        from llm_client import llm_chat
        from topic_summary import EVOLUTION_NARRATOR_SYSTEM, _normalize_citations
        raw = llm_chat(
            [
                {"role": "system", "content": EVOLUTION_NARRATOR_SYSTEM},
                {"role": "user", "content": narrator_msg},
            ],
            temperature=0.45,
        )
        result = _normalize_citations(raw, citations)
        stage_narrative_diag = _collect_stage_narrative_diagnostics(result, diff_facts, citations)
        print(f"  Result length   : {stage_narrative_diag['result_length']:,}")
        print(f"  Citations used  : {stage_narrative_diag['citations_used_count']} "
              f"({', '.join(stage_narrative_diag['citations_used'])})")
        print(f"  Grounded facts  : {stage_narrative_diag['facts_grounded_count']}/"
              f"{stage_narrative_diag['facts_total_count']}")
        print(f"  Section overlap : {stage_narrative_diag.get('section1_section3_overlap', 'n/a')} "
              f"(S1 vs S3, lower is better)")
        print(f"  Insuff. sections: {stage_narrative_diag.get('insufficient_sections', 'n/a')}")
        generic = stage_narrative_diag["generic_check"]
        print(f"  Is generic      : {generic['is_generic']}")
        if generic.get("flags"):
            print(f"  Generic flags   : {', '.join(generic['flags'])}")
        _print_separator("Generated Narrative")
        print(result[:2500])
        if len(result) > 2500:
            print(f"\n  ... [{len(result) - 2500} more chars]")
        return result, stage_narrative_diag
    else:
        print("\n  [Pass --regenerate-narrative to call the narrator LLM]")
        return None, None


def show_stored_artifact(topic_id: int):
    """Print details of the stored evolution artifact."""
    _print_separator("Stored Artifact")
    artifact = database.get_synthesis_artifact(topic_id, "evolution_report")
    if not artifact:
        print("  No stored artifact found — run generation first.")
        return

    content_len = len(artifact.get("content", ""))
    meta = artifact.get("metadata") or {}
    if isinstance(meta, str):
        try:
            meta = json.loads(meta)
        except Exception:
            meta = {}

    stored_diag = meta.get("diagnostics", {})
    source = meta.get("source", "unknown")
    print(f"  Source          : {source}")
    print(f"  Content length  : {content_len:,} chars")

    if "stage_context" in stored_diag:
        # New 3-stage diagnostics
        sc = stored_diag.get("stage_context", {})
        sf = stored_diag.get("stage_facts", {})
        sn = stored_diag.get("stage_narrative", {})
        print(f"\n  Stage A (context):")
        print(f"    tier            : {sc.get('tier', 'n/a')}")
        print(f"    new_events      : {sc.get('new_events_count', 'n/a')}")
        print(f"    new_claims      : {sc.get('new_claims_count', 'n/a')}")
        print(f"\n  Stage B (facts):")
        print(f"    is_fallback     : {sf.get('is_fallback', 'n/a')}")
        print(f"    top_changes     : {sf.get('top_changes_count', 'n/a')}")
        print(f"    event_transitions : {sf.get('event_transitions_count', 'n/a')} "
              f"(reframed={sf.get('event_transitions_reframed', 'n/a')})")
        print(f"    claim_trajectories: {sf.get('claim_trajectories_count', 'n/a')} "
              f"(p1={sf.get('claim_trajectories_priority1', 'n/a')}, "
              f"bound={sf.get('claim_trajectories_bound_to_events', 'n/a')})")
        print(f"    validation_errors : {sf.get('validation_errors', [])}")
        print(f"\n  Stage C (narrative):")
        print(f"    result_length   : {sn.get('result_length', 'n/a')}")
        print(f"    citations_used  : {sn.get('citations_used_count', 'n/a')}")
        print(f"    facts_grounded  : {sn.get('facts_grounded_count', 'n/a')}/{sn.get('facts_total_count', 'n/a')}")
        print(f"    section_overlap : {sn.get('section1_section3_overlap', 'n/a')}")
        print(f"    insufficient_sections: {sn.get('insufficient_sections', 'n/a')}")
        generic = sn.get("generic_check", {})
        print(f"    is_generic      : {generic.get('is_generic', 'n/a')}")
        if generic.get("flags"):
            print(f"    generic_flags   : {', '.join(generic['flags'])}")
    else:
        # Legacy single-stage diagnostics
        print(f"  Tier (stored)   : {stored_diag.get('tier', 'n/a')}")
        generic = stored_diag.get("generic_check", {})
        print(f"  Is generic      : {generic.get('is_generic', 'n/a')}")

    print()
    print("  Content preview (first 1000 chars):")
    print("  " + artifact["content"][:1000].replace("\n", "\n  "))


def main():
    parser = argparse.ArgumentParser(description="Debug evolution pipeline (two-stage)")
    parser.add_argument("--topic", type=int, required=True, help="Topic ID")
    parser.add_argument(
        "--stage",
        choices=["context", "facts", "narrative", "all"],
        default="all",
        help="Which stage to inspect (default: all)",
    )
    parser.add_argument("--regenerate-facts", action="store_true",
                        help="Call the extractor LLM (Stage B) with a real API call")
    parser.add_argument("--regenerate-narrative", action="store_true",
                        help="Call the narrator LLM (Stage C) with a real API call")
    parser.add_argument("--output", type=str, default=None,
                        help="Write debug JSON to this file path")
    parser.add_argument("--show-full-ctx", action="store_true",
                        help="Print the full debug context string")
    args = parser.parse_args()

    database.init_db(settings.database_path)
    topic_id = args.topic

    print(f"\n{'═' * 72}")
    print(f"  EVOLUTION PIPELINE DEBUG — topic_id={topic_id}")
    print(f"  {datetime.now(timezone.utc).isoformat()}")
    print(f"{'═' * 72}")

    # ── Load bundle ───────────────────────────────────────────────────────
    bundle = _load_evolution_fact_bundle(topic_id)
    if bundle.tier == "skip":
        print(f"\n  ✗ SKIP: {bundle.error}")
        sys.exit(0)

    snapshots = database.get_temporal_snapshots(topic_id, window_type="daily", limit=6)
    oldest_ts = snapshots[-1].get("window_end") or snapshots[-1].get("created_at", "") if snapshots else ""
    newest_ts = snapshots[0].get("window_end") or snapshots[0].get("created_at", "") if snapshots else ""
    citations = _build_evolution_citation_catalog(topic_id, oldest_ts, newest_ts)
    debug_ctx = _render_evolution_debug_context(bundle)

    show_context = args.stage in ("context", "all")
    show_facts = args.stage in ("facts", "all")
    show_narr = args.stage in ("narrative", "all")

    context_diag = {}
    sections = []
    diff_facts = None
    facts_diag = {}
    narrative = None
    narrative_diag = None

    if show_context:
        context_diag, sections = show_context_stage(bundle, citations, debug_ctx, args)

    if show_facts:
        diff_facts, facts_diag = show_facts_stage(bundle, citations, args.regenerate_facts)

    if show_narr and diff_facts is not None:
        narrative, narrative_diag = show_narrative_stage(
            diff_facts, citations, bundle, bundle.tier, args.regenerate_narrative
        )

    show_stored_artifact(topic_id)

    # ── JSON output ───────────────────────────────────────────────────────
    if args.output:
        output_data = {
            "topic_id": topic_id,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "tier": bundle.tier,
            "stage_context": context_diag,
            "debug_context_sections": sections,
            "citations": citations,
            "stage_facts": facts_diag,
            "stage_narrative": narrative_diag,
            "diff_facts": {
                "event_transitions": diff_facts.event_transitions if diff_facts else [],
                "claim_trajectories": diff_facts.claim_trajectories if diff_facts else [],
                "strategic_implications": diff_facts.strategic_implications if diff_facts else [],
            } if diff_facts else None,
        }
        _dump_json(args.output, output_data)

    print(f"\n{'═' * 72}\n")


if __name__ == "__main__":
    main()
