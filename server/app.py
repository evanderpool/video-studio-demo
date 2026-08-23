"""
Video Studio public demo service.

Threat model: anonymous internet users. Hence:
  - extension whitelist, hard byte cap streamed to disk, ffprobe duration/stream checks BEFORE any work
  - one worker thread, bounded queue, per-IP + global rate limits
  - job ids are 96-bit random; every job path is server-built; no shell anywhere
  - every job dir is deleted RETENTION_MIN minutes after it finishes (or on any failure)
  - nothing about uploads is logged; no analytics; no accounts
  - the model call (if any) is capped per day and falls back to the offline heuristic
"""
from __future__ import annotations

import json
import os
import secrets
import shutil
import threading
import time
from collections import defaultdict, deque
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import pipeline

ROOT = Path(__file__).resolve().parent.parent
SITE = ROOT / "site"
JOBS = Path(os.environ.get("JOBS_DIR", "/tmp/vs_jobs"))
JOBS.mkdir(parents=True, exist_ok=True)

MAX_BYTES = int(os.environ.get("MAX_UPLOAD_MB", "80")) * 1024 * 1024
MIN_SECONDS = float(os.environ.get("MIN_SECONDS", "5"))
MAX_SECONDS = float(os.environ.get("MAX_SECONDS", "60"))
ALLOWED = {".mp4", ".mov", ".webm", ".m4v"}
PER_IP_PER_HOUR = int(os.environ.get("PER_IP_PER_HOUR", "3"))
GLOBAL_PER_DAY = int(os.environ.get("GLOBAL_PER_DAY", "60"))
QUEUE_MAX = int(os.environ.get("QUEUE_MAX", "4"))
RETENTION_MIN = float(os.environ.get("RETENTION_MIN", "30"))
TRUST_PROXY = os.environ.get("TRUST_PROXY", "1") == "1"

app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

_jobs: dict[str, dict] = {}
_queue: deque[str] = deque()
_lock = threading.Lock()
_ip_hits: dict[str, deque] = defaultdict(deque)
_global_hits: deque = deque()


def client_ip(req: Request) -> str:
    if TRUST_PROXY:
        xff = req.headers.get("x-forwarded-for")
        if xff:
            return xff.split(",")[-1].strip()  # last hop = the trusted proxy's view of the client
    return req.client.host if req.client else "?"


def _rate_ok(ip: str) -> tuple[bool, str]:
    now = time.time()
    with _lock:
        q = _ip_hits[ip]
        while q and now - q[0] > 3600:
            q.popleft()
        while _global_hits and now - _global_hits[0] > 86400:
            _global_hits.popleft()
        if len(q) >= PER_IP_PER_HOUR:
            return False, f"limit: {PER_IP_PER_HOUR} clips per hour per address"
        if len(_global_hits) >= GLOBAL_PER_DAY:
            return False, "the demo has hit its daily cap — try again tomorrow"
        if len(_queue) >= QUEUE_MAX:
            return False, "queue is full right now — try again in a few minutes"
    return True, ""


def _rate_record(ip: str) -> None:
    """Only ACCEPTED clips count against the quotas - a rejected upload is free to retry."""
    now = time.time()
    with _lock:
        _ip_hits[ip].append(now)
        _global_hits.append(now)


def _set(job_id: str, **k):
    with _lock:
        _jobs[job_id].update(k)


def _worker():
    while True:
        job_id = None
        with _lock:
            if _queue:
                job_id = _queue.popleft()
        if not job_id:
            time.sleep(0.5)
            continue
        d = JOBS / job_id
        try:
            _set(job_id, state="running", stage="starting", started=time.time())
            trace = pipeline.process(d, lambda s: _set(job_id, stage=s))
            _set(job_id, state="done", stage="done", finished=time.time(), trace=trace)
        except Exception as e:
            _set(job_id, state="error", stage="error", finished=time.time(), error=str(e)[:300])
            shutil.rmtree(d, ignore_errors=True)


