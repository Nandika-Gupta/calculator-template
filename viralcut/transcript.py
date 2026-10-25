"""Transcript model, Whisper transcription and SRT/VTT parsing.

A transcript is a list of sentences; each sentence carries word-level timings
so captions can highlight the word being spoken.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field, asdict


@dataclass
class Word:
    text: str
    start: float
    end: float


@dataclass
class Sentence:
    text: str
    start: float
    end: float
    words: list[Word] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(d: dict) -> "Sentence":
        return Sentence(
            text=d["text"],
            start=d["start"],
            end=d["end"],
            words=[Word(**w) for w in d.get("words", [])],
        )


_SENTENCE_END = re.compile(r"[.!?…]+[\"')\]]*$")


def words_to_sentences(words: list[Word], max_gap: float = 1.2, max_len: float = 14.0) -> list[Sentence]:
    """Group timed words into sentences using punctuation, pauses and a length cap."""
    sentences: list[Sentence] = []
    current: list[Word] = []
    for i, w in enumerate(words):
        current.append(w)
        nxt = words[i + 1] if i + 1 < len(words) else None
        ends = bool(_SENTENCE_END.search(w.text))
        long_pause = nxt is not None and nxt.start - w.end > max_gap
        too_long = current[-1].end - current[0].start > max_len
        if nxt is None or ends or long_pause or too_long:
            sentences.append(
                Sentence(
                    text=" ".join(x.text for x in current).strip(),
                    start=current[0].start,
                    end=current[-1].end,
                    words=current,
                )
            )
            current = []
    return sentences


def spread_words(text: str, start: float, end: float) -> list[Word]:
    """Approximate word timings across a cue, weighted by word length."""
    tokens = text.split()
    if not tokens:
        return []
    weights = [len(t) + 2 for t in tokens]
    total = sum(weights)
    span = max(end - start, 0.01)
    words, t = [], start
    for tok, wt in zip(tokens, weights):
        d = span * wt / total
        words.append(Word(tok, round(t, 3), round(t + d, 3)))
        t += d
    return words


_TS = re.compile(r"(?:(\d+):)?(\d{1,2}):(\d{2})[.,](\d{1,3})")


def _ts(value: str) -> float:
    m = _TS.search(value)
    if not m:
        raise ValueError(f"bad timestamp: {value!r}")
    h, mnt, s, ms = m.groups()
    return int(h or 0) * 3600 + int(mnt) * 60 + int(s) + int(ms.ljust(3, "0")) / 1000


def parse_subtitles(content: str) -> list[Sentence]:
    """Parse SRT or WebVTT text into sentences with estimated word timings."""
    content = content.replace("\r\n", "\n").replace("\r", "\n")
    words: list[Word] = []
    for block in re.split(r"\n\s*\n", content):
        lines = [ln.strip() for ln in block.strip().split("\n") if ln.strip()]
        timing_idx = next((i for i, ln in enumerate(lines) if "-->" in ln), None)
        if timing_idx is None:
            continue
        left, right = lines[timing_idx].split("-->", 1)
        start, end = _ts(left), _ts(right.strip().split(" ")[0])
        text = " ".join(lines[timing_idx + 1 :])
        text = re.sub(r"<[^>]+>|\{[^}]+\}", "", text).strip()
        if text:
            words.extend(spread_words(text, start, end))
    return words_to_sentences(words)


def transcribe(audio_path: str, model_size: str = "small", language: str | None = None) -> list[Sentence]:
    """Transcribe audio with faster-whisper (word timestamps).

    Raises RuntimeError when faster-whisper or its model weights are unavailable,
    so the pipeline can fall back to audio-only analysis.
    """
    try:
        from faster_whisper import WhisperModel  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError("faster-whisper is not installed (pip install faster-whisper)") from exc
    try:
        device = os.environ.get("VIRALCUT_WHISPER_DEVICE", "cpu")  # "cuda" for NVIDIA GPUs with CUDA installed
        model = WhisperModel(model_size, device=device, compute_type="int8")
        segments, _info = model.transcribe(audio_path, word_timestamps=True, vad_filter=True, language=language)
        words = [
            Word(w.word.strip(), float(w.start), float(w.end))
            for seg in segments
            for w in (seg.words or [])
            if w.word.strip()
        ]
    except Exception as exc:  # model download / decode failures
        raise RuntimeError(f"transcription failed: {exc}") from exc
    return words_to_sentences(words)


def transcript_text(sentences: list[Sentence], with_times: bool = False) -> str:
    if with_times:
        return "\n".join(f"[{s.start:.1f}-{s.end:.1f}] {s.text}" for s in sentences)
    return " ".join(s.text for s in sentences)
