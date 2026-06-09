# SiftPDF — two-stage build, mirrors compile-pdf's Dockerfile pattern.
# SIFT_TIERS build arg controls which optional solver deps are installed.
#
# Build variants:
#   docker build .                                   # grid only
#   docker build --build-arg SIFT_EXTRAS="gang" .   # grid + gang (OR-Tools)
#   docker build --build-arg SIFT_EXTRAS="gang,nest" .  # all tiers

FROM python:3.12-slim AS builder

ARG SIFT_EXTRAS=""
ENV UV_NO_CACHE=1

WORKDIR /build
RUN pip install --no-cache-dir uv

# README.md is referenced by pyproject (`readme = "README.md"`); hatchling needs it
# present to build the project wheel, so copy it alongside the manifest.
COPY pyproject.toml uv.lock* README.md ./
COPY src/ ./src/
# pyproject force-includes schemas/ into the wheel, so it must be present at build time.
COPY schemas/ ./schemas/

RUN if [ -n "$SIFT_EXTRAS" ]; then \
      uv sync --no-dev --extra "$SIFT_EXTRAS"; \
    else \
      uv sync --no-dev; \
    fi


FROM python:3.12-slim AS runtime

ARG SIFT_EXTRAS=""
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    SIFT_TIERS="grid,gang,nest"

# tini for PID-1 signal handling
RUN apt-get update && apt-get install -y --no-install-recommends tini && \
    rm -rf /var/lib/apt/lists/*

# Non-root user
RUN useradd --uid 10001 --no-create-home --shell /sbin/nologin sift

WORKDIR /app
COPY --from=builder /build/.venv /app/.venv
COPY src/ ./src/
COPY schemas/ ./schemas/

ENV PATH="/app/.venv/bin:$PATH"

USER sift

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8100/healthz')"

EXPOSE 8100

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["uvicorn", "sift_pdf.api.main:app", "--host", "0.0.0.0", "--port", "8100"]
