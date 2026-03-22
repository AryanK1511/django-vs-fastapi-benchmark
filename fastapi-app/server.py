import asyncio
import logging
import os
import threading
import time
import uuid

import psutil
from fastapi import FastAPI
from pydantic import BaseModel, Field

from eval.util import bytes_human, percent_of_host

logging.basicConfig(level=logging.INFO)

app = FastAPI()
logger = logging.getLogger(__name__)


class ChatBody(BaseModel):
    sleep_ms: int = Field(default=200, ge=0, le=600_000)


@app.post("/chat")
async def chat(body: ChatBody):
    # Generate a unique request ID for the current request
    request_id = str(uuid.uuid4())

    logger.info(
        "chat start request_id=%s sleep_ms=%s pid=%s",
        request_id,
        body.sleep_ms,
        os.getpid(),
    )

    # Use the sleep_ms from the request body to sleep for the specified duration
    sleep_s = body.sleep_ms / 1000.0

    # Measure the time it takes to sleep for the specified duration
    # The elapsed time should be very close to sleep_s, but under load with thread contention it might drift
    t0 = time.perf_counter()
    await asyncio.sleep(sleep_s)
    elapsed = time.perf_counter() - t0

    # Thread info
    all_threads = threading.enumerate()
    thread_count = threading.active_count()
    thread_names = [t.name for t in all_threads]

    # Memory info
    proc = psutil.Process()
    mi = proc.memory_info()
    rss = int(mi.rss)
    mem_pct = proc.memory_percent()

    # CPU info
    ct = proc.cpu_times()
    cpu_u = float(ct.user)
    cpu_sys = float(ct.system)
    cpu_tot = cpu_u + cpu_sys

    logger.info(
        "chat done request_id=%s elapsed_s=%s thread_count=%s rss_human=%s",
        request_id,
        round(elapsed, 4),
        thread_count,
        bytes_human(rss),
    )

    return {
        "framework": "fastapi",
        "request_id": request_id,
        "pid": os.getpid(),
        "thread_count": thread_count,
        "thread_names": thread_names,
        "thread_name": threading.current_thread().name,
        "sleep_ms": body.sleep_ms,
        "elapsed_s": round(elapsed, 4),
        "server": {
            "rss_bytes": rss,
            "rss_human": bytes_human(rss),
            "mem_percent_of_host": round(mem_pct, 3),
            "mem_percent_display": percent_of_host(mem_pct),
            "cpu_times_s": {
                "user": round(cpu_u, 4),
                "system": round(cpu_sys, 4),
                "total": round(cpu_tot, 4),
            },
        },
    }
