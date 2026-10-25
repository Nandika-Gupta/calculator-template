"""Render 9:16 shorts: face-tracked reframing, animated word-by-word captions, hook title."""

from __future__ import annotations

import os
import subprocess  # nosec B404 - argument lists only, no shell
import tempfile
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .media import VideoInfo
from .transcript import Sentence, Word

CAPTION_STYLES = {
    # name: (primary BGR hex, highlight BGR hex, outline, uppercase, font size ratio)
    "bold": ("FFFFFF", "00E5FF", 7, True, 0.062),      # white + yellow pop (Hormozi style)
    "karaoke": ("FFFFFF", "3CF03C", 6, True, 0.058),   # white + green
    "neon": ("FFF4E0", "FF4FD8", 5, False, 0.055),     # soft white + magenta
    "minimal": ("FFFFFF", "FFFFFF", 4, False, 0.045),  # clean, no highlight colour
}
FONT = os.environ.get("CLIPFORGE_FONT", "Arial Black")


@dataclass
class RenderOptions:
    width: int = 720
    height: int = 1280
    layout: str = "auto"         # auto | track | fit | center
    caption_style: str = "bold"  # see CAPTION_STYLES, or "none"
    show_hook: bool = True
    max_fps: float = 30.0


# ---------------------------------------------------------------------------
# Captions (ASS subtitles rendered by libass)
# ---------------------------------------------------------------------------


def _ass_time(t: float) -> str:
    t = max(t, 0.0)
    h, rem = divmod(t, 3600)
    m, s = divmod(rem, 60)
    return f"{int(h)}:{int(m):02d}:{s:05.2f}"


def _ass_escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("{", "(").replace("}", ")").replace("\n", " ")


def chunk_words(words: list[Word], max_words: int = 3, max_chars: int = 18, max_gap: float = 0.6) -> list[list[Word]]:
    """Split words into short on-screen caption groups."""
    chunks: list[list[Word]] = []
    cur: list[Word] = []
    for w in words:
        if cur and (
            len(cur) >= max_words
            or sum(len(x.text) + 1 for x in cur) + len(w.text) > max_chars
            or w.start - cur[-1].end > max_gap
            or cur[-1].text[-1:] in ".!?,"
        ):
            chunks.append(cur)
            cur = []
        cur.append(w)
    if cur:
        chunks.append(cur)
    return chunks


