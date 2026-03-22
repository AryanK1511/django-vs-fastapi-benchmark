import asyncio
from pathlib import Path
from typing import Any

import typer

from eval.util import (
    _build_sweep_step_report,
    _default_result_path,
    _resolve_stack,
    _run_load,
    _write_json,
)

cli = typer.Typer()


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
        help="django or fastapi; default: infer from URL port (8000 django, 8001 fastapi).",
    ),
    output: Path | None = typer.Option(
        None,
        "--output",
        "-o",
        help="Override output path (default: benchmark-results/<stack>-sweep-result.json).",
    ),
) -> None:
    conc_levels = [int(x.strip()) for x in levels.split(",") if x.strip()]
    runs: list[dict[str, Any]] = []
    for c in conc_levels:
        wall_s, lat_ok, errs, threads_samples, pids, server_rows = asyncio.run(
            _run_load(target, c, requests, sleep_ms, timeout)
        )
        runs.append(
            _build_sweep_step_report(
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
            )
        )
    resolved_stack = _resolve_stack(target, stack)
    out = output if output is not None else _default_result_path(resolved_stack)
    payload = {
        "mode": "sweep",
        "output_stack": resolved_stack,
        "levels": conc_levels,
        "runs": runs,
    }
    _write_json(out, payload)
    typer.echo(str(out.resolve()))


def main() -> None:
    cli()


if __name__ == "__main__":
    main()
