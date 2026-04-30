# vlabor_agent — chat_backend container.
#
# ROS2 / CUDA に依存しない軽量 image (Phase 0)。
# bt_runtime / web_ui は別 service として後で足す前提。
#
# Build context: vlabor_agent repo root (so chat_backend/ が見える).
#   docker build -f docker/Dockerfile -t vlabor-agent:local .
#
# Runtime: chat_backend を /app/chat_backend に bind-mount する想定。
# editable install でソース編集が即反映される (vlabor_dashboard と同パターン)。

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    VLABOR_AGENT_PORT=8887 \
    VLABOR_AGENT_HOST=0.0.0.0

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Pre-bake runtime deps so first start is fast even on a cold mount.
# Versions kept loose to match chat_backend/pyproject.toml. The
# editable install at runtime re-resolves with the repo's pinned
# versions if they differ.
RUN pip install \
      "anthropic>=0.40.0" \
      "openai>=1.40.0" \
      "aiohttp>=3.10.0" \
      "mcp>=1.0.0" \
      "pydantic>=2.5.0"

WORKDIR /app/chat_backend

# Editable install at startup so the bind-mounted source registers as
# the chat_backend package without re-downloading deps. exec ensures
# Python becomes PID 1 for clean signal handling.
CMD ["sh", "-c", "pip install --no-deps -e . && exec python -m chat_backend.server"]