def build_ass(sentences: list[Sentence], clip_start: float, clip_end: float, opts: RenderOptions,
              hook: str = "") -> str:
    w, h = opts.width, opts.height
    style = CAPTION_STYLES.get(opts.caption_style, CAPTION_STYLES["bold"])
    primary, highlight, outline, upper, size_ratio = style
    fs = int(h * size_ratio)
    hook_fs = int(h * 0.042)
    header = f"""[Script Info]
ScriptType: v4.00+
PlayResX: {w}
PlayResY: {h}
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Caption,{FONT},{fs},&H00{primary},&H00{highlight},&H00000000,&H96000000,-1,0,0,0,100,100,1,0,1,{outline},3,2,{int(w * 0.06)},{int(w * 0.06)},{int(h * 0.27)},1
Style: Hook,{FONT},{hook_fs},&H00000000,&H00000000,&H00FFFFFF,&H00FFFFFF,-1,0,0,0,100,100,0,0,3,{int(hook_fs * 0.45)},0,8,{int(w * 0.08)},{int(w * 0.08)},{int(h * 0.11)},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    lines = []
    if hook and opts.show_hook:
        lines.append(
            f"Dialogue: 1,{_ass_time(0)},{_ass_time(min(3.5, clip_end - clip_start))},Hook,,0,0,0,,"
            f"{{\\fad(150,250)}}{_ass_escape(hook.upper())}"
        )
    if opts.caption_style != "none":
        words = [w_ for s in sentences for w_ in s.words if clip_start - 0.05 <= w_.start < clip_end]
        chunks = chunk_words(words)
        for c_idx, chunk in enumerate(chunks):
            chunk_end = chunk[-1].end + 0.15
            if c_idx + 1 < len(chunks):  # never overlap the next caption group
                chunk_end = min(chunk_end, chunks[c_idx + 1][0].start)
            for i, word in enumerate(chunk):
                start = word.start - clip_start
                end = (chunk[i + 1].start if i + 1 < len(chunk) else chunk_end) - clip_start
                end = min(end, clip_end - clip_start)
                if end <= start:
                    continue
                parts = []
                for j, other in enumerate(chunk):
                    txt = _ass_escape(other.text.upper() if upper else other.text)
                    if j == i and opts.caption_style != "minimal":
                        parts.append(
                            f"{{\\c&H{highlight}&\\fscx118\\fscy118\\t(0,110,\\fscx100\\fscy100)}}{txt}"
                            f"{{\\c&H{primary}&\\fscx100\\fscy100}}"
                        )
                    else:
                        parts.append(txt)
                lines.append(
                    f"Dialogue: 0,{_ass_time(start)},{_ass_time(end)},Caption,,0,0,0,,{' '.join(parts)}"
                )
    return header + "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Face-tracked reframing
# ---------------------------------------------------------------------------


class FaceTracker:
    """Keeps the most prominent face inside a 9:16 window with smooth camera moves."""

    def __init__(self, frame_w: int, crop_w: int, fps: float):
        import cv2  # pylint: disable=import-outside-toplevel

        self.cv2 = cv2
        self.detector = cv2.CascadeClassifier(os.path.join(cv2.data.haarcascades, "haarcascade_frontalface_default.xml"))
        self.frame_w, self.crop_w = frame_w, crop_w
        self.every = max(1, int(round(fps / 6)))  # detect ~6 times per second
        self.cam = frame_w / 2
        self.target = frame_w / 2
        self.pending: list[float] = []
        self.frame_no = 0
        self.locked = False

    def _detect(self, frame: np.ndarray) -> float | None:
        cv2 = self.cv2
        scale = 360 / frame.shape[0]
        small = cv2.resize(frame, (int(frame.shape[1] * scale), 360))
        gray = cv2.equalizeHist(cv2.cvtColor(small, cv2.COLOR_BGR2GRAY))
        faces = self.detector.detectMultiScale(gray, scaleFactor=1.15, minNeighbors=6, minSize=(28, 28))
        if len(faces) == 0:
            return None
        x, _y, fw, _fh = max(faces, key=lambda f: f[2] * f[3])
        return (x + fw / 2) / scale

    def crop_x(self, frame: np.ndarray) -> int:
        if self.frame_no % self.every == 0:
            cx = self._detect(frame)
            if cx is not None and not self.locked:
                self.target = self.cam = cx  # first face: start framed on it
                self.locked = True
            elif cx is not None:
                if abs(cx - self.target) > self.crop_w * 0.5:
                    # big jump: require two agreeing detections, then hard-cut (new shot / speaker)
                    self.pending.append(cx)
                    if len(self.pending) >= 2 and abs(self.pending[-1] - self.pending[-2]) < self.crop_w * 0.3:
                        self.target = self.cam = cx
                        self.pending.clear()
                else:
                    self.pending.clear()
                    self.target = cx
        self.frame_no += 1
        delta = self.target - self.cam
        if abs(delta) > self.crop_w * 0.04:  # dead zone avoids jitter
            self.cam += delta * 0.09
        x = int(round(self.cam - self.crop_w / 2))
        return max(0, min(self.frame_w - self.crop_w, x))


def _resolve_layout(info: VideoInfo, opts: RenderOptions) -> str:
    if opts.layout != "auto":
        return opts.layout
    src_ratio = info.width / info.height
    if src_ratio <= opts.width / opts.height + 0.02:
        return "center"  # already vertical
    return "track"


def render_clip(src: Path, info: VideoInfo, start: float, end: float, out_path: Path,
                sentences: list[Sentence], opts: RenderOptions, hook: str = "") -> str:
    """Render one short and return the layout used."""
    out_path = Path(out_path).resolve()
    work = out_path.parent
    ass_name = out_path.stem + ".ass"
    (work / ass_name).write_text(build_ass(sentences, start, end, opts, hook), encoding="utf-8")
    layout = _resolve_layout(info, opts)
    fps = min(info.fps or 30.0, opts.max_fps)
    dur = end - start
    w, h = opts.width, opts.height
    encode = ["-c:v", "libx264", "-preset", "veryfast", "-crf", "21", "-pix_fmt", "yuv420p",
              "-c:a", "aac", "-b:a", "160k", "-movflags", "+faststart"]

    if layout in ("fit", "center"):
        if layout == "fit":
            graph = (
                f"[0:v]fps={fps},split[a][b];"
                f"[a]scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},boxblur=24:3,eq=brightness=-0.1[bg];"
                f"[b]scale={w}:{h}:force_original_aspect_ratio=decrease[fg];"
                f"[bg][fg]overlay=(W-w)/2:(H-h)/2,ass={ass_name}[v]"
            )
        else:
            graph = f"[0:v]fps={fps},scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},ass={ass_name}[v]"
        cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
               "-filter_complex", graph, "-map", "[v]", "-map", "0:a:0?", *encode, str(out_path)]
        proc = subprocess.run(cmd, cwd=work, capture_output=True, check=False)  # nosec B603
        if proc.returncode != 0:
            raise RuntimeError(proc.stderr.decode(errors="replace")[-1500:])
        return layout

    # "track": decode -> Python face tracking crop -> encode with captions
    scaled_w = int(round(info.width * h / info.height / 2) * 2)
    crop_w = min(w, scaled_w)
    decode = subprocess.Popen(  # nosec B603
        ["ffmpeg", "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
         "-vf", f"fps={fps},scale={scaled_w}:{h}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"],
        stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
    )
    with tempfile.TemporaryFile() as err:
        encoder = subprocess.Popen(  # nosec B603
            ["ffmpeg", "-y", "-v", "error",
             "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{crop_w}x{h}", "-r", f"{fps}", "-i", "-",
             "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src),
             "-map", "0:v:0", "-map", "1:a:0?",
             "-vf", f"scale={w}:{h}:force_original_aspect_ratio=increase,crop={w}:{h},ass={ass_name}",
             *encode, "-shortest", str(out_path)],
            stdin=subprocess.PIPE, stderr=err, cwd=work,
        )
        tracker = FaceTracker(scaled_w, crop_w, fps)
        frame_bytes = scaled_w * h * 3
        try:
            while True:
                buf = decode.stdout.read(frame_bytes)
                if len(buf) < frame_bytes:
                    break
                frame = np.frombuffer(buf, np.uint8).reshape(h, scaled_w, 3)
                x = tracker.crop_x(frame)
                encoder.stdin.write(np.ascontiguousarray(frame[:, x : x + crop_w]).tobytes())
        finally:
            decode.stdout.close()
            decode.wait()
            encoder.stdin.close()
            code = encoder.wait()
        if code != 0:
            err.seek(0)
            raise RuntimeError(err.read().decode(errors="replace")[-1500:])
    return layout
