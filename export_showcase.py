"""
export_showcase.py - sanitizing exporter for the Video Studio public demo.

Reads finished project dirs from the private Video Studio workspace and emits a
public-safe bundle under ./site/data/<slug>/:

  output.mp4           720p web re-encode of the FINISHED video, metadata stripped
  edl.json             beats + overlay timings (paths removed, sources anonymised)
  decision.json        brain reasoning, QA verdicts, before/after stats
  contact_sheet.jpg    QA contact sheet of the finished cut
  kw_N.jpg             keyword-pop verification frames

Hard rules (denylist): nothing from raw/, work/, transcripts/, base_preview*,
clips_preview/, overlays*/ (webm), meta.json `output` paths, `regen_notes`
(operator text), or any absolute path. Raw transcripts are reduced to counts only.

After export every text artifact is scanned against SCRUB_PATTERNS and the
export FAILS if any match - nothing is published on a failed scrub.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

# The private workspace is never named in this repo - point VIDEO_STUDIO_PROJECTS at its 01_projects dir.
PRIVATE_ROOT = Path(os.environ.get("VIDEO_STUDIO_PROJECTS") or sys.exit("set VIDEO_STUDIO_PROJECTS"))
OUT_ROOT = Path(__file__).parent / "site" / "data"

# slug -> (project dir, which final/EDL variant to publish)
PICKS = {
    "zipstring-luma-july4": ("app-20260609-zipstring-luma-stars-stripes-july-4th-2389b3", "demo"),
    "levoit-vital-100s": ("app-20260608-levoit-vital-100s-air-purifier-c07aca", None),
    "geoorood-pet-fountain": ("app-20260608-geoorood-pet-water-fountain-95b62a", None),
    "ogery-camping-fan": ("app-20260609-ogery-camping-fan-84415a", "demo"),
    "zipstring-arcana": ("app-20260609-zipstring-arcana-97b73d", "demo"),
}

SCRUB_PATTERNS = [
    r"[A-Za-z]:\\",                 # any Windows absolute path
    r"/Users/",                     # any *nix home path
    r"\bEr" + r"ick\b", r"(?<![a-z])Vander" + r"pool",  # author surname; the public GitHub handle is allowed (split so this file passes its own gate)
    r"\b100\.64\.", r"tailscale",   # tailnet
    r"sk-ant", r"APP_KEY", r"app_key",
    r"[\w.+-]+@[A-Za-z][\w-]*\.[A-Za-z]{2,}",  # email (letters-first domain + alpha TLD)
    r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b",  # phone
    r"\$\s?\d",                     # dollar amounts (commissions / prices)
    r"regen_notes",
]


def ffprobe_duration(p: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(p)],
        capture_output=True, text=True, check=True,
    ).stdout.strip()
    return round(float(out), 2)


def ffprobe_tags(p: Path) -> dict:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format_tags:stream_tags", "-of", "json", str(p)],
        capture_output=True, text=True, check=True,
    ).stdout
    j = json.loads(out)
    tags = dict(j.get("format", {}).get("tags", {}))
    for s in j.get("streams", []):
        tags.update(s.get("tags", {}))
    return tags


def reencode(src: Path, dst: Path) -> None:
    """720p vertical, CRF 26, faststart, ALL metadata stripped."""
    subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(src),
         "-map_metadata", "-1", "-map_chapters", "-1",
         "-vf", "scale=-2:1280", "-c:v", "libx264", "-preset", "slow", "-crf", "26",
         "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)],
        check=True,
    )


def sanitize_edl(edl: dict) -> dict:
    ranges = [
        {k: r[k] for k in ("start", "end", "beat", "motion", "keep") if k in r}
        for r in edl.get("ranges", [])
    ]
    overlays = [
        {k: o[k] for k in ("text", "style", "start_in_output", "duration") if k in o}
        for o in edl.get("overlays", [])
    ]
    return {
        "title": edl.get("title"),
        "theme": edl.get("theme"),
        "notes": edl.get("notes"),
        "grade": edl.get("grade"),
        "pop_style": edl.get("pop_style"),
        "ranges": ranges,
        "overlays": overlays,
    }


def export_one(slug: str, proj: str, variant: str | None) -> dict:
    src = PRIVATE_ROOT / proj
    dst = OUT_ROOT / slug
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)

    meta = json.loads((src / "meta.json").read_text(encoding="utf-8"))
    if variant:
        edl_path = src / "edit" / f"auto_edl_{variant}.json"
        final_path = src / "final" / f"edited_{variant}.mp4"
        qa_dir = src / "qa" / variant
        v = next(x for x in meta["variants"] if x["style"] == variant)
        reason, notes, theme, qa, segments = v["reason"], v["notes"], v["theme"], v["qa"], v["segments"]
        other_variants = [
            {"style": x["style"], "theme": x["theme"], "reason": x["reason"], "duration": x["qa"]["video_dur"]}
            for x in meta["variants"] if x["style"] != variant
        ]
    else:
        edl_path = src / "edit" / "auto_edl.json"
        final_path = src / "final" / "edited.mp4"
        qa_dir = src / "qa"
        reason, notes, theme = None, meta.get("notes"), meta.get("theme")
        qa, segments, other_variants = meta.get("qa", {}), meta.get("segments"), []

    edl = json.loads(edl_path.read_text(encoding="utf-8"))
    if notes is None:
        notes = edl.get("notes")
    if theme is None:
        theme = edl.get("theme")

    # ---- video: re-encode finished output only ----
    reencode(final_path, dst / "output.mp4")
    tags = ffprobe_tags(dst / "output.mp4")
    # muxer defaults only - anything else (location, creation_time, device make/model, comment) fails
    BENIGN = ("major_brand", "minor_version", "compatible_brands", "encoder", "language", "handler_name", "vendor_id")
    leaky = {k: v for k, v in tags.items() if k.lower() not in BENIGN}
    if leaky:
        raise SystemExit(f"[{slug}] output.mp4 still carries tags: {leaky}")

    # ---- stats derived from raw/transcript (numbers only, never content) ----
    raw_dur = ffprobe_duration(src / "raw" / "clip01.mov")
    out_dur = ffprobe_duration(dst / "output.mp4")
    tpath = src / "edit" / "transcripts" / "clip01.json"
    words_raw = len(json.loads(tpath.read_text(encoding="utf-8")).get("words", [])) if tpath.exists() else None
    kept = sum(r["end"] - r["start"] for r in edl.get("ranges", []))

    # ---- QA images ----
    cs = qa_dir / "contact_sheet.png"
    if cs.exists():
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(cs), "-map_metadata", "-1",
                        "-vf", "scale=1200:-2", "-q:v", "4", str(dst / "contact_sheet.jpg")], check=True)
    kw_frames = []
    for i, f in enumerate(sorted(qa_dir.glob("kw_*.jpg"))):
        name = f"kw_{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", str(f), "-map_metadata", "-1",
                        "-vf", "scale=480:-2", "-q:v", "5", str(dst / name)], check=True)
        kw_frames.append(name)

    (dst / "edl.json").write_text(json.dumps(sanitize_edl(edl), indent=2), encoding="utf-8")
    decision = {
        "slug": slug,
        "title": meta.get("title") or edl.get("title"),
        "variant": variant or "single",
        "theme": theme,
        "brain_reason": reason,
        "edit_notes": notes,
        "grade": edl.get("grade"),
        "compliance_dropped": meta.get("compliance_dropped", []),
        "other_variants": other_variants,
        "stats": {
            "raw_duration_s": raw_dur,
            "output_duration_s": out_dur,
            "kept_ratio": round(out_dur / raw_dur, 3),
            "segments": segments or len(edl.get("ranges", [])),
            "kept_span_s": round(kept, 2),
            "transcribed_words": words_raw,
            "overlays": len(edl.get("overlays", [])),
        },
        "qa": {k: qa.get(k) for k in ("video_dur", "audio_dur", "av_drift", "sync_ok", "black_ok")},
        "qa_frames": kw_frames,
        "has_contact_sheet": (dst / "contact_sheet.jpg").exists(),
    }
    (dst / "decision.json").write_text(json.dumps(decision, indent=2), encoding="utf-8")
    return decision


def scrub_gate(root: Path) -> None:
    hits = []
    for p in root.rglob("*"):
        if ".git" in p.parts or "__pycache__" in p.parts:
            continue
        if p.suffix.lower() in (".json", ".md", ".txt", ".html", ".js", ".css"):
            text = p.read_text(encoding="utf-8", errors="replace")
            for pat in SCRUB_PATTERNS:
                for m in re.finditer(pat, text, flags=re.I):
                    hits.append(f"{p.relative_to(root)} :: /{pat}/ :: {text[max(0,m.start()-30):m.end()+30]!r}")
    if hits:
        print("SCRUB GATE FAILED:\n  " + "\n  ".join(hits))
        sys.exit(1)
    print(f"scrub gate: clean ({len(SCRUB_PATTERNS)} patterns over {root})")


if __name__ == "__main__":
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    index = []
    for slug, (proj, variant) in PICKS.items():
        d = export_one(slug, proj, variant)
        s = d["stats"]
        print(f"{slug:24s} {s['raw_duration_s']:6.1f}s -> {s['output_duration_s']:5.1f}s  segs={s['segments']}  pops={s['overlays']}")
        index.append({k: d[k] for k in ("slug", "title", "variant", "theme", "stats", "qa")})
    (OUT_ROOT / "index.json").write_text(json.dumps(index, indent=2), encoding="utf-8")
    scrub_gate(Path(__file__).parent)  # whole repo, this script included
