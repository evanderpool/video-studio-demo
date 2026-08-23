"""
Demo pipeline: one uploaded clip -> transcript -> EDL -> render -> QA -> trace.

Deliberately small and dependency-light (FFmpeg + faster-whisper, optional Anthropic).
Every subprocess is an arg list (no shell). Every path is server-controlled.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import time
from collections import Counter
from pathlib import Path

MAX_OUTPUT_S = float(os.environ.get("MAX_OUTPUT_S", "40"))
FONT = os.environ.get("CAPTION_FONT", "DejaVu Sans")
FONT_FILE = os.environ.get("CAPTION_FONT_FILE", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf")
W, H = 720, 1280


# ---------------------------------------------------------------- ffmpeg helpers
def run(cmd: list[str], timeout: float = 600, cwd: Path | None = None) -> str:
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=cwd)
    if p.returncode != 0:
        raise RuntimeError(f"{cmd[0]} failed: {p.stderr[-800:]}")
    return p.stdout


def probe(path: Path) -> dict:
    out = run(["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height",
               "-of", "json", str(path)])
    j = json.loads(out)
    kinds = [s.get("codec_type") for s in j.get("streams", [])]
    vid = next((s for s in j.get("streams", []) if s.get("codec_type") == "video"), {})
    return {
        "duration": float(j.get("format", {}).get("duration") or 0),
        "has_video": "video" in kinds,
        "has_audio": "audio" in kinds,
        "width": vid.get("width"), "height": vid.get("height"),
    }


def normalize(src: Path, dst: Path) -> None:
    """Re-encode to 720x1280 vertical (letterbox if needed), strip metadata, 30fps, AAC."""
    vf = (f"scale={W}:{H}:force_original_aspect_ratio=decrease,"
          f"pad={W}:{H}:(ow-iw)/2:(oh-ih)/2:color=black,fps=30,format=yuv420p")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-map_metadata", "-1", "-map_chapters", "-1",
         "-vf", vf, "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
         "-c:a", "aac", "-b:a", "128k", "-ar", "48000", "-ac", "2", "-movflags", "+faststart", str(dst)])


def extract_wav(src: Path, dst: Path) -> None:
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-vn", "-ac", "1", "-ar", "16000", "-c:a", "pcm_s16le", str(dst)])


# ---------------------------------------------------------------- transcription
_model = None


def transcribe(wav: Path) -> list[dict]:
    global _model
    from faster_whisper import WhisperModel
    if _model is None:
        _model = WhisperModel(os.environ.get("WHISPER_MODEL", "small.en"), device="cpu", compute_type="int8")
    segments, _info = _model.transcribe(str(wav), word_timestamps=True, vad_filter=True, beam_size=3)
    words = []
    for seg in segments:
        for w in seg.words or []:
            t = (w.word or "").strip()
            if t:
                words.append({"text": t, "start": round(w.start, 2), "end": round(w.end, 2)})
    return words


# ---------------------------------------------------------------- heuristic brain
def phrase_ranges(words: list[dict], gap_max=0.7, pad_head=0.12, pad_tail=0.3) -> list[dict]:
    if not words:
        return []
    phrases, cur = [], [words[0]]
    for prev, w in zip(words, words[1:]):
        if w["start"] - prev["end"] > gap_max:
            phrases.append(cur); cur = [w]
        else:
            cur.append(w)
    phrases.append(cur)
    out = []
    for i, ph in enumerate(phrases):
        start = max(0.0, ph[0]["start"] - pad_head)
        end = ph[-1]["end"] + pad_tail
        if i + 1 < len(phrases):
            end = min(end, phrases[i + 1][0]["start"] - 0.05)
        if end - start < 0.25:
            continue
        out.append({"start": round(start, 2), "end": round(end, 2),
                    "beat": " ".join(x["text"] for x in ph)[:70]})
    return out


STOP = {"because", "before", "around", "different", "multiple", "anything", "everything", "something",
        "actually", "basically", "literally", "probably", "another", "really", "question", "without",
        "through", "between", "people", "little", "better", "always", "though", "having", "gonna",
        "wanna", "right", "there", "these", "those", "about", "where", "which", "while", "being",
        "other", "stuff", "thing", "things", "pretty", "could", "would", "should", "their", "going"}
POWER = {"free", "limited", "finally", "secret", "instant", "proof", "guaranteed", "never", "easiest",
         "fastest", "cheapest", "favorite", "honestly", "insane", "crazy", "game-changer", "obsessed"}
UNITS = {"liter", "liters", "ounce", "ounces", "gallon", "percent", "inch", "inches", "pound", "pounds",
         "hour", "hours", "day", "days", "minute", "minutes", "watt", "watts", "feet", "year", "years",
         "ml", "oz", "lb", "lbs", "mph", "modes", "speeds", "colors", "pack", "count", "pieces"}
NUM = re.compile(r"^\$?\d[\d.,]*$")


def output_words(ranges: list[dict], words: list[dict]) -> list[tuple[float, float, str]]:
    """words mapped to OUTPUT time: (start, end, text)."""
    out, off = [], 0.0
    for r in ranges:
        for w in words:
            if r["start"] <= w["start"] < r["end"]:
                s = off + (w["start"] - r["start"])
                e = min(off + (r["end"] - r["start"]), off + (w["end"] - r["start"]))
                out.append((round(s, 2), round(max(e, s + 0.05), 2), w["text"]))
        off += r["end"] - r["start"]
    return out


def select_pops(ranges: list[dict], words: list[dict], max_n=4, min_gap=3.5) -> list[dict]:
    seq = output_words(ranges, words)
    clean = lambda t: re.sub(r"[^A-Za-z]", "", t).lower()
    freq = Counter(clean(t) for _, _, t in seq if len(clean(t)) >= 5 and clean(t) not in STOP)
    top = {w for w, c in freq.most_common(2) if c >= 2}
    cands = []
    for i, (s, _e, t) in enumerate(seq):
        c = clean(t)
        if NUM.match(t.strip(".,!?")) and i + 1 < len(seq) and clean(seq[i + 1][2]) in UNITS:
            cands.append((s, f"{t.strip('.,!?')} {seq[i+1][2].strip('.,!?')}".upper(), 3))
        elif c in POWER:
            cands.append((s, c.upper(), 2))
        elif c in top:
            cands.append((s, c.upper(), 1))
    cands.sort(key=lambda x: (-x[2], x[0]))
    chosen: list[dict] = []
    for s, text, _p in cands:
        if all(abs(s - o["start_in_output"]) >= min_gap for o in chosen) and text not in {o["text"] for o in chosen}:
            chosen.append({"text": text, "start_in_output": round(max(0.0, s - 0.1), 2), "duration": 1.8})
        if len(chosen) >= max_n:
            break
    chosen.sort(key=lambda o: o["start_in_output"])
    return chosen


def fit_to_budget(ranges: list[dict], budget: float) -> list[dict]:
    """Keep the first spans that fit, always keeping the last one (the CTA) if possible."""
    total = sum(r["end"] - r["start"] for r in ranges)
    if total <= budget or len(ranges) < 3:
        return ranges
    keep, acc = [], 0.0
    last = ranges[-1]
    for r in ranges[:-1]:
        d = r["end"] - r["start"]
        if acc + d + (last["end"] - last["start"]) > budget:
            break
        keep.append(r); acc += d
    keep.append(last)
    return keep


def heuristic_brain(words: list[dict]) -> dict:
    ranges = fit_to_budget(phrase_ranges(words), MAX_OUTPUT_S)
    for i, r in enumerate(ranges):
        r["motion"] = "in" if i % 2 == 0 else "out"
    return {
        "brain": "heuristic",
        "theme": "Dead air removed, phrases kept in order, rule-based keyword pops.",
        "reason": "Offline rules: split on pauses > 0.7s, drop the silence, pop number+unit phrases, "
                  "power words, and the most-repeated product term.",
        "ranges": ranges,
        "overlays": select_pops(ranges, words),
    }


# ---------------------------------------------------------------- API brain (optional, capped)
BRAIN_SYSTEM = (
    "You are a short-form video editor. You receive the word-level transcript of ONE raw talking-head take "
    "as numbered phrases with timestamps. Produce a tight retention cut: hook first, proof/demo protected, "
    "a clear CTA last. Keep phrases VERBATIM by index (you may trim a phrase by giving a sub-range inside it). "
    f"Total kept duration must be <= {int(MAX_OUTPUT_S)} seconds. Also author up to 4 short on-screen keyword "
    "pops (2-4 words, ALL CAPS, factual — no claims not said on camera) each tied to a phrase index. "
    "Return ONLY JSON: {\"theme\": str, \"reason\": str, \"ranges\": [{\"i\": int, \"start\": float, \"end\": float, "
    "\"beat\": str}], \"pops\": [{\"i\": int, \"text\": str}]}"
)


def api_brain(words: list[dict]) -> dict | None:
    try:
        import anthropic
    except ImportError:
        return None
    phrases = phrase_ranges(words)
    if not phrases:
        return None
    payload = [{"i": i, "start": p["start"], "end": p["end"], "text": p["beat"]} for i, p in enumerate(phrases)]
    client = anthropic.Anthropic()
    msg = client.messages.create(
        model=os.environ.get("BRAIN_MODEL", "claude-sonnet-5"), max_tokens=1200, system=BRAIN_SYSTEM,
        messages=[{"role": "user", "content": json.dumps({"phrases": payload})}],
    )
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    m = re.search(r"\{.*\}", text, re.S)
    if not m:
        return None
    d = json.loads(m.group(0))
    ranges = []
    for r in d.get("ranges", []):
        i = int(r.get("i", -1))
        if not 0 <= i < len(phrases):
            continue
        p = phrases[i]
        s = max(p["start"], float(r.get("start", p["start"])))
        e = min(p["end"], float(r.get("end", p["end"])))
        if e - s >= 0.3:
            ranges.append({"start": round(s, 2), "end": round(e, 2), "beat": str(r.get("beat") or p["beat"])[:70], "_i": i})
    if not ranges:
        return None
    ranges = fit_to_budget(ranges, MAX_OUTPUT_S)
    for k, r in enumerate(ranges):
        r["motion"] = "in" if k % 2 == 0 else "out"
    # map pops to output time via phrase index
    off, starts = 0.0, {}
    for r in ranges:
        starts.setdefault(r["_i"], off)
        off += r["end"] - r["start"]
    pops = []
    for p in d.get("pops", [])[:4]:
        i = int(p.get("i", -1))
        t = re.sub(r"[^A-Z0-9 %$.'-]", "", str(p.get("text", "")).upper())[:28].strip()
        if i in starts and t:
            pops.append({"text": t, "start_in_output": round(starts[i] + 0.15, 2), "duration": 1.8})
    for r in ranges:
        r.pop("_i", None)
    return {"brain": "api", "theme": str(d.get("theme", ""))[:200], "reason": str(d.get("reason", ""))[:600],
            "ranges": ranges, "overlays": pops}


# ---------------------------------------------------------------- render
def _esc(t: str) -> str:
    return t.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'").replace("%", "\\%")


def write_srt(ranges: list[dict], words: list[dict], path: Path) -> None:
    ws = output_words(ranges, words)
    # group into 3-4 word caption chunks
    chunks, cur = [], []
    for w in ws:
        cur.append(w)
        if len(cur) >= 4 or w[2].rstrip().endswith((".", "?", "!", ",")):
            chunks.append(cur); cur = []
    if cur:
        chunks.append(cur)
    fmt = lambda s: time.strftime("%H:%M:%S", time.gmtime(s)) + f",{int((s % 1) * 1000):03d}"
    lines = []
    for n, ch in enumerate(chunks, 1):
        s, e = ch[0][0], max(ch[-1][1], ch[0][0] + 0.4)
        lines += [str(n), f"{fmt(s)} --> {fmt(e)}", " ".join(w[2] for w in ch).upper(), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def render(src: Path, decision: dict, words: list[dict], out: Path, workdir: Path) -> None:
    ranges, pops = decision["ranges"], decision["overlays"]
    srt = workdir / "captions.srt"
    write_srt(ranges, words, srt)
    parts, maps = [], ""
    for k, r in enumerate(ranges):
        z = 1.08 if r.get("motion") == "in" else 1.0
        cw, ch = int(W / z) // 2 * 2, int(H / z) // 2 * 2
        parts.append(f"[0:v]trim=start={r['start']}:end={r['end']},setpts=PTS-STARTPTS,"
                     f"crop={cw}:{ch}:(iw-{cw})/2:(ih-{ch})/2,scale={W}:{H}[v{k}];"
                     f"[0:a]atrim=start={r['start']}:end={r['end']},asetpts=PTS-STARTPTS[a{k}];")
        maps += f"[v{k}][a{k}]"
    n = len(ranges)
    chain = "".join(parts) + f"{maps}concat=n={n}:v=1:a=1[cv][ca];"
    # keyword pops: boxed drawtext, upper-third
    vfs = []
    font_file = FONT_FILE.replace("\\", "/").replace(":", "\:")
    for p in pops:
        s, e = p["start_in_output"], p["start_in_output"] + p["duration"]
        vfs.append(f"drawtext=fontfile='{font_file}':text='{_esc(p['text'])}':fontsize=54:fontcolor=0x1a1204:"
                   f"box=1:boxcolor=0xffb323@0.95:boxborderw=18:x=(w-text_w)/2:y=h*0.22:"
                   f"enable='between(t,{s},{e})'")
    # ffmpeg runs with cwd=workdir so the SRT is a bare relative name - no path escaping to get wrong
    vfs.append(f"subtitles=captions.srt:force_style='FontName={FONT},FontSize=15,Bold=1,PrimaryColour=&H00FFFFFF,"
               f"OutlineColour=&H80000000,BorderStyle=1,Outline=2,Shadow=0,Alignment=2,MarginV=42'")
    chain += "[cv]" + ",".join(vfs) + "[vout];[ca]loudnorm=I=-14:TP=-1.5:LRA=11[aout]"
    script = workdir / "filter.txt"
    script.write_text(chain, encoding="utf-8")
    run(["ffmpeg", "-y", "-v", "error", "-i", str(src), "-filter_complex_script", "filter.txt",
         "-map", "[vout]", "-map", "[aout]", "-map_metadata", "-1",
         "-c:v", "libx264", "-preset", "veryfast", "-crf", "23", "-c:a", "aac", "-b:a", "128k",
         "-movflags", "+faststart", str(out)], timeout=900, cwd=workdir)


def qa(out: Path, workdir: Path) -> dict:
    j = json.loads(run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type,duration", "-of", "json", str(out)]))
    vd = ad = 0.0
    for s in j.get("streams", []):
        if s.get("codec_type") == "video": vd = float(s.get("duration") or 0)
        if s.get("codec_type") == "audio": ad = float(s.get("duration") or 0)
    black = subprocess.run(["ffmpeg", "-v", "info", "-i", str(out), "-vf", "blackdetect=d=0.3:pic_th=0.98", "-an", "-f", "null", "-"],
                           capture_output=True, text=True).stderr
    # contact sheet: 12 frames
    run(["ffmpeg", "-y", "-v", "error", "-i", str(out), "-vf", f"fps=12/{max(vd,1)},scale=180:-2,tile=6x2",
         "-frames:v", "1", "-q:v", "5", str(workdir / "contact_sheet.jpg")])
    return {"video_dur": round(vd, 1), "audio_dur": round(ad, 1), "av_drift": round(abs(vd - ad), 2),
            "sync_ok": abs(vd - ad) < 0.25, "black_ok": "black_start" not in black}


# ---------------------------------------------------------------- orchestrate
def process(job_dir: Path, set_status) -> dict:
    upload = next(job_dir.glob("upload.*"))
    norm, wav, out = job_dir / "norm.mp4", job_dir / "audio.wav", job_dir / "output.mp4"

    set_status("normalizing")
    normalize(upload, norm)
    upload.unlink(missing_ok=True)
    raw_dur = probe(norm)["duration"]

    set_status("transcribing")
    extract_wav(norm, wav)
    words = transcribe(wav)
    wav.unlink(missing_ok=True)
    if len(words) < 4:
        raise RuntimeError("Could not hear enough speech in the clip — the demo needs a talking take.")

    set_status("deciding")
    decision = None
    # BRAIN=heuristic (default, local rules, no network) | BRAIN=api (Claude, needs key, daily-capped).
    # The production system has a third mode - a live Claude Code session - that makes no sense on a public host.
    if os.environ.get("BRAIN", "heuristic").lower() == "api" and os.environ.get("ANTHROPIC_API_KEY") and _api_budget_ok():
        try:
            decision = api_brain(words)
        except Exception as e:  # fall back, never fail the job on the model
            decision = None
            (job_dir / "brain_error.txt").write_text(str(e)[:300])
    if not decision:
        decision = heuristic_brain(words)
    if not decision["ranges"]:
        raise RuntimeError("No usable speech spans found.")

    set_status("rendering")
    render(norm, decision, words, out, job_dir)
    norm.unlink(missing_ok=True)

    set_status("verifying")
    q = qa(out, job_dir)
    out_dur = probe(out)["duration"]
    trace = {
        "title": "Your clip", "variant": decision["brain"], "theme": decision["theme"],
        "brain_reason": decision["reason"], "edit_notes": None, "grade": "subtle",
        "compliance_dropped": [], "other_variants": [],
        "stats": {"raw_duration_s": round(raw_dur, 2), "output_duration_s": round(out_dur, 2),
                  "kept_ratio": round(out_dur / max(raw_dur, 0.1), 3), "segments": len(decision["ranges"]),
                  "kept_span_s": round(sum(r["end"] - r["start"] for r in decision["ranges"]), 2),
                  "transcribed_words": len(words), "overlays": len(decision["overlays"])},
        "qa": q, "qa_frames": [], "has_contact_sheet": (job_dir / "contact_sheet.jpg").exists(),
    }
    edl = {"title": "Your clip", "theme": decision["theme"], "notes": None, "grade": "subtle",
           "pop_style": "accent", "ranges": decision["ranges"], "overlays": decision["overlays"]}
    (job_dir / "decision.json").write_text(json.dumps(trace), encoding="utf-8")
    (job_dir / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
    return trace


_BUDGET = Path(os.environ.get("BUDGET_FILE", "/tmp/brain_budget.json"))


def _api_budget_ok() -> bool:
    cap = int(os.environ.get("DAILY_API_CAP", "30"))
    today = time.strftime("%Y-%m-%d")
    try:
        d = json.loads(_BUDGET.read_text())
    except Exception:
        d = {}
    n = d.get(today, 0)
    if n >= cap:
        return False
    _BUDGET.write_text(json.dumps({today: n + 1}))
    return True
