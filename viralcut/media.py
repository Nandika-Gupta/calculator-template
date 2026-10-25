"""FFmpeg / yt-dlp helpers: probing, audio extraction, loudness curve, downloads."""

from __future__ import annotations

import json
import shutil
import subprocess  # nosec B404 - ffmpeg is invoked with argument lists, never a shell
from dataclasses import dataclass
from pathlib import Path

import numpy as np

ENERGY_HOP = 0.25  # seconds per loudness sample


@dataclass
class VideoInfo:
    width: int
    height: int
    fps: float
    duration: float
    has_audio: bool


def require_ffmpeg() -> None:
    for tool in ("ffmpeg", "ffprobe"):
        if shutil.which(tool) is None:
            raise RuntimeError(f"{tool} not found on PATH - install FFmpeg first")


def run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    proc = subprocess.run(cmd, capture_output=True, check=False, **kwargs)  # nosec B603
    if proc.returncode != 0:
        tail = proc.stderr.decode(errors="replace")[-1500:]
        raise RuntimeError(f"{cmd[0]} failed ({proc.returncode}): {tail}")
    return proc


def probe(path: str | Path) -> VideoInfo:
    out = run(
        ["ffprobe", "-v", "error", "-show_streams", "-show_format", "-of", "json", str(path)]
    ).stdout
    data = json.loads(out)
    video = next((s for s in data["streams"] if s.get("codec_type") == "video"), None)
    if video is None:
        raise RuntimeError("no video stream found in file")
    num, _, den = video.get("avg_frame_rate", "30/1").partition("/")
    fps = float(num) / float(den or 1) if float(den or 1) and float(num) else 30.0
    width, height = int(video["width"]), int(video["height"])
    rotation = abs(int(video.get("tags", {}).get("rotate", 0) or 0))
    for side in video.get("side_data_list", []):
        rotation = abs(int(side.get("rotation", rotation) or 0))
    if rotation in (90, 270):
        width, height = height, width
    duration = float(data["format"].get("duration") or video.get("duration") or 0)
    has_audio = any(s.get("codec_type") == "audio" for s in data["streams"])
    return VideoInfo(width, height, fps, duration, has_audio)


def extract_audio(src: str | Path, dst: str | Path) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", str(dst)])
    return Path(dst)


def loudness_curve(wav_path: str | Path) -> np.ndarray:
    """RMS loudness (dB) per ENERGY_HOP seconds, read from a 16 kHz mono wav."""
    raw = run(
        ["ffmpeg", "-v", "error", "-i", str(wav_path), "-f", "s16le", "-ac", "1", "-ar", "16000", "-"]
    ).stdout
    samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768.0
    hop = int(16000 * ENERGY_HOP)
    n = len(samples) // hop
    if n == 0:
        return np.zeros(1, dtype=np.float32)
    frames = samples[: n * hop].reshape(n, hop)
    rms = np.sqrt(np.mean(frames**2, axis=1) + 1e-10)
    return (20 * np.log10(rms)).astype(np.float32)


def download(url: str, out_dir: Path) -> Path:
    """Download a video from YouTube/Twitch/Kick/Drive/etc. via yt-dlp."""
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError("only http(s) links are supported")
    try:
        import yt_dlp  # pylint: disable=import-outside-toplevel
    except ImportError as exc:
        raise RuntimeError("yt-dlp is not installed (pip install yt-dlp)") from exc
    opts = {
        "outtmpl": str(out_dir / "source.%(ext)s"),
        "format": "bv*[height<=1080]+ba/b[height<=1080]/b",
        "merge_output_format": "mp4",
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
    }
    with yt_dlp.YoutubeDL(opts) as ydl:
        info = ydl.extract_info(url, download=True)
        title = info.get("title") or ""
    files = sorted(out_dir.glob("source.*"), key=lambda p: p.stat().st_size, reverse=True)
    if not files:
        raise RuntimeError("download produced no file")
    (out_dir / "source_title.txt").write_text(title, encoding="utf-8")
    return files[0]


def thumbnail(src: str | Path, at: float, dst: str | Path) -> Path:
    run(["ffmpeg", "-y", "-v", "error", "-ss", f"{at:.2f}", "-i", str(src), "-frames:v", "1", "-q:v", "3", str(dst)])
    return Path(dst)
