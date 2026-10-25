"""End-to-end job: ingest -> transcribe -> find viral moments -> write copy -> render shorts."""

from __future__ import annotations

import json
import logging
import threading
import time
import traceback
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from . import ai, analysis, media
from .render import RenderOptions, render_clip
from .transcript import Sentence, parse_subtitles, transcribe, transcript_text

log = logging.getLogger(__name__)

STEPS = ["ingest", "transcribe", "analyze", "copywrite", "render", "done"]


@dataclass
class JobSettings:
    clip_count: int = 5
    min_len: float = 20
    max_len: float = 60
    layout: str = "auto"
    caption_style: str = "bold"
    show_hook: bool = True
    resolution: int = 720           # output width; height = width * 16 / 9
    whisper_model: str = "small"
    language: str | None = None
    use_ai: bool = True

    @staticmethod
    def from_dict(d: dict) -> "JobSettings":
        s = JobSettings()
        for k, v in d.items():
            if not hasattr(s, k) or v in (None, ""):
                continue
            current = getattr(s, k)
            if isinstance(current, bool):
                v = v if isinstance(v, bool) else str(v).lower() in ("1", "true", "on", "yes")
            elif isinstance(current, (int, float)):
                v = type(current)(float(v))
            else:
                v = str(v)
            setattr(s, k, v)
        s.clip_count = max(1, min(s.clip_count, 20))
        s.min_len = max(5.0, min(s.min_len, 170.0))
        s.max_len = max(s.min_len + 5, min(s.max_len, 180.0))
        s.resolution = 1080 if s.resolution >= 1080 else 720
        if s.layout not in ("auto", "track", "fit", "center"):
            s.layout = "auto"
        if s.caption_style not in ("bold", "karaoke", "neon", "minimal", "none"):
            s.caption_style = "bold"
        return s


@dataclass
class Job:
    id: str
    source: str
    settings: JobSettings
    status: str = "queued"       # queued | running | done | error
    step: str = "ingest"
    progress: float = 0.0
    message: str = "Waiting in queue"
    error: str = ""
    created: float = field(default_factory=time.time)
    title: str = ""
    duration: float = 0.0
    engine: str = ""
    transcript_source: str = ""
    summary: str = ""
    long_form_post: str = ""
    clips: list = field(default_factory=list)
    schedule: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)


class JobStore:
    """Jobs live in data/jobs/<id>/job.json so they survive restarts."""

    def __init__(self, root: Path, workers: int = 1):
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.lock = threading.Lock()
        self.jobs: dict[str, Job] = {}
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self._load()

    def _load(self) -> None:
        for path in self.root.glob("*/job.json"):
            try:
                d = json.loads(path.read_text(encoding="utf-8"))
                d["settings"] = JobSettings.from_dict(d.get("settings", {}))
                job = Job(**d)
                if job.status in ("queued", "running"):
                    job.status, job.error = "error", "Server restarted while this job was processing"
                self.jobs[job.id] = job
            except (ValueError, TypeError, KeyError):
                log.warning("skipping unreadable job file %s", path)

    def dir(self, job_id: str) -> Path:
        return self.root / job_id

    def create(self, source: str, settings: JobSettings) -> Job:
        job = Job(id=uuid.uuid4().hex[:12], source=source, settings=settings)
        self.dir(job.id).mkdir(parents=True, exist_ok=True)
        with self.lock:
            self.jobs[job.id] = job
        self.save(job)
        return job

    def save(self, job: Job) -> None:
        path = self.dir(job.id) / "job.json"
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(job.to_dict(), indent=2), encoding="utf-8")
        tmp.replace(path)

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def all(self) -> list[Job]:
        return sorted(self.jobs.values(), key=lambda j: j.created, reverse=True)

    def submit(self, job: Job, **kwargs) -> None:
        self.pool.submit(run_job, self, job, **kwargs)


def _update(store: JobStore, job: Job, step: str, progress: float, message: str) -> None:
    job.step, job.progress, job.message = step, round(progress, 3), message
    store.save(job)
    log.info("[%s] %s %.0f%% %s", job.id, step, progress * 100, message)


