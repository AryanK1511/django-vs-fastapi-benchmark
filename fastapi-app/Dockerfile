FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY eval/ eval/
COPY fastapi-app/ fastapi-app/

RUN uv sync --frozen --no-cache

WORKDIR /app/fastapi-app

EXPOSE 8001

CMD ["uv", "run", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8001"]
