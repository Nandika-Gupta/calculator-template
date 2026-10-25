"""Claude-powered viral moment selection and social copywriting.

Used when ANTHROPIC_API_KEY (or another Anthropic credential) is configured.
Falls back to the offline heuristics in analysis.py otherwise.
"""

from __future__ import annotations

import logging
import os

from pydantic import BaseModel, Field

from .transcript import Sentence, transcript_text

log = logging.getLogger(__name__)

MODEL = os.environ.get("CLIPFORGE_MODEL", "claude-opus-5-5")


class PlatformPosts(BaseModel):
    tiktok: str = Field(description="TikTok caption, punchy, <150 chars, no hashtags")
    instagram: str = Field(description="Instagram Reels caption: hook line, 2-3 short lines of value, CTA; no hashtags")
    youtube: str = Field(description="YouTube Shorts title, <70 chars, curiosity-driven; no hashtags")
    x: str = Field(description="X/Twitter post, <260 chars; no hashtags")
    linkedin: str = Field(description="LinkedIn post: hook, 3-5 short lines with a takeaway, question at end")


class PlatformHashtags(BaseModel):
    tiktok: list[str]
    instagram: list[str]
    youtube: list[str]
    x: list[str]
    linkedin: list[str]


class ClipPlan(BaseModel):
    start: float = Field(description="clip start in seconds, at the start of a sentence")
    end: float = Field(description="clip end in seconds, at the end of a sentence")
    title: str = Field(description="scroll-stopping title for the clip")
    hook: str = Field(description="on-screen hook text for the first 3 seconds, max 7 words, ALL CAPS")
    virality_score: int = Field(description="0-100 predicted virality")
    reason: str = Field(description="one sentence on why this moment will perform")
    posts: PlatformPosts
    hashtags: PlatformHashtags


class ClipPlans(BaseModel):
    clips: list[ClipPlan]
    video_summary: str = Field(description="one-paragraph summary of the whole video")
    long_form_post: str = Field(description="a standalone viral text post / thread opener promoting the full video")


SYSTEM = """You are a top short-form video editor and social media strategist who has grown \
channels to millions of followers by clipping podcasts, interviews, streams and talks.

From a timestamped transcript you pick the moments most likely to go viral as standalone \
9:16 shorts on TikTok, Instagram Reels and YouTube Shorts, and you write the copy to post them.

What makes a great clip:
- The first 3 seconds hook the viewer: a bold claim, a question, a surprising number, conflict, or emotion.
- It stands alone: a viewer with no context understands it and gets a payoff (insight, laugh, twist, story resolution).
- It starts at the beginning of a sentence and ends on a complete thought - never mid-sentence.
- High energy, strong opinions, stories and controversy beat generic small talk, intros and sponsor reads.
- Clips must not overlap each other.

Hashtags: 5-10 per platform, each starting with '#', mixing 2-3 broad discovery tags \
for that platform with specific niche/topic tags from the content. LinkedIn and X get 2-4 professional tags.
Write in the transcript's language. Make the copy sound human and native to each platform."""


def available() -> bool:
    return bool(os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN"))


def plan_clips(sentences: list[Sentence], count: int, min_len: float, max_len: float,
               hints: list[dict], source_title: str = "") -> ClipPlans:
    """Ask Claude for the best clips plus per-platform posts and hashtags."""
    import anthropic  # pylint: disable=import-outside-toplevel

    hint_lines = "\n".join(
        f"- {h['start']:.1f}-{h['end']:.1f}s (score {h['score']}, signals {h['signals']})" for h in hints
    )
    prompt = (
        f"Video title: {source_title or 'unknown'}\n\n"
        f"<transcript>\n{transcript_text(sentences, with_times=True)}\n</transcript>\n\n"
        f"Pick the {count} best clips, each between {min_len:.0f} and {max_len:.0f} seconds long. "
        "Use the transcript timestamps for start and end.\n\n"
        "An acoustic/linguistic pre-scorer flagged these windows (use them as hints, not rules):\n"
        f"{hint_lines or '- none'}"
    )
    client = anthropic.Anthropic()
    response = client.beta.messages.parse(
        model=MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
        output_format=ClipPlans,
        output_config={"effort": "high"},
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("Claude declined to process this transcript")
    if response.parsed_output is None:
        raise RuntimeError(f"Claude returned no structured output (stop_reason={response.stop_reason})")
    return response.parsed_output


def snap_to_sentences(start: float, end: float, sentences: list[Sentence],
                      min_len: float, max_len: float) -> tuple[float, float, list[Sentence]]:
    """Align a proposed clip to sentence boundaries and the allowed length."""
    if not sentences:
        return start, end, []
    first = min(range(len(sentences)), key=lambda i: abs(sentences[i].start - start))
    last = min(range(first, len(sentences)), key=lambda i: abs(sentences[i].end - end))
    while last > first and sentences[last].end - sentences[first].start > max_len:
        last -= 1
    while last + 1 < len(sentences) and sentences[last].end - sentences[first].start < min_len:
        last += 1
    group = sentences[first : last + 1]
    return group[0].start, group[-1].end, group
