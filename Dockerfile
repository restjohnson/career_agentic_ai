# Stage 1 — build React frontend
FROM node:20-slim AS frontend
WORKDIR /app
COPY client/package.json client/package-lock.json ./
RUN npm ci
COPY client/ .
RUN npm run build

# Stage 2 — Python API server with bundled frontend
FROM python:3.10-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

COPY server/requirement.txt .
RUN pip install --no-cache-dir -r requirement.txt

COPY server/app/ ./app/
COPY --from=frontend /app/dist ./static

EXPOSE 8080
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
