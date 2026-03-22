import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import typer

BENCHMARK_RESULTS_DIR = Path("benchmark-results")


def bytes_human(n: int) -> str:
    x = float(n)
    if x < 1024:
        return f"{int(x)} B"
    for suffix in ("KiB", "MiB", "GiB", "TiB"):
        x /= 1024.0
        if x < 1024 or suffix == "TiB":
            return f"{x:.2f} {suffix}"
    return f"{int(n)} B"


def percent_of_host(p: float) -> str:
    return f"{p:.1f}% of host RAM"


def host_memory_sentence(vm_total: int, vm_avail: int, vm_percent: float) -> str:
    return (
        f"Host memory: {vm_percent:.1f}% in use; "
        f"{bytes_human(vm_avail)} free of {bytes_human(vm_total)} total"
    )


def host_cpu_sentence(cpu_pct: float) -> str:
    return f"Host CPU (all cores, snapshot): {cpu_pct:.1f}% busy"


def _infer_stack_from_target(target: str) -> str:
    u = urlparse(target)
    if u.port == 8000:
        return "django"
    if u.port == 8001:
        return "fastapi"
    raise typer.BadParameter(
        "Could not infer django vs fastapi from --target "
        "(use :8000 or :8001 or pass --stack django or fastapi)."
    )


def _resolve_stack(target: str, stack: str | None) -> str:
    if stack is not None:
        s = stack.strip().lower()
        if s not in ("django", "fastapi"):
            raise typer.BadParameter("--stack must be django or fastapi")
        return s
    return _infer_stack_from_target(target)


def _default_result_path(stack: str) -> Path:
    return BENCHMARK_RESULTS_DIR / f"{stack}-sweep-result.json"


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _percentile(sorted_vals: list[float], p: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * p / 100.0
    f = int(k)
    c = min(f + 1, len(sorted_vals) - 1)
    if f == c:
        return sorted_vals[f]
    return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)


def _latency_stats(latencies_ok: list[float]) -> dict[str, float]:
    if not latencies_ok:
        return {"min": 0.0, "p50": 0.0, "p95": 0.0, "max": 0.0}
    s = sorted(latencies_ok)
    return {
        "min": round(s[0], 6),
        "p50": round(_percentile(s, 50), 6),
        "p95": round(_percentile(s, 95), 6),
        "max": round(s[-1], 6),
    }


def _thread_stats(threads_samples: list[int]) -> dict[str, Any]:
    if not threads_samples:
        return {"min": None, "max": None, "mean": None}
    return {
        "min": min(threads_samples),
        "max": max(threads_samples),
        "mean": round(statistics.mean(threads_samples), 4),
    }


def _num_stats(vals: list[float]) -> dict[str, float]:
    if not vals:
        return {}
    s = sorted(vals)
    return {
        "min": round(s[0], 4),
        "max": round(s[-1], 4),
        "mean": round(statistics.mean(vals), 4),
    }


def _aggregate_server_from_responses(
    rows: list[dict[str, Any]],
) -> dict[str, Any] | None:
    if not rows:
        return None
    rss = [int(r["rss"]) for r in rows]
    mem = [float(r["mem_pct"]) for r in rows]
    cpu = [float(r["cpu_total"]) for r in rows]
    pids = {int(r["pid"]) for r in rows}
    peak_rss = max(rss)
    cpu_delta = None
    if len(pids) == 1 and len(cpu) >= 2:
        cpu_delta = max(cpu) - min(cpu)
    rss_stats = _num_stats([float(x) for x in rss])
    mem_stats = _num_stats(mem)
    out: dict[str, Any] = {
        "sample_count": len(rows),
        "distinct_server_pids_in_samples": len(pids),
        "rss_bytes": rss_stats,
        "rss_human": {
            "min": bytes_human(min(rss)),
            "max": bytes_human(max(rss)),
            "mean": bytes_human(int(statistics.mean(rss))),
            "peak_seen": bytes_human(peak_rss),
        },
        "mem_percent_of_host": mem_stats,
        "mem_percent_display_at_peak_rss": percent_of_host(
            float(mem[rss.index(peak_rss)])
        ),
        "cpu_times_total_s_observed": {
            "min": round(min(cpu), 4),
            "max": round(max(cpu), 4),
        },
        "cpu_time_delta_s_approx": round(cpu_delta, 4)
        if cpu_delta is not None
        else None,
    }
    return out


