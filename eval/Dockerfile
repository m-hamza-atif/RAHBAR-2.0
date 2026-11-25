FROM python:3.12.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 HOME=/tmp
WORKDIR /app
RUN pip install --no-cache-dir httpx==0.28.1 pyyaml==6.0.2
COPY eval/ ./eval/
COPY scripts/inspect_trace.py scripts/summarize_traces.py scripts/trace_records.py ./scripts/
USER 10001:10001
CMD ["python", "eval/cluster_job.py"]
