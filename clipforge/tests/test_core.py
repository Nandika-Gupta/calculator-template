"""Unit tests for transcript parsing, moment scoring, copywriting and caption building."""

import numpy as np

from clipforge import ai, analysis
from clipforge.pipeline import JobSettings
from clipforge.render import RenderOptions, build_ass, chunk_words
from clipforge.transcript import Word, parse_subtitles, words_to_sentences

SRT = """1
00:00:01,000 --> 00:00:04,000
Why is nobody talking about the AI clipping business?

2
00:00:04,500 --> 00:00:09,000
Creators pay millions every month for short clips.

3
00:00:09,500 --> 00:00:12,000
Here's how it works.

4
00:00:12,500 --> 00:00:20,000
You take one long podcast and turn it into ten viral shorts.

5
00:00:21,000 --> 00:00:30,000
uh so yeah anyway we were just sitting around and stuff
"""


def test_parse_srt_into_timed_sentences():
    sentences = parse_subtitles(SRT)
    assert sentences[0].text.startswith("Why is nobody")
    assert sentences[0].start == 1.0
    words = [w for s in sentences for w in s.words]
    assert all(a.start <= b.start for a, b in zip(words, words[1:]))
    assert abs(sentences[0].words[-1].end - 4.0) < 0.01


def test_parse_vtt():
    vtt = "WEBVTT\n\n00:00.500 --> 00:02.000\n<v Bob>Hello there world.</v>\n"
    sentences = parse_subtitles(vtt)
    assert sentences[0].text == "Hello there world."
    assert sentences[0].start == 0.5


def test_words_to_sentences_splits_on_pause():
    words = [Word("hello", 0, 0.4), Word("there", 0.5, 0.9), Word("again", 3.0, 3.4)]
    assert [s.text for s in words_to_sentences(words)] == ["hello there", "again"]


def test_hook_strength_prefers_curiosity():
    assert analysis.hook_strength("Why is nobody talking about this?") > analysis.hook_strength(
        "so we were sitting there"
    )


def test_find_moments_prefers_hooky_segment():
    sentences = parse_subtitles(SRT)
    loud = np.full(200, -30.0, dtype=np.float32)
    moments = analysis.find_moments(sentences, loud, 30.0, count=1, min_len=8, max_len=20)
    assert len(moments) == 1
    assert moments[0].start == 1.0
    assert 0 < moments[0].score <= 99


def test_moments_do_not_overlap():
    sentences = parse_subtitles(SRT)
    loud = np.random.default_rng(0).normal(-30, 5, 200).astype(np.float32)
    moments = analysis.find_moments(sentences, loud, 30.0, count=3, min_len=4, max_len=12)
    for a, b in zip(moments, moments[1:]):
        assert a.end - b.start <= 0.1 * min(a.duration, b.duration) + 1e-6


def test_energy_only_fallback():
    loud = np.full(400, -40.0, dtype=np.float32)
    loud[200:220] = -5
    moments = analysis.find_moments([], loud, 100.0, count=2, min_len=10, max_len=20)
    assert moments and any(m.start <= 52 <= m.end for m in moments)


def test_hashtags_and_offline_copy():
    tags = analysis.hashtags_for("AI clipping business. The AI clipping business pays creators.")
    assert "#aiclipping" in tags
    assert all(t.startswith("#") for t in tags)
    sentences = parse_subtitles(SRT)
    cand = analysis.Candidate(1, 12, " ".join(s.text for s in sentences[:3]), sentences[:3])
    analysis.score_candidate(cand, np.zeros(100), [])
    copy = analysis.offline_copy(cand, 0)
    assert set(copy["posts"]) == {"tiktok", "instagram", "youtube", "x", "linkedin"}
    assert "#shorts" in copy["hashtags"]["youtube"]


def test_snap_to_sentences_respects_bounds():
    sentences = parse_subtitles(SRT)
    start, end, group = ai.snap_to_sentences(1.3, 11.0, sentences, 5, 15)
    assert start == sentences[0].start
    assert end - start <= 15
    assert group[0] is sentences[0]


def test_ass_captions_highlight_each_word():
    sentences = parse_subtitles(SRT)
    ass = build_ass(sentences[:1], 1.0, 4.0, RenderOptions(), hook="Wait for it")
    assert "Style: Caption" in ass and "Style: Hook" in ass
    assert "WAIT FOR IT" in ass
    assert ass.count("Dialogue: 0,") == len(sentences[0].words)
    none = build_ass(sentences[:1], 1.0, 4.0, RenderOptions(caption_style="none"))
    assert "Dialogue: 0," not in none


def test_chunk_words_limits():
    words = [Word(f"w{i}", i * 0.3, i * 0.3 + 0.25) for i in range(10)]
    assert all(len(c) <= 3 for c in chunk_words(words))


def test_settings_are_clamped():
    s = JobSettings.from_dict({"clip_count": "99", "min_len": 1, "max_len": 2, "show_hook": "false",
                               "layout": "weird", "resolution": 4000})
    assert s.clip_count == 20 and s.min_len == 5 and s.max_len == 10
    assert s.show_hook is False and s.layout == "auto" and s.resolution == 1080


def test_caption_events_never_overlap():
    sentences = parse_subtitles(SRT)
    ass = build_ass(sentences, 0.0, 30.0, RenderOptions())

    def secs(ts):
        h, m, s = ts.split(":")
        return int(h) * 3600 + int(m) * 60 + float(s)

    events = [line.split(",")[1:3] for line in ass.splitlines() if line.startswith("Dialogue: 0,")]
    spans = sorted((secs(a), secs(b)) for a, b in events)
    assert all(prev[1] <= nxt[0] + 1e-6 for prev, nxt in zip(spans, spans[1:]))


def test_claude_plans_are_snapped_and_normalised():
    from clipforge.pipeline import _plans_from_ai  # pylint: disable=import-outside-toplevel

    sentences = parse_subtitles(SRT)
    posts = ai.PlatformPosts(tiktok="t", instagram="i", youtube="y", x="x", linkedin="l")
    tags = ai.PlatformHashtags(tiktok=["fyp", "#ai"], instagram=[], youtube=["#shorts"], x=[], linkedin=[])
    clip = ai.ClipPlan(start=1.2, end=11.8, title="T", hook="HOOK", virality_score=90, reason="r",
                       posts=posts, hashtags=tags)
    result = ai.ClipPlans(clips=[clip, clip], video_summary="s", long_form_post="p")
    plans = _plans_from_ai(result, sentences, np.zeros(200), JobSettings.from_dict({"min_len": 5, "max_len": 15}))
    assert len(plans) == 1  # duplicate overlapping clip dropped
    assert plans[0]["start"] == 1.0 and plans[0]["hashtags"]["tiktok"] == ["#fyp", "#ai"]
