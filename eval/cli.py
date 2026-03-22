import asyncio
import json
import statistics
import time
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx
import psutil
import typer

from eval.human_format import (
    bytes_human,
    host_cpu_sentence,
    host_memory_sentence,
    percent_of_host,
)

cli = typer.Typer()

BENCHMARK_RESULTS_DIR = Path("benchmark-results")


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


def _default_result_path(stack: str, sweep: bool) -> Path:
    kind = "sweep" if sweep else "run"
    return BENCHMARK_RESULTS_DIR / f"{stack}-{kind}-result.json"


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
    thread_max: int | None,
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
        "cpu_time_delta_human": (
            f"Server process consumed about {cpu_delta:.2f} s of CPU (user+system) "
            f"between the lowest and highest cumulative samples in this benchmark "
            f"(same PID only)."
            if cpu_delta is not None
            else (
                "CPU delta needs at least two successful responses from the same server PID."
            )
        ),
        "deck_line_rss_threads": (
            f"Under this load, server RSS peaked around {bytes_human(peak_rss)}"
            + (
                f" with up to {thread_max} Python threads alive (from responses)."
                if thread_max is not None
                else "."
            )
        ),
    }
    return out


def _system_snapshot() -> dict[str, Any]:
    vm = psutil.virtual_memory()
    cpu_pct = psutil.cpu_percent(interval=0.1)
    return {
        "memory_total_bytes": vm.total,
        "memory_available_bytes": vm.available,
        "memory_used_percent": vm.percent,
        "cpu_percent": cpu_pct,
        "memory_total_human": bytes_human(int(vm.total)),
        "memory_available_human": bytes_human(int(vm.available)),
        "memory_used_percent_display": f"{vm.percent:.1f}% of host RAM in use (all processes)",
        "summary_host_memory": host_memory_sentence(
            int(vm.total), int(vm.available), float(vm.percent)
        ),
        "summary_host_cpu": host_cpu_sentence(float(cpu_pct)),
    }


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


def _human_summary_lines(
    thread_stats: dict[str, Any],
    server_agg: dict[str, Any] | None,
    system: dict[str, Any],
    ok: int,
    fail: int,
) -> list[str]:
    lines: list[str] = []
    lines.append(
        f"Requests: {ok} succeeded, {fail} failed. "
        f"Thread count in API responses (min / max / mean): "
        f"{thread_stats.get('min')} / {thread_stats.get('max')} / {thread_stats.get('mean')}."
    )
    lines.append(system.get("summary_host_memory", ""))
    lines.append(system.get("summary_host_cpu", ""))
    if server_agg:
        lines.append(server_agg.get("deck_line_rss_threads", ""))
        lines.append(server_agg.get("cpu_time_delta_human", ""))
    else:
        lines.append(
            "No per-response server metrics (upgrade API or fix errors). "
            "You can still watch the server with: "
            "ps -o pid,rss,vsz,%mem,%cpu -p <daphne_or_uvicorn_pid>"
        )
    lines.append(
        "Replace time.sleep with real LLM + streaming: thread counts stay comparable, "
        "but sockets and buffers weigh more; async tends to scale that part more cheaply."
    )
    return [ln for ln in lines if ln]


def _build_run_report(
    mode: str,
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
    system_after: dict[str, Any],
    error_limit: int = 25,
) -> dict[str, Any]:
    ok = len(latencies_ok)
    fail = len(errors)
    rps = total_requests / wall_s if wall_s > 0 else 0.0
    err_out = errors[:error_limit]
    if len(errors) > error_limit:
        err_out = err_out + [f"... and {len(errors) - error_limit} more"]
    th_stats = _thread_stats(threads_samples)
    th_max = th_stats.get("max")
    th_max_i = int(th_max) if isinstance(th_max, int) else None
    server_agg = _aggregate_server_from_responses(server_rows, th_max_i)
    return {
        "mode": mode,
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
        "system": system_after,
        "human_summary": _human_summary_lines(
            th_stats, server_agg, system_after, ok, fail
        ),
        "errors": err_out,
    }


@cli.command("run")
def cmd_run(
    target: str = typer.Option(
        ..., "--target", "-t", help="Full URL, e.g. http://127.0.0.1:8000/chat/"
    ),
    concurrency: int = typer.Option(10, "--concurrency", "-c"),
    requests: int = typer.Option(100, "--requests", "-n"),
    sleep_ms: int = typer.Option(200, "--sleep-ms", "-s"),
    timeout: float = typer.Option(120.0, "--timeout"),
    stack: str | None = typer.Option(
        None,
        "--stack",
        help="django or fastapi; default: infer from URL (ports 8000/8001 or /chat/ vs /chat).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Override output path (default: benchmark-results/<stack>-run-result.json).",
    ),
) -> None:
    psutil.cpu_percent(interval=0.1)
    wall_s, lat_ok, errs, threads_samples, pids, server_rows = asyncio.run(
        _run_load(target, concurrency, requests, sleep_ms, timeout)
    )
    system_after = _system_snapshot()
    report = _build_run_report(
        "run",
        target,
        concurrency,
        requests,
        sleep_ms,
        wall_s,
        lat_ok,
        errs,
        threads_samples,
        pids,
        server_rows,
        system_after,
    )
    resolved_stack = _resolve_stack(target, stack)
    out = (
        output
        if output is not None
        else _default_result_path(resolved_stack, sweep=False)
    )
    report["output_stack"] = resolved_stack
    _write_json(out, report)
    typer.echo(str(out.resolve()))


@cli.command("sweep")
def cmd_sweep(
    target: str = typer.Option(..., "--target", "-t"),
    levels: str = typer.Option(
        "1,5,10,25,50",
        "--levels",
        "-l",
        help="Comma-separated concurrency levels",
    ),
    requests: int = typer.Option(200, "--requests", "-n"),
    sleep_ms: int = typer.Option(200, "--sleep-ms", "-s"),
    timeout: float = typer.Option(300.0, "--timeout"),
    stack: str | None = typer.Option(
        None,
        "--stack",
        help="django or fastapi; default: infer from URL (ports 8000/8001 or /chat/ vs /chat).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Override output path (default: benchmark-results/<stack>-sweep-result.json).",
    ),
) -> None:
    conc_levels = [int(x.strip()) for x in levels.split(",") if x.strip()]
    psutil.cpu_percent(interval=0.1)
    runs: list[dict[str, Any]] = []
    for c in conc_levels:
        wall_s, lat_ok, errs, threads_samples, pids, server_rows = asyncio.run(
            _run_load(target, c, requests, sleep_ms, timeout)
        )
        system_after = _system_snapshot()
        runs.append(
            _build_run_report(
                "sweep",
                target,
                c,
                requests,
                sleep_ms,
                wall_s,
                lat_ok,
                errs,
                threads_samples,
                pids,
                server_rows,
                system_after,
            )
        )
    resolved_stack = _resolve_stack(target, stack)
    out = (
        output
        if output is not None
        else _default_result_path(resolved_stack, sweep=True)
    )
    payload = {
        "mode": "sweep",
        "output_stack": resolved_stack,
        "levels": conc_levels,
        "runs": runs,
        "human_summary": [
            f"Sweep across concurrency {conc_levels}; see each run.human_summary."
        ],
    }
    _write_json(out, payload)
    typer.echo(str(out.resolve()))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