def run_job(store: JobStore, job: Job, video_path: Path | None = None, url: str | None = None,
            subtitles: str | None = None) -> None:
    jdir = store.dir(job.id)
    s = job.settings
    job.status = "running"
    try:
        media.require_ffmpeg()
        # 1. ingest ---------------------------------------------------------
        if url:
            _update(store, job, "ingest", 0.02, "Downloading video…")
            video_path = media.download(url, jdir)
            title_file = jdir / "source_title.txt"
            job.title = title_file.read_text(encoding="utf-8") if title_file.exists() else url
        if video_path is None:
            raise ValueError("no video provided")
        info = media.probe(video_path)
        job.duration = round(info.duration, 2)
        job.title = job.title or Path(job.source).stem
        _update(store, job, "ingest", 0.08, f"Loaded {info.width}x{info.height}, {info.duration / 60:.1f} min")

        # 2. transcript -------------------------------------------------------
        sentences: list[Sentence] = []
        loudness = None
        if info.has_audio:
            wav = media.extract_audio(video_path, jdir / "audio.wav")
            loudness = media.loudness_curve(wav)
            if subtitles:
                sentences = parse_subtitles(subtitles)
                job.transcript_source = "uploaded subtitles"
            else:
                _update(store, job, "transcribe", 0.12, "Transcribing speech with Whisper…")
                try:
                    sentences = transcribe(str(wav), s.whisper_model, s.language)
                    job.transcript_source = f"whisper-{s.whisper_model}"
                except RuntimeError as exc:
                    log.warning("transcription unavailable: %s", exc)
                    job.transcript_source = "none (audio energy only)"
                    job.message = str(exc)
        else:
            job.transcript_source = "none (no audio track)"
        if loudness is None:
            import numpy as np  # pylint: disable=import-outside-toplevel

            loudness = np.zeros(max(1, int(info.duration / media.ENERGY_HOP)), dtype="float32")
        (jdir / "transcript.json").write_text(json.dumps([x.to_dict() for x in sentences]), encoding="utf-8")
        (jdir / "transcript.txt").write_text(transcript_text(sentences, with_times=True), encoding="utf-8")

        # 3. find viral moments ------------------------------------------------
        _update(store, job, "analyze", 0.35, "Scoring hooks, energy & emotion…")
        moments = analysis.find_moments(sentences, loudness, info.duration, s.clip_count, s.min_len, s.max_len)
        hints = analysis.find_moments(sentences, loudness, info.duration, s.clip_count * 2, s.min_len, s.max_len)

        # 4. copywriting -------------------------------------------------------
        plans = []
        job.engine = "offline heuristics"
        if s.use_ai and ai.available() and sentences:
            _update(store, job, "copywrite", 0.45, f"Claude is picking clips & writing posts ({ai.MODEL})…")
            try:
                result = ai.plan_clips(
                    sentences, s.clip_count, s.min_len, s.max_len,
                    [{"start": c.start, "end": c.end, "score": c.score, "signals": c.signals} for c in hints],
                    job.title,
                )
                job.summary, job.long_form_post = result.video_summary, result.long_form_post
                plans = _plans_from_ai(result, sentences, loudness, s)
                job.engine = f"Claude ({ai.MODEL})"
            except Exception as exc:  # pylint: disable=broad-except
                log.warning("Claude planning failed, using heuristics: %s", exc)
                job.engine = f"offline heuristics (Claude error: {str(exc)[:160]})"
        if not plans:
            _update(store, job, "copywrite", 0.45, "Writing titles, posts & hashtags…")
            plans = [{"start": c.start, "end": c.end, "score": c.score, "signals": c.signals,
                      "sentences": c.sentences, "text": c.text, **analysis.offline_copy(c, i, job.title)}
                     for i, c in enumerate(moments)]
            if not job.long_form_post:
                job.summary = transcript_text(sentences)[:400]
                tags = " ".join(analysis.hashtags_for(transcript_text(sentences) or job.title, limit=5))
                job.long_form_post = (
                    f"{job.title}\n\nWe pulled the {len(plans)} best moments from this one. "
                    f"Which clip hits hardest? 👇\n\n{tags}"
                )

        # 5. render ------------------------------------------------------------
        opts = RenderOptions(width=s.resolution, height=s.resolution * 16 // 9, layout=s.layout,
                             caption_style=s.caption_style, show_hook=s.show_hook)
        job.clips = []
        for i, p in enumerate(plans):
            _update(store, job, "render", 0.5 + 0.48 * i / len(plans), f"Rendering short {i + 1}/{len(plans)}…")
            name = f"clip_{i + 1:02d}"
            layout = render_clip(video_path, info, p["start"], p["end"], jdir / f"{name}.mp4",
                                 p["sentences"], opts, p["hook"])
            media.thumbnail(jdir / f"{name}.mp4", min(1.0, (p["end"] - p["start"]) / 2), jdir / f"{name}.jpg")
            job.clips.append({
                "id": name,
                "video": f"{name}.mp4",
                "thumb": f"{name}.jpg",
                "start": round(p["start"], 2),
                "end": round(p["end"], 2),
                "duration": round(p["end"] - p["start"], 1),
                "score": p["score"],
                "signals": p.get("signals", {}),
                "title": p["title"],
                "hook": p["hook"],
                "reason": p["reason"],
                "posts": p["posts"],
                "hashtags": p["hashtags"],
                "transcript": p.get("text", ""),
                "layout": layout,
            })
            store.save(job)
        job.status = "done"
        _update(store, job, "done", 1.0, f"{len(job.clips)} shorts ready")
    except Exception as exc:  # pylint: disable=broad-except
        log.error("job %s failed: %s", job.id, traceback.format_exc())
        job.status, job.error = "error", str(exc)
        store.save(job)


def _plans_from_ai(result, sentences, loudness, s: JobSettings) -> list[dict]:
    energy = analysis._normalize(loudness)  # pylint: disable=protected-access
    kw = analysis.keywords(transcript_text(sentences), 15)
    plans, taken = [], []
    for clip in result.clips[: s.clip_count]:
        start, end, group = ai.snap_to_sentences(clip.start, clip.end, sentences, s.min_len, s.max_len)
        if any(min(end, b) - max(start, a) > 0.25 * min(end - start, b - a) for a, b in taken):
            continue
        taken.append((start, end))
        cand = analysis.score_candidate(
            analysis.Candidate(start, end, " ".join(x.text for x in group), group), energy, kw
        )
        plans.append({
            "start": start, "end": end, "sentences": group, "text": cand.text,
            "score": round(0.6 * clip.virality_score + 0.4 * cand.score, 1), "signals": cand.signals,
            "title": clip.title, "hook": clip.hook, "reason": clip.reason,
            "posts": clip.posts.model_dump(),
            "hashtags": {k: [t if t.startswith("#") else f"#{t}" for t in v]
                         for k, v in clip.hashtags.model_dump().items()},
        })
    return sorted(plans, key=lambda p: p["start"])
