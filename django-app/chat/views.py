import logging
import os
import threading
import time
import uuid

import psutil
from rest_framework.permissions import AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView

from eval.util import bytes_human, percent_of_host

logger = logging.getLogger(__name__)


class ChatView(APIView):
    authentication_classes = []
    permission_classes = [AllowAny]

    def post(self, request):
        # Fetch sleep milliseconds from request body
        body = request.data if isinstance(request.data, dict) else {}
        sleep_ms = int(body.get("sleep_ms", 200))
        sleep_s = sleep_ms / 1000.0

        # Every request has a unique request ID
        request_id = str(uuid.uuid4())

        logger.info(
            "chat start request_id=%s sleep_ms=%s pid=%s thread=%s",
            request_id,
            sleep_ms,
            os.getpid(),  # PID of the server process
            threading.current_thread().name,  # Name of the current thread
        )

        # Measure the time it takes to sleep for the specified duration
        # The elapsed time should be very close to sleep_s, but under load with thread contention it might drift
        t0 = time.perf_counter()
        time.sleep(sleep_s)
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

        return Response(
            {
                "framework": "django",
                "request_id": request_id,
                "pid": os.getpid(),
                "thread_count": thread_count,
                "thread_names": thread_names,
                "thread_name": threading.current_thread().name,
                "sleep_ms": sleep_ms,
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
        )
