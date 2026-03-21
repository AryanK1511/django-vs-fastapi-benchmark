# Django vs FastAPI Experiments

## Setup

From the repo root:

```bash
uv sync
cd django-app && uv run python manage.py migrate
```

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

From the repo root, `bench run` and `bench sweep` write **JSON** under **`benchmark-results/`** (directory is created if needed). Filenames:

| Command | Django target                                | FastAPI target                                |
| ------- | -------------------------------------------- | --------------------------------------------- |
| `run`   | `benchmark-results/django-run-result.json`   | `benchmark-results/fastapi-run-result.json`   |
| `sweep` | `benchmark-results/django-sweep-result.json` | `benchmark-results/fastapi-sweep-result.json` |

Stack is inferred from `--target`: port **8000** → Django, **8001** → FastAPI; otherwise path ending in **`/chat/`** → Django, **`/chat`** (no trailing slash) → FastAPI. Override with **`--stack django`** or **`--stack fastapi`** if you use other ports. **`--output` / `-o`** sets a custom file path instead.

After a run, the absolute path of the written file is printed on one line.

`system` is a **machine-wide** snapshot after the run (with `*_human` fields and `summary_host_memory` / `summary_host_cpu`). `results.server_observed` aggregates the **`server` object from each API response** (RSS, host RAM %, CPU time delta when all samples share one PID). **`human_summary`** is a short list of deck-ready sentences.

Each `/chat` JSON includes **`server`**: `rss_bytes` / `rss_human`, `mem_percent_of_host` / `mem_percent_display`, and **`cpu_times_s`** (cumulative user+system seconds since that process started — use max−min across responses during a benchmark as a rough “CPU used during the test”).

### Watch the server process externally (optional)

While `bench` runs, in another terminal (replace `<pid>` with the Daphne or Uvicorn PID):

```bash
ps -o pid,rss,vsz,%mem,%cpu -p <pid>
```

`rss` is in kilobytes on macOS `ps`. Compare Django vs FastAPI under the same workload for the “many threads vs one thread” story.

With one server running:

```bash
uv run bench run --target http://127.0.0.1:8000/chat/ --concurrency 20 --requests 100 --sleep-ms 200
uv run bench run --target http://127.0.0.1:8001/chat --concurrency 20 --requests 100 --sleep-ms 200
```

Sweep concurrency levels:

```bash
uv run bench sweep --target http://127.0.0.1:8000/chat/ --levels 1,10,50 --requests 150 --sleep-ms 200
uv run bench sweep --target http://127.0.0.1:8001/chat --levels 1,10,50 --requests 150 --sleep-ms 200
```

Each API response also includes `thread_count`, `thread_names`, `thread_name`, and `pid`.
