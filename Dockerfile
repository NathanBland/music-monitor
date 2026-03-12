FROM python:3.13-slim

LABEL org.opencontainers.image.source="https://github.com/NathanBland/music-monitor"
LABEL org.opencontainers.image.description="Folder watcher that tags audio with beets and organizes output"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates procps \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --no-cache-dir .

COPY config.toml.example ./config.toml.example

RUN useradd --create-home --shell /usr/sbin/nologin appuser \
    && chown -R appuser:appuser /app

USER appuser

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD pgrep -f music-monitor >/dev/null || exit 1

CMD ["music-monitor"]
