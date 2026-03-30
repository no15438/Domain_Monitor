"""Event-aware relevance module.

Stages (all lightweight, no LLM):
  1. filter_by_relevance  — topic keyword gate
  2. dedup_by_similarity  — semantic near-duplicate removal (TF-IDF cosine)
  3. cluster_by_event     — group articles about the same event
  4. score_candidate      — multi-signal scoring inside each cluster
  5. select_representatives — pick canonical article per event
"""

from __future__ import annotations

import hashlib
import logging
import math
import re
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse

log = logging.getLogger("relevance")
_NON_ALNUM = re.compile(r"[^\w\s]", re.UNICODE)


def _normalize(text: str) -> str:
    return _NON_ALNUM.sub("", text).lower().strip()


# ── Authority map ─────────────────────────────────────
# Domain -> score (0.0 – 1.0).  Higher = more authoritative.
# Covers major international + Chinese sources.

AUTHORITY_MAP: dict[str, float] = {
    # Tier 1 — wire services & top international
    "reuters.com": 1.0, "apnews.com": 1.0, "afp.com": 1.0,
    "bbc.com": 0.95, "bbc.co.uk": 0.95,
    "nytimes.com": 0.95, "wsj.com": 0.95, "ft.com": 0.95,
    "bloomberg.com": 0.95, "economist.com": 0.95,
    # Tier 1 — Chinese authoritative
    "xinhuanet.com": 0.95, "people.com.cn": 0.95,
    "cctv.com": 0.90, "chinadaily.com.cn": 0.90,
    # Tier 2 — major broadsheets / channels
    "theguardian.com": 0.85, "washingtonpost.com": 0.85,
    "cnn.com": 0.80, "cnbc.com": 0.80, "aljazeera.com": 0.80,
    "scmp.com": 0.80, "caixin.com": 0.80,
    "nature.com": 0.90, "science.org": 0.90,
    "forbes.com": 0.75, "fortune.com": 0.75,
    # Tier 2 — tech press
    "techcrunch.com": 0.75, "theverge.com": 0.75,
    "arstechnica.com": 0.75, "wired.com": 0.75,
    "technologyreview.com": 0.80,
    "36kr.com": 0.70, "ithome.com": 0.65,
    # Tier 3 — solid regional / specialty
    "politico.com": 0.70, "axios.com": 0.70,
    "thehill.com": 0.65, "businessinsider.com": 0.65,
    "zdnet.com": 0.65, "venturebeat.com": 0.65,
    "yicai.com": 0.65, "jiemian.com": 0.60,
    "huxiu.com": 0.60, "leiphone.com": 0.55,
}

AGGREGATOR_DOMAINS = {
    "news.google.com", "news.yahoo.com", "msn.com",
    "flipboard.com", "feedly.com", "smartnews.com",
    "toutiao.com", "jinritoutiao.com",
}

DEFAULT_AUTHORITY = 0.30


# ── URL normalization ─────────────────────────────────

_TRACKING_PARAMS = frozenset({
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_reader", "utm_name", "utm_cid",
    "ref", "referrer", "from", "via", "source",
    "fbclid", "gclid", "msclkid", "yclid", "_ga",
    "share", "share_token", "cid", "ncid", "icid",
})

_AMP_RE = re.compile(r"/amp(/|$)", re.IGNORECASE)


def normalize_url(url: str) -> str:
    """Normalize a URL for deduplication.
    - Lowercases scheme + host
    - Strips known tracking query params (utm_*, fbclid, …)
    - Removes /amp/ path segments
    - Strips trailing slashes and fragments
    """
    if not url:
        return url
    try:
        p = urlparse(url.strip())
        host = (p.hostname or "").lower()
        if host.startswith("www."):
            host = host[4:]
        path = _AMP_RE.sub("/", p.path).rstrip("/") or "/"
        qs = {k: v for k, v in parse_qs(p.query).items()
              if k.lower() not in _TRACKING_PARAMS}
        query = urlencode(qs, doseq=True)
        return urlunparse((p.scheme.lower(), host, path, "", query, ""))
    except Exception:
        return url.lower().strip()


# ── Semantic dedup helpers ────────────────────────────

_CJK_RE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u3040-\u30ff]")


def _is_cjk_dominant(text: str) -> bool:
    cjk = len(_CJK_RE.findall(text))
    return cjk > max(len(text) * 0.2, 4)


def _char_bigrams(text: str) -> dict[str, int]:
    """Character bigram bag for CJK text (no word boundaries)."""
    t = text.strip()
    bg: dict[str, int] = {}
    for i in range(len(t) - 1):
        g = t[i: i + 2]
        if g.strip():
            bg[g] = bg.get(g, 0) + 1
    return bg


