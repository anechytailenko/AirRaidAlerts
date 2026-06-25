# Narrative Analyst Agent — isolated container (plans/07 §4).
# The dynamic code synthesizer runs LLM-written Python; this image is the outer containment ring:
# non-root user, no baked-in data, and (via docker-compose) a read-only rootfs + read-only data
# mounts so generated code can NEVER delete or corrupt the real export or model weights.
FROM python:3.11-slim

# system libs matplotlib/statsmodels need at runtime
RUN apt-get update && apt-get install -y --no-install-recommends \
        libgomp1 fonts-dejavu-core && rm -rf /var/lib/apt/lists/*

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/app/src \
    MPLBACKEND=Agg \
    AIRRAID_EXPORTS_DIR=/data/exports \
    OLLAMA_BASE_URL=http://host.docker.internal:11434

WORKDIR /app

# deps only (no data) — kept minimal & pinned-by-range; the read-only data arrives via a mount
RUN pip install --no-cache-dir \
        "mcp>=1.2" "langgraph>=0.2" "pydantic>=2" "pydantic-settings>=2" \
        "pandas>=2" "numpy>=1.26" "pyarrow>=14" "matplotlib>=3.8" "seaborn>=0.13" \
        "statsmodels>=0.14" "requests>=2.31"

# code only — src/ (the airraid package) + the MCP server
COPY src/ /app/src/
COPY MCP/Narrative_Analyst/ /app/MCP/Narrative_Analyst/

# non-root: generated code runs as an unprivileged user
RUN useradd --create-home --uid 10001 analyst
USER analyst

# stdio MCP server (compose adds the read-only mounts, tmpfs scratch, and resource limits)
CMD ["python", "/app/MCP/Narrative_Analyst/server.py"]
