# Django vs FastAPI Experiments

I built this to compare Django and FastAPI under the same I/O-heavy `/chat` workload, with matching Docker CPU and memory caps and rising client concurrency, using RSS, CPU time, and thread behavior alongside throughput instead of treating raw RPS as the whole story.

## Running the servers

Before running the benchmark, you need to run the Django and FastAPI servers. There are two ways to do this:

1. Run using docker compose
2. Run using uv

The good thing about running using docker compose is that it assigns a fixed amount of CPU and memory to each app, so the results are more consistent since each computer has a different amount of CPU and memory.

### Running using docker compose

From the repo root, build and start both apps (Django on **8000**, FastAPI on **8001**):

```bash
docker compose up --build
```

If you use the standalone Compose binary:

```bash
docker-compose up --build
```

Stopping the containers is done with:

```bash
docker compose down
```

If you use the standalone Compose binary:

```bash
docker-compose down
```

### Running using uv

#### Django (Daphne + DRF)

From the repo root:

```bash
uv sync
cd django-app && uv run python manage.py migrate
uv run daphne -b 127.0.0.1 -p 8000 config.asgi:application
```

#### FastAPI (Uvicorn)

From the repo root:

```bash
cd fastapi-app
uv run uvicorn server:app --host 127.0.0.1 --port 8001
```

## Endpoints

- **Django** (Daphne + DRF): `POST http://127.0.0.1:8000/chat`
- **FastAPI** (Uvicorn): `POST http://127.0.0.1:8001/chat`

JSON body: `{"sleep_ms": 200}`.

## Running the benchmark

**Local flow:** Start the stack you want to measure (Docker Compose or `uv`, as in [Running the servers](#running-the-servers)) and leave it running. In a **separate** terminal, from the **repository root** (after `uv sync` so the `bench` script and dependencies are available), run `bench` against the matching URL.

`bench` writes **JSON** under **`benchmark-results/`** (the directory is created if needed):

| Stack   | Default output file                           |
| ------- | --------------------------------------------- |
| Django  | `benchmark-results/django-sweep-result.json`  |
| FastAPI | `benchmark-results/fastapi-sweep-result.json` |

Stack is inferred from `--target`: port **8000** → Django, **8001** → FastAPI. Override with **`--stack django`** or **`--stack fastapi`** if you use other ports. **`--output` / `-o`** sets a custom file path instead.

After a sweep, the absolute path of the written file is printed on one line.

Examples when Django is on **8000** and FastAPI on **8001** (same ports as in the sections above):

```bash
uv run bench --target http://127.0.0.1:8000/chat/ --levels 500,1000 --requests 1000 --sleep-ms 4000
uv run bench --target http://127.0.0.1:8001/chat --levels 500,1000 --requests 1000 --sleep-ms 4000
```

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