def _word_bag(text: str) -> dict[str, int]:
    """Bag-of-words (with stopword removal) for Latin-script text."""
    bow: dict[str, int] = {}
    for w in _normalize(text).split():
        if len(w) >= 2 and w not in _STOP:
            bow[w] = bow.get(w, 0) + 1
    return bow


def _text_vector(text: str) -> dict[str, int]:
    """Choose vectorisation strategy based on dominant script."""
    return _char_bigrams(text) if _is_cjk_dominant(text) else _word_bag(text)


def _cosine(v1: dict[str, int], v2: dict[str, int]) -> float:
    if not v1 or not v2:
        return 0.0
    dot = sum(v1.get(k, 0) * c for k, c in v2.items())
    mag1 = math.sqrt(sum(c * c for c in v1.values()))
    mag2 = math.sqrt(sum(c * c for c in v2.values()))
    if mag1 == 0 or mag2 == 0:
        return 0.0
    return dot / (mag1 * mag2)


_MIN_TEXT_LEN = 80  # Articles with combined title+content below this length
                    # have sparse vectors; skip semantic comparison to avoid
                    # false-positive deduplication of short breaking-news items.


def dedup_by_similarity(
    items: list[dict],
    threshold: float = 0.82,
) -> list[dict]:
    """Remove near-duplicate articles using TF-IDF cosine similarity.

    Vectors are built from title + first 800 chars of content.
    For each pair with similarity >= threshold the lower-authority article
    is dropped.  O(n²) — fast enough for n < 500 (post-URL-dedup corpus).

    Short articles (combined text < _MIN_TEXT_LEN chars) are excluded from
    pairwise comparison — their sparse vectors produce unreliably high cosine
    scores and should never be dropped by this stage.

    Threshold guidance:
      0.82  — "almost verbatim repost" — safe default, preserves different
              angles/commentary on the same event
      0.88  — used for cross-run dedup (even more conservative)
    """
    if len(items) <= 1:
        return items

    # Pre-build vectors and flag short articles
    vecs: list[dict[str, int]] = []
    too_short: list[bool] = []
    for item in items:
        text = item.get("title", "") + " " + (item.get("content") or "")[:800]
        too_short.append(len(text.strip()) < _MIN_TEXT_LEN)
        vecs.append(_text_vector(text))

    n = len(items)
    keep = [True] * n

    for i in range(n):
        if not keep[i]:
            continue
        for j in range(i + 1, n):
            if not keep[j]:
                continue
            # Skip comparison if either article has a sparse vector
            if too_short[i] or too_short[j]:
                continue
            sim = _cosine(vecs[i], vecs[j])
            if sim >= threshold:
                auth_i = _authority_of(items[i].get("url", ""))
                auth_j = _authority_of(items[j].get("url", ""))
                # Drop the lower-authority duplicate; tie → drop j
                if auth_i >= auth_j:
                    keep[j] = False
                else:
                    keep[i] = False
                    break  # i is gone; move to next i

    kept = [item for k, item in zip(keep, items) if k]
    removed = n - len(kept)
    if removed:
        log.info("semantic dedup removed %d/%d near-duplicates", removed, n)
    return kept


def _extract_domain(url: str) -> str:
    try:
        host = urlparse(url).hostname or ""
        if host.startswith("www."):
            host = host[4:]
        return host.lower()
    except Exception:
        return ""


def _authority_of(url: str) -> float:
    domain = _extract_domain(url)
    if domain in AUTHORITY_MAP:
        return AUTHORITY_MAP[domain]
    for known, score in AUTHORITY_MAP.items():
        if domain.endswith("." + known):
            return score
    return DEFAULT_AUTHORITY


# ── 1. Keyword relevance (topic gate) ────────────────


def _kw_matches(kw_norm: str, text: str) -> bool:
    """Return True if keyword matches text using three strategies:

    1. Exact normalized phrase substring  ("rba 利率" in text)
    2. Space-collapsed substring          ("asx200" matches "asx 200")
    3. Any individual word of the keyword (length ≥ 2) appears in text
       — lets mixed-language phrases like "RBA 利率" match English articles
         that only contain the English part "rba".
    """
    if kw_norm in text:
        return True
    # Space-collapsed: handles "ASX200" vs "ASX 200"
    if kw_norm.replace(" ", "") in text.replace(" ", ""):
        return True
    # Word-level fallback for multi-word phrases
    words = [w for w in kw_norm.split() if len(w) >= 2]
    if len(words) > 1 and any(w in text for w in words):
        return True
    return False


