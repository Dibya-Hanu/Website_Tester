# Chromium and all tools are local; no paid or proprietary runtime services.
FROM node:22-bookworm-slim AS frontend
WORKDIR /web
COPY frontend/package*.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM node:22-bookworm-slim AS node-tools
ENV PUPPETEER_SKIP_DOWNLOAD=true
WORKDIR /tools
COPY tools/package*.json ./
RUN npm ci --omit=dev --no-audit --no-fund

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_BROWSERS_PATH=/opt/browsers PYTHONPATH=/app/backend \
    UWT_DATA_DIR=/app/data UWT_TOOLS_DIR=/app/tools UWT_FRONTEND_DIR=/app/frontend/dist
WORKDIR /app
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates tini fonts-dejavu-core libstdc++6 libgomp1 && rm -rf /var/lib/apt/lists/*
COPY backend/requirements.txt /app/backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt && \
    playwright install --with-deps chromium && \
    chmod -R a+rX /opt/browsers
COPY --from=node-tools /usr/local/bin/node /usr/local/bin/node
COPY --from=node-tools /tools/node_modules /app/tools/node_modules
COPY --from=frontend /web/dist /app/frontend/dist
COPY backend/ /app/backend/
COPY tools/ /app/tools/
COPY scripts/ /app/scripts/
COPY samples/ /app/samples/
COPY LICENSE README.md ARCHITECTURE.md THIRD_PARTY_NOTICES.md SECURITY.md TESTING.md /app/
COPY third_party/licenses/ /app/third_party/licenses/
RUN python scripts/install_nuclei.py /usr/local/bin/nuclei && \
    useradd --create-home --uid 10001 tester && mkdir -p /app/data && chown -R tester:tester /app/data
USER tester
EXPOSE 8080
ENTRYPOINT ["tini", "--"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080", "--workers", "1"]
