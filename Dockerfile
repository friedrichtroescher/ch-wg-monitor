# ch-wg-monitor — built for linux/arm64 (Hetzner k3s) and pushed to
# ghcr.io/<owner>/ch-wg-monitor:latest by .github/workflows/build.yaml on push to main.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim
WORKDIR /app
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-editable
COPY src/ src/
COPY main.py .
CMD ["uv", "run", "main.py", "run"]
