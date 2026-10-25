"""Viral-moment detection and offline (no-API) copywriting.

Every candidate window is scored on signals that correlate with short-form
retention: a strong opening hook, vocal energy spikes, speaking pace, emotional
and curiosity language, and whether the clip ends on a complete thought.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass, field

import numpy as np

from .media import ENERGY_HOP
from .transcript import Sentence

STOPWORDS = set(
    """a about above after again against all am an and any are aren't as at be because been before being below
    between both but by can can't cannot could couldn't did didn't do does doesn't doing don't down during each few
    for from further gonna got had hadn't has hasn't have haven't having he he'd he'll he's her here here's hers herself
    him himself his how how's i i'd i'll i'm i've if in into is isn't it it's its itself just let's like me more most
    mustn't my myself no nor not now of off on once only or other ought our ours ourselves out over own really right
    same say said says shan't she she'd she'll she's should shouldn't so some such than that that's the their theirs
    them themselves then there there's these they they'd they'll they're they've thing things think this those
    through to too under until up us very want was wasn't way we we'd we'll we're we've well were weren't what what's
    when when's where where's which while who who's whom why why's will with won't would wouldn't yeah yes you you'd
    you'll you're you've your yours yourself yourselves okay ok um uh actually basically literally kind sort going
    know mean get go one also lot even still much many make made every thats dont im youre ive ill cant wont
    nobody anybody somebody everybody someone anyone everyone something anything everything nothing talking talk
    tried try trying hit days day time times take takes took put puts tell told see saw look looking come came
    give gave need needs needed use used using start started work works working first last next ever new
    two three four five six seven eight nine ten twenty thirty forty fifty hundred thousand waiting wait
    people guys guy man stuff part point whole single month year week hour minute second seconds back keep""".split()
)

HOOK_PATTERNS = [
    r"\bwhy\b", r"\bhow (to|i|we|you)\b", r"\bwhat if\b", r"\bsecret", r"\bnobody\b", r"\bno one\b",
    r"\bnever\b", r"\bstop\b", r"\bmistake", r"\btruth\b", r"\bthe (real|biggest|best|worst)\b",
    r"\bhere'?s (why|how|what)\b", r"\byou (need|have) to\b", r"\bi (quit|lost|made|built|tried)\b",
    r"\bimagine\b", r"\bthis is (why|how|the)\b", r"\bdid you know\b", r"\bwait\b", r"\bcrazy\b",
    r"\binsane\b", r"\bunbelievable\b", r"\bshocking\b", r"\bmillion", r"\bbillion", r"\$\d",
    r"\b\d+\s?(k|%|percent|x|times|days|years|hours)\b",
]
EMOTION_WORDS = set(
    """amazing awesome crazy insane shocking love hate fear scared angry broke rich money died death kill
    win won lose lost fail failed failure success secret truth lie lies wrong worst best never always
    hilarious funny laugh cried crying wow omg unbelievable incredible huge massive dangerous illegal
    banned free viral famous fired quit rejected betrayed""".split()
)


@dataclass
class Candidate:
    start: float
    end: float
    text: str
    sentences: list[Sentence] = field(default_factory=list)
    score: float = 0.0
    signals: dict = field(default_factory=dict)

    @property
    def duration(self) -> float:
        return self.end - self.start


def tokenize(text: str) -> list[str]:
    return re.findall(r"[a-z0-9][a-z0-9'$%]*", text.lower())


def _content(tok: str) -> bool:
    return (tok not in STOPWORDS and len(tok) > 2 and not tok[0].isdigit() and "$" not in tok
            and not (tok.endswith("ly") and len(tok) > 5))


def keywords(text: str, top: int = 12) -> list[str]:
    """Topic words ranked by frequency, favouring longer, more specific words."""
    counts = Counter(t.strip("'") for t in tokenize(text) if _content(t.strip("'")))
    ranked = sorted(counts, key=lambda w: counts[w] * (1 + min(len(w), 12) / 6), reverse=True)
    return ranked[:top]


def key_phrases(text: str, top: int = 5) -> list[str]:
    """Repeated two-word phrases such as 'ai clipping' or 'side hustle'."""
    pairs: Counter = Counter()
    for clause in re.split(r"[.!?,;:]+", text):
        toks = tokenize(clause)
        pairs.update(f"{a}{b}" for a, b in zip(toks, toks[1:]) if (_content(a) or a == "ai") and _content(b))
    return [p for p, n in pairs.most_common(top) if n > 1 or len(pairs) < 4]


def hook_strength(text: str) -> float:
    """0..1 score for how scroll-stopping an opening line is."""
    t = text.lower()
    hits = sum(1 for p in HOOK_PATTERNS if re.search(p, t))
    score = min(hits, 3) / 3 * 0.7
    if "?" in text:
        score += 0.15
    if re.search(r"\byou\b", t):
        score += 0.1
    if len(t.split()) <= 14:
        score += 0.05
    return min(score, 1.0)


def _normalize(curve: np.ndarray) -> np.ndarray:
    if curve.size == 0:
        return curve
    lo, hi = np.percentile(curve, 10), np.percentile(curve, 98)
    return np.clip((curve - lo) / max(hi - lo, 1e-6), 0, 1)


def energy_between(curve: np.ndarray, start: float, end: float) -> tuple[float, float]:
    """Mean and peak normalised loudness within [start, end]."""
    i, j = int(start / ENERGY_HOP), max(int(end / ENERGY_HOP), int(start / ENERGY_HOP) + 1)
    seg = curve[i:j]
    if seg.size == 0:
        return 0.0, 0.0
    return float(seg.mean()), float(np.percentile(seg, 95))


def score_candidate(cand: Candidate, energy: np.ndarray, global_keywords: list[str]) -> Candidate:
    words = tokenize(cand.text)
    n = max(len(words), 1)
    first = cand.sentences[0].text if cand.sentences else cand.text[:120]
    hook = hook_strength(first)
    emotion = min(sum(1 for w in words if w in EMOTION_WORDS) / n * 12, 1.0)
    curiosity = min(cand.text.count("?") * 0.25 + len(re.findall(r"\d", cand.text)) * 0.05, 1.0)
    topical = min(sum(1 for w in words if w in global_keywords) / n * 6, 1.0)
    pace = n / max(cand.duration, 1)
    pace_score = float(np.exp(-((pace - 3.0) ** 2) / 2.0)) if cand.sentences else 0.5
    mean_e, peak_e = energy_between(energy, cand.start, cand.end)
    energy_score = 0.6 * mean_e + 0.4 * peak_e
    complete = 1.0 if (not cand.sentences or re.search(r"[.!?]$", cand.sentences[-1].text)) else 0.4
    signals = {
        "hook": hook, "energy": energy_score, "emotion": emotion, "curiosity": curiosity,
        "pace": pace_score, "topical": topical, "complete": complete,
    }
    weights = {"hook": 0.27, "energy": 0.2, "emotion": 0.15, "curiosity": 0.1, "pace": 0.1, "topical": 0.08, "complete": 0.1}
    raw = sum(signals[k] * w for k, w in weights.items())
    cand.signals = {k: round(v, 3) for k, v in signals.items()}
    cand.score = round(min(99.0, 40 + raw * 75), 1)
    return cand


def transcript_candidates(sentences: list[Sentence], min_len: float, max_len: float) -> list[Candidate]:
    """Every run of consecutive sentences whose duration fits the target range."""
    out = []
    for i, s in enumerate(sentences):
        for j in range(i, len(sentences)):
            dur = sentences[j].end - s.start
            if dur > max_len:
                break
            if dur >= min_len:
                group = sentences[i : j + 1]
                out.append(Candidate(s.start, sentences[j].end, " ".join(x.text for x in group), group))
    return out


def energy_candidates(energy: np.ndarray, duration: float, min_len: float, max_len: float) -> list[Candidate]:
    """Audio-only fallback: windows around loudness peaks, snapped to quiet points."""
    if energy.size < 8:
        return [Candidate(0, min(duration, max_len), "")]
    kernel = np.ones(8) / 8
    smooth = np.convolve(energy, kernel, mode="same")
    target = (min_len + max_len) / 2
    out = []
    order = np.argsort(smooth)[::-1]
    for idx in order[: max(40, len(order) // 20)]:
        center = idx * ENERGY_HOP
        start = max(0.0, center - target * 0.35)
        start = _snap_quiet(smooth, start, 2.0)
        end = min(duration, start + target)
        end = _snap_quiet(smooth, end, 2.0)
        if end - start >= min_len * 0.8:
            out.append(Candidate(round(start, 2), round(min(end, start + max_len), 2), ""))
    return out


def _snap_quiet(curve: np.ndarray, t: float, radius: float) -> float:
    i0 = max(0, int((t - radius) / ENERGY_HOP))
    i1 = min(len(curve), int((t + radius) / ENERGY_HOP) + 1)
    if i1 <= i0:
        return t
    return (i0 + int(np.argmin(curve[i0:i1]))) * ENERGY_HOP


def pick_top(cands: list[Candidate], count: int, max_overlap: float = 0.1) -> list[Candidate]:
    """Highest scores first, rejecting clips that overlap an already-chosen one."""
    chosen: list[Candidate] = []
    for c in sorted(cands, key=lambda c: c.score, reverse=True):
        if all(_overlap(c, o) <= max_overlap for o in chosen):
            chosen.append(c)
        if len(chosen) >= count:
            break
    return sorted(chosen, key=lambda c: c.start)


def _overlap(a: Candidate, b: Candidate) -> float:
    inter = max(0.0, min(a.end, b.end) - max(a.start, b.start))
    return inter / max(min(a.duration, b.duration), 1e-6)


def find_moments(sentences: list[Sentence], loudness: np.ndarray, duration: float,
                 count: int = 5, min_len: float = 20, max_len: float = 60) -> list[Candidate]:
    energy = _normalize(loudness)
    max_len = min(max_len, duration)
    min_len = min(min_len, max_len)
    if sentences:
        cands = transcript_candidates(sentences, min_len, max_len)
        if not cands:  # sentences longer than the window - fall back to one big clip
            cands = [Candidate(sentences[0].start, min(sentences[-1].end, sentences[0].start + max_len),
                               " ".join(s.text for s in sentences), sentences)]
    else:
        cands = energy_candidates(energy, duration, min_len, max_len)
    kw = keywords(" ".join(s.text for s in sentences), 15)
    for c in cands:
        score_candidate(c, energy, kw)
    return pick_top(cands, count)


# ---------------------------------------------------------------------------
# Offline copywriting (used when no ANTHROPIC_API_KEY is configured)
# ---------------------------------------------------------------------------

BROAD_TAGS = {
    "tiktok": ["#fyp", "#foryou", "#viral"],
    "instagram": ["#reels", "#explorepage", "#viralreels"],
    "youtube": ["#shorts", "#youtubeshorts"],
    "x": [],
    "linkedin": [],
}


def hashtags_for(text: str, extra: list[str] | None = None, limit: int = 10) -> list[str]:
    tags = []
    for w in (extra or []) + key_phrases(text, 3) + keywords(text, 15):
        tag = "#" + re.sub(r"[^a-z0-9]", "", w.lower())
        if len(tag) > 3 and tag not in tags:
            tags.append(tag)
    return tags[:limit]


def _title_case_hook(text: str, limit: int = 60) -> str:
    text = re.sub(r"\s+", " ", text).strip().rstrip(".,")
    if len(text) > limit:
        text = text[:limit].rsplit(" ", 1)[0] + "…"
    return text[:1].upper() + text[1:] if text else text


def offline_copy(cand: Candidate, index: int, source_title: str = "") -> dict:
    """Template-based titles, hooks, platform posts and hashtags."""
    first = cand.sentences[0].text if cand.sentences else ""
    kw = keywords(cand.text or source_title, 6)
    title = _title_case_hook(first) if first else (source_title or f"Best moment #{index + 1}")
    hook = _title_case_hook(first, 42).upper() if first else "WAIT FOR IT…"
    niche = hashtags_for(cand.text or source_title, limit=7)
    topic = " ".join(kw[:3]) or "this"
    posts = {
        "tiktok": f"{title} 🤯 Watch till the end… #{''.join(kw[:1]) or 'viral'}",
        "instagram": f"{title}\n\nThis is the part nobody talks about about {topic}. 👀\n"
                     "Save this for later & share it with someone who needs to hear it. 🔁",
        "youtube": f"{title} #shorts",
        "x": f"{title}\n\nThe most underrated take on {topic} 👇",
        "linkedin": f"{title}\n\nOne lesson on {topic} that changed how I think. "
                    "What's your take? 👇",
    }
    tags = {p: (niche + BROAD_TAGS[p])[:12] for p in BROAD_TAGS}
    return {
        "title": title,
        "hook": hook,
        "reason": _reason(cand.signals),
        "posts": posts,
        "hashtags": tags,
    }


def _reason(signals: dict) -> str:
    labels = {
        "hook": "strong opening hook", "energy": "high vocal energy", "emotion": "emotional language",
        "curiosity": "curiosity gap / numbers", "pace": "fast, punchy pacing", "topical": "on-topic",
        "complete": "ends on a complete thought",
    }
    top = sorted(signals.items(), key=lambda kv: kv[1], reverse=True)[:3]
    return ", ".join(labels[k] for k, v in top if v > 0.3).capitalize() or "Steady, engaging segment"