def score_relevance(item: dict, keywords: list[str]) -> float:
    """Score 0.0-1.0 based on keyword presence in title and content.

    Matching uses three strategies in order:
      1. Exact normalized phrase match
      2. Space-collapsed match  (ASX200 ↔ ASX 200)
      3. Any-word match for multi-word keywords  (RBA 利率 ↔ RBA)
    """
    if not keywords:
        return 1.0

    title = _normalize(item.get("title", ""))
    content = _normalize(item.get("content", ""))

    title_hits = 0
    content_hits = 0

    for kw in keywords:
        # Normalize keyword identically to article text (removes punctuation).
        kw_norm = _normalize(kw)
        if not kw_norm:
            continue
        if _kw_matches(kw_norm, title):
            title_hits += 1
        if _kw_matches(kw_norm, content):
            content_hits += 1

    total_kw = len([_normalize(k) for k in keywords if _normalize(k)])
    if total_kw == 0:
        return 1.0

    # Cap the denominator so even 1 keyword match in the title gives a score
    # above min_score regardless of how large the keyword list is.
    norm = min(total_kw, 5)
    title_score = min(1.0, title_hits / norm)
    content_score = min(1.0, content_hits / norm)

    return min(1.0, title_score * 0.6 + content_score * 0.4)


def filter_by_relevance(
    items: list[dict],
    keywords: list[str],
    min_score: float = 0.05,
) -> list[dict]:
    """Keep only articles that match at least one keyword."""
    scored = []
    for item in items:
        s = score_relevance(item, keywords)
        if s >= min_score:
            item["_relevance"] = s
            scored.append(item)

    scored.sort(key=lambda x: x.get("_relevance", 0), reverse=True)
    return scored


# ── 2. Event clustering ──────────────────────────────

_STOP = frozenset(
    "the a an and or but in on at to for of with by from is was are were "
    "be been has have had do does did will would shall should can could may "
    "might this that these those it its you your we our they their he she "
    "his her all very how what when where who which not no so if up out "
    "about into over after before between under than too also just more "
    "most some any new old big now here there then".split()
)


_CJK_RANGE = re.compile(r"[\u4e00-\u9fff\u3400-\u4dbf\u20000-\u2a6df\uac00-\ud7af]")


def _has_cjk(text: str) -> bool:
    """Return True if the text contains a significant proportion of CJK characters."""
    cjk_chars = len(_CJK_RANGE.findall(text))
    return cjk_chars > 0 and cjk_chars / max(len(text.replace(" ", "")), 1) > 0.2


def _cjk_ngrams(text: str, n: int = 2) -> set[str]:
    """Extract character n-grams from CJK text for overlap computation.

    Non-CJK token-length words are also included, making this work for
    mixed Chinese/English titles like 'BYD Ultra EV 上市价格公布'.
    """
    grams: set[str] = set()
    # ASCII-ish space-separated tokens
    for token in text.split():
        if not _CJK_RANGE.search(token):
            if len(token) >= 3 and token not in _STOP:
                grams.add(token)
    # CJK bigrams across the whole string (spaces stripped)
    cjk_only = "".join(_CJK_RANGE.findall(text))
    for i in range(len(cjk_only) - n + 1):
        grams.add(cjk_only[i:i + n])
    return grams


def _significant_words(text: str) -> set[str]:
    if _has_cjk(text):
        return _cjk_ngrams(text)
    return {w for w in text.split() if len(w) >= 3 and w not in _STOP}


def _title_similarity(a: str, b: str) -> float:
    """Combined metric: max of SequenceMatcher ratio and word/ngram overlap coefficient."""
    seq_sim = SequenceMatcher(None, a, b).ratio()

    words_a = _significant_words(a)
    words_b = _significant_words(b)
    if not words_a or not words_b:
        return seq_sim

    intersection = len(words_a & words_b)
    overlap_coeff = intersection / min(len(words_a), len(words_b))
    return max(seq_sim, overlap_coeff)


def _parse_date(raw: str) -> datetime | None:
    """Best-effort parse of diverse date strings."""
    if not raw:
        return None
    for fmt in (
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S.%f%z",
        "%a, %d %b %Y %H:%M:%S %Z",
        "%a, %d %b %Y %H:%M:%S %z",
        "%Y-%m-%d %H:%M:%S",
        "%Y-%m-%d",
    ):
        try:
            return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
        except (ValueError, TypeError):
            continue
    return None


def _time_close(a_raw: str, b_raw: str, max_hours: float = 72) -> bool:
    da, db = _parse_date(a_raw), _parse_date(b_raw)
    if da is None or db is None:
        return True  # unknown dates — don't penalize
    return abs((da - db).total_seconds()) <= max_hours * 3600


