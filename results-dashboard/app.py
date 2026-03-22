from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import streamlit as st

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DJANGO = REPO_ROOT / "benchmark-results" / "django-sweep-result.json"
DEFAULT_FASTAPI = REPO_ROOT / "benchmark-results" / "fastapi-sweep-result.json"

STACK_COLORS = {"django": "#34d399", "fastapi": "#2dd4bf"}
STACK_ORDER = ["django", "fastapi"]
PLOTLY_TEMPLATE = "plotly_dark"

BENCH_HINT = """
Run sweeps from the repo root (after servers are up), then refresh this page:

```text
uv run bench --target http://127.0.0.1:8000/chat/ --levels 1,5,10,25,50 --requests 200 --sleep-ms 200
uv run bench --target http://127.0.0.1:8001/chat --levels 1,5,10,25,50 --requests 200 --sleep-ms 200
```
"""


def _load_json_path(path: Path) -> dict[str, Any] | None:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _normalize_sweep(payload: dict[str, Any]) -> pd.DataFrame:
    stack = str(payload.get("output_stack") or "unknown").lower()
    rows: list[dict[str, Any]] = []
    for run in payload.get("runs") or []:
        load = run.get("load") or {}
        res = run.get("results") or {}
        lat = res.get("latency_s") or {}
        th = res.get("server_thread_count") or {}
        obs = res.get("server_observed") or None
        rss_mean_mib = float("nan")
        cpu_delta = float("nan")
        if isinstance(obs, dict):
            rb = obs.get("rss_bytes")
            if isinstance(rb, dict) and rb.get("mean") is not None:
                rss_mean_mib = float(rb["mean"]) / (1024.0**2)
            cd = obs.get("cpu_time_delta_s_approx")
            if cd is not None:
                cpu_delta = float(cd)
        tm = th.get("mean")
        threads_mean = float(tm) if tm is not None else float("nan")
        rows.append(
            {
                "stack": stack,
                "concurrency": int(load.get("concurrency") or 0),
                "requests": int(load.get("requests") or 0),
                "sleep_ms": int(load.get("sleep_ms") or 0),
                "rps": float(res.get("requests_per_second") or 0.0),
                "wall_s": float(res.get("wall_s") or 0.0),
                "lat_min": float(lat.get("min") or 0.0),
                "lat_p50": float(lat.get("p50") or 0.0),
                "lat_p95": float(lat.get("p95") or 0.0),
                "lat_max": float(lat.get("max") or 0.0),
                "threads_mean": threads_mean,
                "rss_mean_mib": rss_mean_mib,
                "cpu_delta_s": cpu_delta,
                "fail": int(res.get("fail") or 0),
                "ok": int(res.get("ok") or 0),
                "errors": list(run.get("errors") or []),
            }
        )
    return pd.DataFrame(rows)


def _color_map() -> dict[str, str]:
    return {s: STACK_COLORS.get(s, "#94a3b8") for s in STACK_ORDER}


def _ordered_concurrency(df: pd.DataFrame) -> list[Any]:
    return sorted(df["concurrency"].unique().tolist())


def _join_concurrency_phrase(levels: list[int]) -> str:
    parts = [f"{x:,}" for x in levels]
    if len(parts) == 1:
        return parts[0]
    if len(parts) == 2:
        return f"{parts[0]}, then {parts[1]}"
    return ", ".join(parts[:-1]) + f", and {parts[-1]}"


def fig_grouped_bar(
    df: pd.DataFrame,
    y: str,
    title: str,
    y_title: str,
) -> go.Figure:
    d = df.copy()
    d["stack"] = pd.Categorical(d["stack"], categories=STACK_ORDER, ordered=True)
    d = d.sort_values(["concurrency", "stack"])
    fig = px.bar(
        d,
        x="concurrency",
        y=y,
        color="stack",
        barmode="group",
        title=title,
        labels={"concurrency": "Concurrency", y: y_title, "stack": "Stack"},
        color_discrete_map=_color_map(),
        category_orders={"concurrency": _ordered_concurrency(d)},
    )
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        legend_title_text="",
        margin=dict(t=48, b=48),
        xaxis=dict(type="category"),
    )
    return fig


