# ⚡ ViralCut: long video → viral shorts

ViralCut is a self-hosted AI clipping studio, like OpusClip or ScaleReach. You paste a link or upload a long video
(podcast, stream, interview, talk), and it gives you ready-to-post 9:16 shorts plus posts and hashtags for every platform.

## What it does

| Step | How |
|---|---|
| **Import** | Upload any video file, or paste a YouTube / Twitch / Kick / Vimeo / X / Drive / Dropbox link (via `yt-dlp`). |
| **Transcribe** | Uses [faster-whisper](https://github.com/SYSTRAN/faster-whisper) with word-level timestamps, or reads an `.srt` / `.vtt` you upload. |
| **Find viral moments** | Scores every candidate window on hook strength (first 3 s), vocal energy peaks, emotional and curiosity language, pacing, topic relevance, and whether it ends on a complete thought. With no speech at all, it still finds loudness peaks. |
| **AI picks and copywriting** | When `ANTHROPIC_API_KEY` is set, Claude chooses the best clips and writes a title, an on-screen hook, a virality score, the reason it will perform, a native post for **TikTok, Instagram Reels, YouTube Shorts, X and LinkedIn**, and per-platform **hashtags** (broad and niche). Without a key, built-in heuristics write the copy offline. |
| **Reframe to 9:16** | *Face tracking* keeps the speaker centred with smooth camera moves and cuts on speaker changes. You can also use *blurred-background fit* or *center crop*. |
| **Animated captions** | Burned-in word-by-word captions with the active word highlighted (Bold pop, Karaoke, Neon, Minimal), plus a hook title for the first 3 seconds. |
| **Publish** | Download each clip or the whole set as a ZIP (each clip comes with a text file of its posts), copy the posts, and plan a **posting schedule** with suggested peak times. The schedule exports to your calendar as `.ics`. |

## Quick start

```bash
# 1. Install FFmpeg (https://ffmpeg.org) - e.g. `brew install ffmpeg` / `sudo apt install ffmpeg` / `winget install ffmpeg`
# 2. Install Python deps (Python 3.10+)
pip install -r viralcut/requirements.txt
# 3. Optional: enable Claude for the best clip picks + copy
export ANTHROPIC_API_KEY=sk-ant-...
# 4. Run (from the repository root)
uvicorn viralcut.app:app --host 0.0.0.0 --port 8000
```

Open <http://localhost:8000>, paste a link or drop a video, and click **Generate viral clips**.

The first run downloads the Whisper model (`small`, ~500 MB). On a GPU machine it's much faster. Set
`device`/`compute_type` in `viralcut/transcript.py` if you want to force CUDA.

### Docker

```bash
docker build -t viralcut -f viralcut/Dockerfile .
docker run -p 8000:8000 -e ANTHROPIC_API_KEY=$ANTHROPIC_API_KEY -v $PWD/viralcut_data:/app/viralcut_data viralcut
```

## Deploy online

ViralCut needs a real server, not static hosting: it runs FFmpeg, Whisper and OpenCV. Plan for at least
**2 GB RAM** (4 GB+ for long videos) and a persistent disk for projects.

### Render (easiest, ~$25/month for the 2 GB plan + disk)

1. Push this repo to GitHub (already done if you're reading this there).
2. In [Render](https://dashboard.render.com): **New → Blueprint**, pick this repository and branch.
   Render reads [`render.yaml`](../render.yaml), builds `viralcut/Dockerfile` and attaches a 20 GB disk.
3. When asked, fill in **`ANTHROPIC_API_KEY`** and a **`VIRALCUT_PASSWORD`**.
4. Open the `https://viralcut-xxxx.onrender.com` URL. Your browser asks for a password: enter any username and your `VIRALCUT_PASSWORD`.

### Railway / Fly.io / Google Cloud Run / any VPS

All of them can build `viralcut/Dockerfile` directly (build context = repo root). The container listens on `$PORT`.
Set the same environment variables and mount a volume at the path in `VIRALCUT_DATA`.
On a VPS: `docker build -t viralcut -f viralcut/Dockerfile . && docker run -d -p 80:8000 --env-file .env -v /srv/viralcut:/app/viralcut_data viralcut`.

> **Always set `VIRALCUT_PASSWORD` on a public server.** Without it anyone who finds the URL can process videos
> on your server and spend your Claude API credits.

## Configuration (environment variables)

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | – | Enables Claude clip selection and copywriting |
| `VIRALCUT_MODEL` | `claude-opus-5-5` | Claude model to use |
| `VIRALCUT_DATA` | `./viralcut_data` | Where projects, clips and transcripts are stored |
| `VIRALCUT_WORKERS` | `1` | Videos processed in parallel |
| `VIRALCUT_FONT` | `Arial Black` | Caption font (any installed font; e.g. `Montserrat Black`) |
| `VIRALCUT_PASSWORD` | – | Password for the whole site (HTTP Basic auth, any username) |
| `VIRALCUT_WHISPER_MODEL` | `small` | Whisper size: `tiny`, `base`, `small`, `medium`, `large-v3` (bigger = more accurate, more RAM) |
| `PORT` | `8000` | Port the Docker container listens on |

## API

| Method | Path | |
|---|---|---|
| `POST` | `/api/jobs` | multipart: `file` **or** `url`, optional `subtitles`, `settings` JSON (`clip_count`, `min_len`, `max_len`, `layout`, `caption_style`, `show_hook`, `use_ai`, `resolution`) |
| `GET` | `/api/jobs/{id}` | status, progress and clips with posts and hashtags |
| `GET` | `/api/jobs/{id}/files/clip_01.mp4` | rendered short (also `.jpg` thumbnail, `transcript.txt`) |
| `GET` | `/api/jobs/{id}/export.zip` | all clips + post text files |
| `POST` | `/api/jobs/{id}/schedule` | `{clip_id, platform, time, caption}` |
| `GET` | `/api/jobs/{id}/schedule.ics` | posting schedule as a calendar |

## Tests

```bash
pip install pytest
python -m pytest viralcut/tests
```

## Notes

* Auto-posting directly to TikTok/Instagram/YouTube needs each platform's developer app approval and OAuth.
  ViralCut prepares the clips, captions, hashtags and the schedule, and puts posting reminders in your calendar.
* Only process videos you own or have permission to repurpose.