def cluster_by_event(
    items: list[dict],
    title_threshold: float = 0.38,
    time_window_hours: float = 72,
) -> list[list[dict]]:
    """Group articles into event clusters.

    Returns list of clusters, each cluster is a list of item dicts.
    Uses greedy single-link: an item joins the first cluster whose seed
    title is similar enough AND published within the time window.
    """
    clusters: list[list[dict]] = []
    seed_titles: list[str] = []
    seed_dates: list[str] = []

    for item in items:
        title_norm = _normalize(item.get("title", ""))
        pub_date = item.get("published_date", "")
        matched = False

        for idx, seed_title in enumerate(seed_titles):
            if not _time_close(pub_date, seed_dates[idx], time_window_hours):
                continue
            if _title_similarity(title_norm, seed_title) >= title_threshold:
                clusters[idx].append(item)
                matched = True
                break

        if not matched:
            clusters.append([item])
            seed_titles.append(title_norm)
            seed_dates.append(pub_date)

    return clusters


def _make_event_id(cluster: list[dict]) -> str:
    seed_title = cluster[0].get("title", "")
    return hashlib.md5(seed_title.encode()).hexdigest()[:12]


# ── 3. Candidate scoring inside a cluster ────────────


DEFAULT_WEIGHTS = {
    "authority": 0.35,
    "coverage": 0.25,
    "rank_proxy": 0.20,
    "freshness": 0.10,
    "originality": 0.10,
}


def score_candidate(
    item: dict,
    cluster_size: int,
    total_collected: int,
    weights: dict | None = None,
) -> tuple[float, dict]:
    """Score a single candidate article. Returns (total_score, breakdown)."""
    w = weights or DEFAULT_WEIGHTS

    # authority
    auth = _authority_of(item.get("url", ""))

    # coverage: log-scaled cluster size (1 article = 0, 10+ = ~1.0)
    cov = min(1.0, math.log(max(cluster_size, 1) + 1) / math.log(12))

    # rank proxy: collector return order (earlier = more popular/relevant)
    collect_idx = item.get("_collect_idx", total_collected)
    rank = 1.0 - (collect_idx / max(total_collected, 1))

    # freshness: exponential decay, half-life = 24h
    fresh = 0.5
    dt = _parse_date(item.get("published_date", ""))
    if dt:
        age_h = max((datetime.now(timezone.utc) - dt).total_seconds() / 3600, 0)
        fresh = math.exp(-0.029 * age_h)  # half-life ~24h

    # originality: aggregators penalized
    domain = _extract_domain(item.get("url", ""))
    orig = 0.2 if domain in AGGREGATOR_DOMAINS else 0.8
    if auth >= 0.75:
        orig = 1.0  # known authoritative = original by definition

    breakdown = {
        "authority": round(auth, 3),
        "coverage": round(cov, 3),
        "rank_proxy": round(rank, 3),
        "freshness": round(fresh, 3),
        "originality": round(orig, 3),
    }
    total = sum(breakdown[k] * w.get(k, 0) for k in breakdown)
    return round(total, 4), breakdown


# ── 4. Representative selection ───────────────────────


def select_representatives(
    clusters: list[list[dict]],
    total_collected: int,
    weights: dict | None = None,
    max_canonicals: int = 15,
) -> list[dict]:
    """For each cluster, pick the highest-scoring canonical article.

    Returns a flat list of canonical items, each annotated with:
      _event_id, _is_canonical, _event_size, _source_score, _source_breakdown,
      _cluster_alts  (list of non-canonical items in the same cluster)
    """
    canonicals: list[dict] = []

    for cluster in clusters:
        event_id = _make_event_id(cluster)
        cluster_size = len(cluster)

        scored = []
        for item in cluster:
            sc, bd = score_candidate(item, cluster_size, total_collected, weights)
            scored.append((sc, bd, item))

        scored.sort(key=lambda x: x[0], reverse=True)
        best_score, best_bd, best_item = scored[0]

        best_item["_event_id"] = event_id
        best_item["_is_canonical"] = 1
        best_item["_event_size"] = cluster_size
        best_item["_source_score"] = best_score
        best_item["_source_breakdown"] = best_bd

        # Annotate and attach non-canonical cluster members
        alts = []
        for sc, bd, item in scored[1:]:
            item["_event_id"] = event_id
            item["_is_canonical"] = 0
            item["_event_size"] = cluster_size
            item["_source_score"] = sc
            item["_source_breakdown"] = bd
            alts.append(item)
        best_item["_cluster_alts"] = alts

        canonicals.append(best_item)

    canonicals.sort(key=lambda x: x.get("_source_score", 0), reverse=True)
    return canonicals[:max_canonicals]