def fig_latency_lines(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    conc_order = _ordered_concurrency(df)
    for stack in STACK_ORDER:
        sub = df[df["stack"] == stack].set_index("concurrency").reindex(conc_order)
        x = sub.index.tolist()
        c = STACK_COLORS.get(stack, "#94a3b8")
        fig.add_trace(
            go.Scatter(
                x=x,
                y=sub["lat_p50"].tolist(),
                mode="lines+markers",
                name=f"{stack} p50",
                line=dict(color=c, width=2),
                marker=dict(size=8),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=sub["lat_p95"].tolist(),
                mode="lines+markers",
                name=f"{stack} p95",
                line=dict(color=c, width=2, dash="dash"),
                marker=dict(size=8, symbol="diamond"),
            )
        )
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title="Latency vs concurrency (seconds)",
        xaxis_title="Concurrency",
        yaxis_title="Latency (s)",
        legend_title_text="",
        margin=dict(t=48, b=48),
        xaxis=dict(type="category", categoryorder="array", categoryarray=conc_order),
    )
    return fig


def fig_threads(df: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    conc_order = _ordered_concurrency(df)
    for stack in STACK_ORDER:
        sub = df[df["stack"] == stack].set_index("concurrency").reindex(conc_order)
        c = STACK_COLORS.get(stack, "#94a3b8")
        fig.add_trace(
            go.Scatter(
                x=sub.index.tolist(),
                y=sub["threads_mean"].tolist(),
                mode="lines+markers",
                name=stack,
                line=dict(color=c, width=2),
                marker=dict(size=9),
            )
        )
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title="Mean observed server thread count vs concurrency",
        xaxis_title="Concurrency",
        yaxis_title="Threads (mean)",
        legend_title_text="",
        margin=dict(t=48, b=48),
        xaxis=dict(type="category", categoryorder="array", categoryarray=conc_order),
    )
    return fig


def _hex_to_rgba_fill(hex_color: str, alpha: float) -> str:
    h = hex_color.lstrip("#")
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r},{g},{b},{alpha})"


def fig_latency_spread_fixed(df: pd.DataFrame) -> go.Figure:
    conc_order = _ordered_concurrency(df)
    fig = make_subplots(
        rows=1,
        cols=2,
        subplot_titles=("Django", "FastAPI"),
        shared_yaxes=True,
    )
    for col, stack in enumerate(STACK_ORDER, start=1):
        sub = df[df["stack"] == stack].set_index("concurrency").reindex(conc_order)
        x = sub.index.tolist()
        c = STACK_COLORS.get(stack, "#94a3b8")
        fill_rgba = _hex_to_rgba_fill(c, 0.28)
        fig.add_trace(
            go.Scatter(
                x=x + x[::-1],
                y=sub["lat_max"].tolist() + sub["lat_min"].tolist()[::-1],
                fill="toself",
                fillcolor=fill_rgba,
                line=dict(color="rgba(0,0,0,0)"),
                name=f"{stack} min–max",
                showlegend=col == 1,
                hoverinfo="skip",
            ),
            row=1,
            col=col,
        )
        fig.add_trace(
            go.Scatter(
                x=x,
                y=sub["lat_p50"].tolist(),
                mode="lines+markers",
                name=f"{stack} p50",
                line=dict(color=c, width=2.5),
                marker=dict(size=8),
            ),
            row=1,
            col=col,
        )
    fig.update_layout(
        template=PLOTLY_TEMPLATE,
        title="Latency spread (min–max band) and median (p50)",
        margin=dict(t=56, b=40),
        height=400,
    )
    fig.update_xaxes(type="category", categoryorder="array", categoryarray=conc_order)
    fig.update_yaxes(title_text="Latency (s)", row=1, col=1)
    return fig


