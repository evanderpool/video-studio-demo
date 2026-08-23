FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# all writable state lives under /tmp or /app/hf; HF Spaces runs the container as uid 1000
ENV BRAIN=heuristic HF_HOME=/app/hf JOBS_DIR=/tmp/vs_jobs BUDGET_FILE=/tmp/brain_budget.json \
    MAX_SECONDS=60 MIN_SECONDS=5 MAX_UPLOAD_MB=80 PER_IP_PER_HOUR=3 GLOBAL_PER_DAY=60 RETENTION_MIN=30

# bake the ASR model into the image so the first request isn't a cold download
RUN python -c "from faster_whisper import WhisperModel; WhisperModel('small.en', device='cpu', compute_type='int8')"

COPY server ./server
COPY site ./site

RUN useradd -m -u 1000 user && chown -R user /app
USER user

EXPOSE 7860
CMD ["uvicorn", "server.app:app", "--host", "0.0.0.0", "--port", "7860", "--proxy-headers", "--forwarded-allow-ips", "*"]
