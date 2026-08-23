---
title: Video Studio Demo
emoji: 🎬
colorFrom: yellow
colorTo: gray
sdk: docker
app_port: 7860
pinned: false
---

# Video Studio — public demo

Five finished short-form videos cut by an LLM editing brain, each shown with its
complete decision trace: the beats it kept (and where they sat in the raw take),
the keyword pops it authored and timed, its reasoning, alternate cuts it
produced, and the automated QA verdict on the render.

**The production system is local-first and private by design.** The gallery is
a read-only export of its *outputs and artifacts*. The **Try it** section runs
a deliberately small, isolated re-implementation of the same stages on a
5–60 s clip you upload — it is not the private app exposed.

## Try-it service (`server/`)

`normalize → faster-whisper (small.en, CPU) → brain → FFmpeg render → QA → trace`

Built for anonymous internet users, so:

| control | value (env) |
|---|---|
| clip length | `MIN_SECONDS=5` … `MAX_SECONDS=60` — checked with ffprobe before any work |
| upload size | `MAX_UPLOAD_MB=80`, streamed to disk, connection cut on overflow |
| file types | mp4 / mov / webm / m4v; must contain a video **and** an audio stream |
| rate limits | `PER_IP_PER_HOUR=3`, `GLOBAL_PER_DAY=60`, `QUEUE_MAX=4` (only *accepted* clips count) |
| proxy trust | `TRUST_PROXY=1` reads the last `X-Forwarded-For` hop (the platform proxy) |
| retention | `RETENTION_MIN=30` — job dir deleted after that, or immediately on failure |
| brain | **`BRAIN=heuristic` (the default and what the public Space runs): local rules, no model call, no network.** `BRAIN=api` + `ANTHROPIC_API_KEY` enables Claude, capped by `DAILY_API_CAP=30`, always falling back to heuristic |
| process | one worker thread; every subprocess is an arg list (no shell); paths are server-built; job ids are 96-bit random; docs/openapi disabled |
| output | 720×1280, all metadata stripped, `Cache-Control: no-store` |

The static gallery still works with no server at all (GitHub Pages / Vercel);
the Try-it section only appears when `/api/health` answers.

### The brain seam (demo vs. production)

The production Video Studio routes every editing decision through one JSON
contract with **three interchangeable backends**:

| backend | where it runs | cost | used for |
|---|---|---|---|
| local rules (heuristic) | in-process | free | offline fallback; **this public demo** |
| live Claude session | desktop, attended | flat subscription | production default — reads transcript + sampled frames, writes the decision file |
| Anthropic API | server, unattended | cents / video, capped | phone-sent jobs |

The five gallery videos were cut by the Claude backends (their reasoning is
shown verbatim). The Try-it service ships with the local-rules backend on
purpose: no model spend for anonymous traffic, no key on the public host, and
nothing leaves the container. Flip `BRAIN=api` with a key to see the model path.

## Run the service locally

```
pip install -r requirements.txt          # needs ffmpeg on PATH
uvicorn server.app:app --port 7860
```

## How this bundle is produced

`export_showcase.py` reads finished project folders from the private workspace
and writes `site/data/<slug>/`:

| file | what | what's stripped |
|---|---|---|
| `output.mp4` | 720p re-encode of the finished cut | all container/stream metadata (`-map_metadata -1`) |
| `edl.json` | beats + overlay timings | source paths, overlay file paths |
| `decision.json` | reasoning, QA, before/after stats | output paths, operator notes; transcript reduced to a word count |
| `contact_sheet.jpg`, `kw_*.jpg` | QA frames | image metadata |

Then a **scrub gate** regex-scans every text file in `site/` for absolute paths,
author identity, tailnet addresses, key names, emails, phone numbers, and dollar
amounts. Any hit fails the export. The re-encoded video is also probed and fails
if any non-muxer tag survives.

## Run locally

```
python -m http.server 8000 --bind 127.0.0.1 --directory site
```

## Stack behind the outputs

Python · FastAPI · Anthropic Claude (multimodal) · faster-whisper · FFmpeg · HyperFrames