async def _run_load(
    target: str,
    concurrency: int,
    total_requests: int,
    sleep_ms: int,
    timeout: float,
) -> tuple[
    float,
    list[float],
    list[str],
    list[int],
    list[int],
    list[dict[str, Any]],
]:
    latencies_ok: list[float] = []
    errors: list[str] = []
    threads_samples: list[int] = []
    pids: list[int] = []
    server_rows: list[dict[str, Any]] = []
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(
        timeout=timeout,
        limits=httpx.Limits(
            max_connections=concurrency, max_keepalive_connections=concurrency
        ),
    ) as client:

        async def one(i: int) -> None:
            async with sem:
                t0 = time.perf_counter()
                try:
                    r = await client.post(target, json={"sleep_ms": sleep_ms})
                    dt = time.perf_counter() - t0
                    if r.status_code >= 400:
                        errors.append(f"HTTP {r.status_code} {r.text[:200]}")
                        return
                    data = r.json()
                    latencies_ok.append(dt)
                    tc = data.get("thread_count", data.get("active_threads"))
                    if isinstance(tc, int):
                        threads_samples.append(tc)
                    if "pid" in data and isinstance(data["pid"], int):
                        pids.append(data["pid"])
                    srv = data.get("server")
                    if isinstance(srv, dict):
                        rb = srv.get("rss_bytes")
                        mp = srv.get("mem_percent_of_host")
                        cts = srv.get("cpu_times_s")
                        pid = data.get("pid")
                        ct_total = cts.get("total") if isinstance(cts, dict) else None
                        if (
                            isinstance(rb, int)
                            and isinstance(mp, (int, float))
                            and isinstance(ct_total, (int, float))
                            and isinstance(pid, int)
                        ):
                            server_rows.append(
                                {
                                    "rss": rb,
                                    "mem_pct": float(mp),
                                    "cpu_total": float(ct_total),
                                    "pid": pid,
                                }
                            )
                except Exception as exc:
                    errors.append(str(exc))

        wall0 = time.perf_counter()
        await asyncio.gather(*[one(i) for i in range(total_requests)])
        wall_s = time.perf_counter() - wall0
    return wall_s, latencies_ok, errors, threads_samples, pids, server_rows


def _build_sweep_step_report(
    target: str,
    concurrency: int,
    total_requests: int,
    sleep_ms: int,
    wall_s: float,
    latencies_ok: list[float],
    errors: list[str],
    threads_samples: list[int],
    pids: list[int],
    server_rows: list[dict[str, Any]],
    error_limit: int = 25,
) -> dict[str, Any]:
    ok = len(latencies_ok)
    fail = len(errors)
    rps = total_requests / wall_s if wall_s > 0 else 0.0
    err_out = errors[:error_limit]
    if len(errors) > error_limit:
        err_out = err_out + [f"... and {len(errors) - error_limit} more"]
    th_stats = _thread_stats(threads_samples)
    server_agg = _aggregate_server_from_responses(server_rows)
    return {
        "target": target,
        "load": {
            "concurrency": concurrency,
            "requests": total_requests,
            "sleep_ms": sleep_ms,
        },
        "results": {
            "wall_s": round(wall_s, 6),
            "total_requests": total_requests,
            "ok": ok,
            "fail": fail,
            "requests_per_second": round(rps, 4),
            "latency_s": _latency_stats(latencies_ok),
            "server_thread_count": th_stats,
            "distinct_server_pids": len(set(pids)) if pids else 0,
            "server_observed": server_agg,
        },
        "errors": err_out,
    }
