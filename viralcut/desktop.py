"""Desktop launcher used by the Windows app (ViralCut.exe).

Starts the ViralCut server on this computer only, opens the browser, and keeps
running until the window is closed. `ViralCut.exe --selftest` renders a short
test clip to prove FFmpeg, OpenCV and captions work inside the packaged app.
"""

from __future__ import annotations

import os
import socket
import sys
import threading
import time
import urllib.request
import webbrowser
from pathlib import Path

PREFERRED_PORT = 8000


def _bundle_dir() -> Path:
    """Folder holding the packaged resources (PyInstaller) or the repo checkout."""
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))


def _prepare_environment() -> None:
    bundle = _bundle_dir()
    ffmpeg_dir = bundle / "ffmpeg"
    if ffmpeg_dir.is_dir():
        os.environ["PATH"] = str(ffmpeg_dir) + os.pathsep + os.environ.get("PATH", "")
    font = bundle / "fonts" / "Anton-Regular.ttf"
    if font.is_file():
        os.environ.setdefault("VIRALCUT_FONT_FILE", str(font))
        os.environ.setdefault("VIRALCUT_FONT", "Anton")
    if "VIRALCUT_DATA" not in os.environ:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        os.environ["VIRALCUT_DATA"] = str(Path(base) / "ViralCut")
    Path(os.environ["VIRALCUT_DATA"]).mkdir(parents=True, exist_ok=True)
    from viralcut import config  # pylint: disable=import-outside-toplevel

    config.load_settings()  # the saved API key lives in the data folder chosen above


def _already_running(port: int) -> bool:
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/healthz", timeout=1) as resp:  # nosec B310
            return resp.status == 200
    except OSError:
        return False


def _free_port() -> int:
    for port in [PREFERRED_PORT, *range(8001, 8020)]:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            if s.connect_ex(("127.0.0.1", port)) != 0:
                return port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def run() -> None:
    _prepare_environment()
    if _already_running(PREFERRED_PORT):
        webbrowser.open(f"http://127.0.0.1:{PREFERRED_PORT}")
        return

    import uvicorn  # pylint: disable=import-outside-toplevel

    from viralcut.app import app  # pylint: disable=import-outside-toplevel

    port = _free_port()
    url = f"http://127.0.0.1:{port}"
    print("=" * 60)
    print("  ViralCut is running at", url)
    print("  Your browser will open automatically.")
    print("  Keep this window open while you work. Close it to quit.")
    print("  Projects are saved in", os.environ["VIRALCUT_DATA"])
    print("=" * 60)

    def open_browser() -> None:
        for _ in range(60):
            if _already_running(port):
                break
            time.sleep(0.5)
        webbrowser.open(url)

    threading.Thread(target=open_browser, daemon=True).start()
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")


def selftest() -> int:
    """Render one captioned short from a generated test video. Exit code 0 = everything works."""
    import tempfile  # pylint: disable=import-outside-toplevel

    _prepare_environment()
    from viralcut import media  # pylint: disable=import-outside-toplevel
    from viralcut.pipeline import JobSettings, JobStore, run_job  # pylint: disable=import-outside-toplevel

    media.require_ffmpeg()
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        video = tmp_path / "test.mp4"
        media.run([
            "ffmpeg", "-y", "-v", "error",
            "-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=30:duration=24",
            "-f", "lavfi", "-i", "sine=frequency=440:duration=24",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(video),
        ])
        lines = [
            "Why is nobody talking about this?", "Here is the secret that changed everything.",
            "Most people quit in month two.", "I tried it for thirty days and it worked.",
            "So what are you waiting for?", "Follow for more tips like this.",
        ]
        srt = "\n".join(
            f"{i + 1}\n00:00:{i * 4:02d},000 --> 00:00:{i * 4 + 3:02d},500\n{text}\n" for i, text in enumerate(lines)
        )
        store = JobStore(tmp_path / "jobs")
        for layout in ("track", "fit"):
            job = store.create("test.mp4", JobSettings.from_dict(
                {"clip_count": 1, "min_len": 5, "max_len": 12, "layout": layout, "use_ai": False}))
            run_job(store, job, video_path=video, subtitles=srt)
            clip = store.dir(job.id) / "clip_01.mp4"
            ok = job.status == "done" and clip.exists() and clip.stat().st_size > 10_000
            print(f"[{layout}] status={job.status} error={job.error!r} clip={clip.stat().st_size if clip.exists() else 0} bytes")
            if not ok:
                return 1
            info = media.probe(clip)
            print(f"[{layout}] output {info.width}x{info.height}, {info.duration:.1f}s, audio={info.has_audio}")
            if (info.width, info.height) != (720, 1280):
                return 1
    import ctranslate2  # noqa: F401 pylint: disable=import-outside-toplevel,unused-import
    import faster_whisper  # noqa: F401 pylint: disable=import-outside-toplevel,unused-import
    import yt_dlp  # noqa: F401 pylint: disable=import-outside-toplevel,unused-import

    from viralcut.app import app  # noqa: F401 pylint: disable=import-outside-toplevel,unused-import

    print("SELFTEST OK")
    return 0


def main() -> None:
    for stream in (sys.stdout, sys.stderr):
        if stream is not None and hasattr(stream, "reconfigure"):
            stream.reconfigure(errors="replace")  # Windows consoles can't print every character
    if "--selftest" in sys.argv:
        sys.exit(selftest())
    try:
        run()
    except Exception as exc:  # pylint: disable=broad-except
        print("\nViralCut could not start:", exc)
        input("Press Enter to close this window…")
        raise


if __name__ == "__main__":
    main()
