# syntax=docker/dockerfile:1

# ── Build / dependency stage ──────────────────────────────────────────────────
FROM python:3.12-slim AS builder

WORKDIR /app

# Install dependencies into a separate prefix so we can copy them cleanly
COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ── Runtime stage ─────────────────────────────────────────────────────────────
FROM python:3.12-slim

LABEL org.opencontainers.image.title="lumens-exporter" \
      org.opencontainers.image.description="Prometheus exporter for Lumens VC-TR40/VC-TR40N PTZ auto-tracking cameras" \
      org.opencontainers.image.source="https://github.com/kristofkeppens/lumens-exporter"

WORKDIR /app

# Copy installed packages from the builder stage
COPY --from=builder /install /usr/local

# Copy the application source
COPY lumens_exporter/ ./lumens_exporter/

# Bundle the example config as the built-in default.
# A custom config can be injected at runtime by mounting a file over this path
# or by setting LUMENS_CONFIG to point elsewhere.
RUN mkdir -p /etc/lumens-exporter
COPY config.example.yaml /etc/lumens-exporter/config.yaml

ENV LUMENS_CONFIG=/etc/lumens-exporter/config.yaml

EXPOSE 9881

# Run as a non-root user for security
RUN useradd --no-create-home --shell /bin/false exporter
USER exporter

ENTRYPOINT ["python", "-m", "lumens_exporter"]
