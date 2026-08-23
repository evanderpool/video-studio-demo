# Video Studio — public demo

Five finished short-form videos cut by an LLM editing brain, each shown with its
complete decision trace: the beats it kept (and where they sat in the raw take),
the keyword pops it authored and timed, its reasoning, alternate cuts it
produced, and the automated QA verdict on the render.

**[Read the full case study →](https://evanderpool.github.io/video-studio-demo/case-study.html)** — architecture, the swappable brain seam, prompting design, the compliance backstop, and the measured 66-video rollup. Source: [CASE-STUDY.md](CASE-STUDY.md), rendered by `render_case_study.py`.

**The production system is local-first and private by design.** This site is a
read-only export of its *outputs and artifacts* — no server, no uploads, no
API calls. Raw footage, transcripts, and analytics never leave the machine.
(A rate-limited upload-and-cut service was built and tested, then deliberately
not deployed: a public host would have to accept strangers' video, and the
project's privacy posture is worth more than the demo. It lives in git history.)

## The brain seam (demo vs. production)

The production Video Studio routes every editing decision through one JSON
contract with **three interchangeable backends**:

| backend | where it runs | cost | used for |
|---|---|---|---|
| local rules (heuristic) | in-process | free | offline fallback; **this public demo** |
| live Claude session | desktop, attended | flat subscription | production default — reads transcript + sampled frames, writes the decision file |
| Anthropic API | server, unattended | cents / video, capped | phone-sent jobs |

The five gallery videos were cut by the Claude backends (their reasoning is
shown verbatim). A public upload path would run the local-rules backend only — no model spend for anonymous traffic, no key on a public host.

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
