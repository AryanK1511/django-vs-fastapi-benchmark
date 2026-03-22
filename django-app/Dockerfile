FROM python:3.12-slim

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/

WORKDIR /app

COPY pyproject.toml uv.lock .python-version ./
COPY eval/ eval/
COPY django-app/ django-app/

RUN uv sync --frozen --no-cache

WORKDIR /app/django-app

EXPOSE 8000

CMD ["sh", "-c", "uv run python manage.py migrate --noinput && uv run daphne -b 0.0.0.0 -p 8000 config.asgi:application"]
