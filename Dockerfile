# ---------- 前端构建 ----------
FROM node:20-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

# ---------- 后端运行 ----------
FROM python:3.11-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/backend \
    DATABASE_URL=sqlite:////app/data/whoop_analyst.db
COPY backend/pyproject.toml backend/pyproject.toml
COPY backend/app backend/app
RUN pip install --no-cache-dir "./backend[postgres]"
COPY --from=web /web/dist frontend/dist
RUN mkdir -p /app/data
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--app-dir", "backend", "--host", "0.0.0.0", "--port", "8000"]