def main() -> None:
    st.set_page_config(
        page_title="Django versus FastAPI - I/O-bound benchmark results",
        layout="wide",
        initial_sidebar_state="collapsed",
    )

    st.markdown(
        "<style>[data-testid='stSidebar']{display:none}[data-testid='collapsedControl']{display:none}</style>",
        unsafe_allow_html=True,
    )

    st.markdown(
        "<h1 style='margin-bottom:0.85rem;color:#f8fafc;font-size:1.85rem;line-height:1.25;font-weight:600;'>"
        "Django versus FastAPI - I/O-bound benchmark results</h1>",
        unsafe_allow_html=True,
    )

    d_raw = _load_json_path(DEFAULT_DJANGO)
    f_raw = _load_json_path(DEFAULT_FASTAPI)

    missing: list[str] = []
    if d_raw is None:
        missing.append("Django")
    if f_raw is None:
        missing.append("FastAPI")

    if missing:
        st.warning(
            "Could not load: **"
            + "**, **".join(missing)
            + f"**. Expected `{DEFAULT_DJANGO.name}` and `{DEFAULT_FASTAPI.name}` under `{DEFAULT_DJANGO.parent}`."
        )
        st.markdown(BENCH_HINT)
        st.stop()

    df_d = _normalize_sweep(d_raw)
    df_f = _normalize_sweep(f_raw)
    if df_d.empty and df_f.empty:
        st.error("Both JSON files have no `runs`.")
        st.markdown(BENCH_HINT)
        st.stop()

    df = pd.concat([df_d, df_f], ignore_index=True)
    if df.empty:
        st.error("No benchmark rows to display.")
        st.stop()

    conc_d = set(df_d["concurrency"].unique()) if not df_d.empty else set()
    conc_f = set(df_f["concurrency"].unique()) if not df_f.empty else set()
    intersection = sorted(conc_d & conc_f)
    only_d = sorted(conc_d - conc_f)
    only_f = sorted(conc_f - conc_d)

    if only_d or only_f:
        st.info(
            "Concurrency levels only in one file are excluded from head-to-head charts: "
            f"Django-only {only_d or '—'}, FastAPI-only {only_f or '—'}. "
            f"Overlapping levels: **{intersection or 'none'}**."
        )

    if not intersection:
        st.error("No overlapping concurrency levels between Django and FastAPI runs.")
        if not df_d.empty:
            st.subheader("Django (unpaired)")
            st.dataframe(df_d, width="stretch")
        if not df_f.empty:
            st.subheader("FastAPI (unpaired)")
            st.dataframe(df_f, width="stretch")
        st.stop()

    df_cmp = df[df["concurrency"].isin(intersection)].copy()
    df_cmp["stack"] = pd.Categorical(
        df_cmp["stack"], categories=STACK_ORDER, ordered=True
    )

    workload_issues: list[str] = []
    for c in intersection:
        rows = df_cmp[df_cmp["concurrency"] == c]
        if len(rows) < 2:
            continue
        rq = rows["requests"].unique()
        sl = rows["sleep_ms"].unique()
        if len(rq) > 1 or len(sl) > 1:
            workload_issues.append(
                f"Concurrency **{c}**: requests {rq.tolist()}, sleep_ms {sl.tolist()} — workloads differ between stacks."
            )
    if workload_issues:
        for msg in workload_issues:
            st.warning(msg)

    rq_vals = df_cmp["requests"].dropna().unique()
    sl_vals = df_cmp["sleep_ms"].dropna().unique()
    if len(rq_vals) == 1 and len(sl_vals) == 1:
        n_req = int(rq_vals[0])
        sleep_ms = int(sl_vals[0])
        conc_phrase = _join_concurrency_phrase(intersection)
        st.markdown(
            "<p style='color:#94a3b8;font-size:1.02rem;line-height:1.55;margin:0 0 1.25rem 0;'>"
            f"We loaded paired sweep JSON from <code>benchmark-results/</code> for Django and FastAPI. "
            f"Each step in that sweep issues <strong>{n_req:,}</strong> <code>POST /chat</code> requests; "
            f"each handler sleeps <strong>{sleep_ms:,}</strong> ms to stand in for downstream I/O. "
            f"The httpx client kept up to <strong>{conc_phrase}</strong> requests in flight at a time. "
            f"Charts compare the two stacks only for matching concurrency levels in both files."
            "</p>",
            unsafe_allow_html=True,
        )
    else:
        st.markdown(
            "<p style='color:#94a3b8;font-size:1.02rem;line-height:1.55;margin:0 0 1.25rem 0;'>"
            "We loaded sweep JSON for both stacks from <code>benchmark-results/</code>, but request counts or "
            "<code>sleep_ms</code> differ across rows—use the Raw normalized rows expander to inspect. "
            "Compare only where the workload matches."
            "</p>",
            unsafe_allow_html=True,
        )

    fail_runs = df[(df["fail"] > 0) | df["errors"].apply(len)]
    if not fail_runs.empty:
        with st.expander("Failures and error messages (from JSON)", expanded=True):
            for _, row in fail_runs.iterrows():
                st.write(
                    f"**{row['stack']}** @ concurrency {row['concurrency']}: "
                    f"fail={row['fail']}, ok={row['ok']}"
                )
                if row["errors"]:
                    st.code("\n".join(str(e) for e in row["errors"]))

    max_c = max(intersection)
    row_max = df_cmp[df_cmp["concurrency"] == max_c]
    d_max = (
        row_max[row_max["stack"] == "django"].iloc[0]
        if len(row_max[row_max["stack"] == "django"])
        else None
    )
    f_max = (
        row_max[row_max["stack"] == "fastapi"].iloc[0]
        if len(row_max[row_max["stack"] == "fastapi"])
        else None
    )

    m1, m2, m3, m4 = st.columns(4)
    if d_max is not None and f_max is not None:
        rps_dj_fa = d_max["rps"] / f_max["rps"] if f_max["rps"] > 0 else float("nan")
        lat_dj_fa = (
            d_max["lat_p95"] / f_max["lat_p95"]
            if f_max["lat_p95"] > 0
            else float("nan")
        )
        m1.metric(
            "RPS @ max concurrency",
            f"{d_max['rps']:.1f} vs {f_max['rps']:.1f}",
            f"{rps_dj_fa:.2f}× Django/FastAPI",
        )
        m2.metric(
            "p95 latency (s) @ max",
            f"{d_max['lat_p95']:.2f} vs {f_max['lat_p95']:.2f}",
            f"{lat_dj_fa:.2f}× Django/FastAPI (lower is better)",
        )
        wall_dj_fa = (
            d_max["wall_s"] / f_max["wall_s"] if f_max["wall_s"] > 0 else float("nan")
        )
        if wall_dj_fa > 1:
            wall_delta = (
                f"{wall_dj_fa:.2f}× Django/FastAPI — FastAPI ~{wall_dj_fa:.2f}× faster"
            )
        elif 0 < wall_dj_fa < 1:
            wall_delta = f"{wall_dj_fa:.2f}× Django/FastAPI — Django ~{1 / wall_dj_fa:.2f}× faster"
        elif wall_dj_fa == 1:
            wall_delta = f"{wall_dj_fa:.2f}× Django/FastAPI"
        else:
            wall_delta = "—"
        m3.metric(
            "Wall time (s) @ max",
            f"{d_max['wall_s']:.2f} vs {f_max['wall_s']:.2f}",
            wall_delta,
        )
        thr_d = d_max["threads_mean"]
        thr_f = f_max["threads_mean"]
        if pd.notna(thr_d) and pd.notna(thr_f) and thr_f > 0:
            m4.metric(
                "Mean threads @ max",
                f"{thr_d:.1f} vs {thr_f:.1f}",
                f"{thr_d / thr_f:.2f}× Django/FastAPI",
            )
        else:
            m4.metric(
                "Mean threads @ max",
                f"{thr_d if pd.notna(thr_d) else '—'} vs {thr_f if pd.notna(thr_f) else '—'}",
            )

    st.divider()
    st.subheader("Charts")

    c1, c2 = st.columns(2)
    with c1:
        st.plotly_chart(
            fig_grouped_bar(df_cmp, "rps", "Throughput", "Requests per second"),
            width="stretch",
        )
    with c2:
        st.plotly_chart(
            fig_grouped_bar(df_cmp, "wall_s", "Total batch duration", "Wall time (s)"),
            width="stretch",
        )

    st.plotly_chart(fig_latency_lines(df_cmp), width="stretch")
    st.plotly_chart(fig_latency_spread_fixed(df_cmp), width="stretch")

    c3, c4 = st.columns(2)
    with c3:
        st.plotly_chart(fig_threads(df_cmp), width="stretch")
    with c4:
        rss_ok = df_cmp["rss_mean_mib"].notna().any()
        if rss_ok:
            st.plotly_chart(
                fig_grouped_bar(
                    df_cmp[df_cmp["rss_mean_mib"].notna()],
                    "rss_mean_mib",
                    "Mean RSS (MiB)",
                    "MiB",
                ),
                width="stretch",
            )
        else:
            st.info(
                "No `server_observed` RSS in JSON — run benchmarks with server stats in responses to plot memory."
            )

    cpu_ok = df_cmp.groupby("stack", observed=True)["cpu_delta_s"].apply(
        lambda s: s.notna().any()
    )
    if cpu_ok.get("django", False) and cpu_ok.get("fastapi", False):
        st.plotly_chart(
            fig_grouped_bar(
                df_cmp[df_cmp["cpu_delta_s"].notna()],
                "cpu_delta_s",
                "Approx. CPU time delta (server-reported)",
                "Seconds (approx.)",
            ),
            width="stretch",
        )

    with st.expander("Raw normalized rows"):
        st.dataframe(df_cmp.sort_values(["concurrency", "stack"]), width="stretch")


if __name__ == "__main__":
    main()
