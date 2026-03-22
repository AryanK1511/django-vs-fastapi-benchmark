# Django vs FastAPI Experiments

I built this to compare Django and FastAPI under the same I/O-heavy `/chat` workload, with matching Docker CPU and memory caps and rising client concurrency, using RSS, CPU time, and thread behavior alongside throughput instead of treating raw RPS as the whole story.

## Setup

From the repo root:

```bash
uv sync
cd django-app && uv run python manage.py migrate
```

## Run with Docker

From the repo root, build and start both apps (Django on **8000**, FastAPI on **8001**):

```bash
docker compose up --build
```

If you use the standalone Compose binary:

```bash
docker-compose up --build
```

- **Django** (Daphne + DRF): `POST http://127.0.0.1:8000/chat/` — same JSON body as below.
- **FastAPI** (Uvicorn): `POST http://127.0.0.1:8001/chat`

[`docker-compose.yml`](docker-compose.yml) caps each service at **0.5 CPU** and **512Mi** memory. Images build from [`django-app/Dockerfile`](django-app/Dockerfile) and [`fastapi-app/Dockerfile`](fastapi-app/Dockerfile) with the repo root as context (shared `pyproject.toml`, `uv.lock`, and `eval/`). The Django container runs `migrate` before Daphne starts.

Stop with Ctrl+C, then `docker compose down` (or `docker-compose down`) if you want containers removed.

To run **`bench`** against these URLs, use a local env (`uv sync` from the repo root). Result JSON is still written under **`benchmark-results/`** on your host (see below).

## Run Django (Daphne + DRF)

```bash
cd django-app
uv run daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

POST endpoint: `http://127.0.0.1:8000/chat/` (JSON body: `{"sleep_ms": 200}`).

## Run FastAPI (Uvicorn)

From the repo root:

```bash
cd fastapi-app
uv run uvicorn server:app --host 127.0.0.1 --port 8001
```

POST endpoint: `http://127.0.0.1:8001/chat` (same JSON body).

## Load eval (Typer + httpx)

From the repo root, `bench` writes **JSON** under **`benchmark-results/`** (directory is created if needed):

| Stack   | Default output file                           |
| ------- | --------------------------------------------- |
| Django  | `benchmark-results/django-sweep-result.json`  |
| FastAPI | `benchmark-results/fastapi-sweep-result.json` |

Stack is inferred from `--target`: port **8000** → Django, **8001** → FastAPI. Override with **`--stack django`** or **`--stack fastapi`** if you use other ports. **`--output` / `-o`** sets a custom file path instead.

After a sweep, the absolute path of the written file is printed on one line.

`results.server_observed` in each run aggregates the **`server` object from each API response** (RSS, host RAM %, CPU time delta when all samples share one PID).

Each `/chat` JSON includes **`server`**: `rss_bytes` / `rss_human`, `mem_percent_of_host` / `mem_percent_display`, and **`cpu_times_s`** (cumulative user+system seconds since that process started — use max−min across responses during a benchmark as a rough “CPU used during the test”).

### Watch the server process externally (optional)

While `bench` runs, in another terminal (replace `<pid>` with the Daphne or Uvicorn PID):

```bash
ps -o pid,rss,vsz,%mem,%cpu -p <pid>
```

`rss` is in kilobytes on macOS `ps`. Compare Django vs FastAPI under the same workload for the “many threads vs one thread” story.

Sweep concurrency levels:

```bash
uv run bench --target http://127.0.0.1:8000/chat/ --levels 500,1000 --requests 1000 --sleep-ms 4000
uv run bench --target http://127.0.0.1:8001/chat --levels 500,1000 --requests 1000 --sleep-ms 4000
```

Each API response also includes `thread_count`, `thread_names`, `thread_name`, and `pid`.

## Results dashboard

After you have sweep JSON for both stacks (same default paths as in the table above), open the dashboard in [`results-dashboard/`](results-dashboard/). It loads `benchmark-results/django-sweep-result.json` and `benchmark-results/fastapi-sweep-result.json` from the repo root and charts overlapping concurrency levels only.

From the repo root, install the optional **dashboard** dependency group and run:

```bash
uv sync --group dashboard
uv run --group dashboard streamlit run results-dashboard/app.py
```

The process prints a local URL in the terminal (often `http://127.0.0.1:8501`). Stop it with Ctrl+C.

## Author

[Aryan Khurana](https://github.com/AryanK1511)
