FROM python:3.12-slim

# Font DejaVu de PDF don hang hien thi dung dau tieng Viet
RUN apt-get update && apt-get install -y --no-install-recommends fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/*
COPY --from=ghcr.io/astral-sh/uv:0.13.1 /uv /bin/uv

WORKDIR /app
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PROJECT_ENVIRONMENT=/opt/venv PATH="/opt/venv/bin:$PATH"
COPY pyproject.toml uv.lock* ./
RUN uv sync --no-dev --no-install-project
COPY . .

EXPOSE 8000
CMD ["sh", "-c", "python -m app.db_init && uvicorn app.api.main:app --host 0.0.0.0 --port 8000"]