def _reaper():
    while True:
        time.sleep(60)
        now = time.time()
        with _lock:
            dead = [j for j, v in _jobs.items()
                    if v.get("finished") and now - v["finished"] > RETENTION_MIN * 60
                    or (not v.get("finished") and now - v["created"] > 3 * 3600)]
        for j in dead:
            shutil.rmtree(JOBS / j, ignore_errors=True)
            with _lock:
                _jobs.pop(j, None)
        # orphans from a previous process
        for p in JOBS.iterdir():
            if p.is_dir() and p.name not in _jobs and now - p.stat().st_mtime > RETENTION_MIN * 60:
                shutil.rmtree(p, ignore_errors=True)


threading.Thread(target=_worker, daemon=True).start()
threading.Thread(target=_reaper, daemon=True).start()


def _job_or_404(job_id: str) -> dict:
    if not (len(job_id) == 24 and all(c in "0123456789abcdef" for c in job_id)):
        raise HTTPException(404)
    j = _jobs.get(job_id)
    if not j:
        raise HTTPException(404)
    return j


@app.get("/api/health")
def health():
    return {"ok": True, "max_seconds": MAX_SECONDS, "min_seconds": MIN_SECONDS, "max_mb": MAX_BYTES // (1024 * 1024),
            "brain": "api" if (os.environ.get("BRAIN", "heuristic").lower() == "api" and os.environ.get("ANTHROPIC_API_KEY")) else "heuristic",
            "retention_min": RETENTION_MIN}


@app.post("/api/try")
async def try_it(req: Request, file: UploadFile):
    ip = client_ip(req)
    ok, why = _rate_ok(ip)
    if not ok:
        raise HTTPException(429, why)
    ext = Path(file.filename or "").suffix.lower()
    if ext not in ALLOWED:
        raise HTTPException(400, f"Allowed: {', '.join(sorted(ALLOWED))}")
    job_id = secrets.token_hex(12)
    d = JOBS / job_id
    d.mkdir()
    dst = d / f"upload{ext}"
    size = 0
    try:
        with dst.open("wb") as f:
            while chunk := await file.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_BYTES:
                    raise HTTPException(413, f"Max {MAX_BYTES // (1024*1024)} MB")
                f.write(chunk)
        info = pipeline.probe(dst)
        if not info["has_video"] or not info["has_audio"]:
            raise HTTPException(400, "Clip needs both video and audio (a talking take).")
        if not (MIN_SECONDS <= info["duration"] <= MAX_SECONDS):
            raise HTTPException(400, f"Clip must be {int(MIN_SECONDS)}–{int(MAX_SECONDS)} seconds (yours: {info['duration']:.0f}s).")
    except HTTPException:
        shutil.rmtree(d, ignore_errors=True)
        raise
    except Exception:
        shutil.rmtree(d, ignore_errors=True)
        raise HTTPException(400, "Could not read that file as a video.")
    _rate_record(ip)
    with _lock:
        _jobs[job_id] = {"state": "queued", "stage": "queued", "created": time.time(), "position": len(_queue) + 1}
        _queue.append(job_id)
    return {"id": job_id, "raw_duration_s": round(info["duration"], 1)}


@app.get("/api/jobs/{job_id}")
def job_status(job_id: str):
    j = _job_or_404(job_id)
    out = {k: j.get(k) for k in ("state", "stage", "error")}
    if j["state"] == "queued":
        with _lock:
            out["position"] = (_queue.index(job_id) + 1) if job_id in _queue else 0
    if j["state"] == "done":
        out["expires_in_s"] = int(RETENTION_MIN * 60 - (time.time() - j["finished"]))
    return out


@app.get("/api/jobs/{job_id}/{name}")
def job_file(job_id: str, name: str):
    j = _job_or_404(job_id)
    if j["state"] != "done":
        raise HTTPException(409, "not ready")
    allowed = {"output.mp4": "video/mp4", "decision.json": "application/json",
               "edl.json": "application/json", "contact_sheet.jpg": "image/jpeg"}
    if name not in allowed:
        raise HTTPException(404)
    p = JOBS / job_id / name
    if not p.exists():
        raise HTTPException(404)
    return FileResponse(p, media_type=allowed[name], headers={"Cache-Control": "private, no-store"})


@app.exception_handler(HTTPException)
async def _http_err(_req, exc: HTTPException):
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


app.mount("/", StaticFiles(directory=str(SITE), html=True), name="site")
