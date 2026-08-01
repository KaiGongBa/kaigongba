#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request

CONFIRMATION = "RUN_READ_ONLY_LOAD_TEST"


def main() -> int:
    parser = argparse.ArgumentParser(description="开工吧只读 HTTP 压力验收")
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--path", default="/api/ready")
    parser.add_argument("--requests", type=int, default=500)
    parser.add_argument("--concurrency", type=int, default=20)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--p95-ms", type=float, default=800.0)
    args = parser.parse_args()
    parsed = urllib.parse.urlparse(args.base_url)
    safe_host = parsed.hostname in {"127.0.0.1", "localhost"} or "staging" in (parsed.hostname or "")
    if not safe_host and os.getenv("KGB_LOAD_TEST_CONFIRM") != CONFIRMATION:
        raise SystemExit(
            f"Refusing non-local/non-staging target. Set KGB_LOAD_TEST_CONFIRM={CONFIRMATION}."
        )
    if args.requests < 1 or args.requests > 100_000:
        raise SystemExit("--requests must be between 1 and 100000")
    if args.concurrency < 1 or args.concurrency > 500:
        raise SystemExit("--concurrency must be between 1 and 500")
    target = args.base_url.rstrip("/") + "/" + args.path.lstrip("/")

    def request_once(_: int) -> tuple[int, float]:
        started = time.perf_counter()
        request = urllib.request.Request(target, headers={"User-Agent": "kaigongba-phase5a-load/1.0"})
        try:
            with urllib.request.urlopen(request, timeout=args.timeout) as response:
                status = response.status
                response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
        except OSError:
            status = 0
        return status, (time.perf_counter() - started) * 1000

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(request_once, range(args.requests)))
    duration = time.perf_counter() - started
    latencies = sorted(item[1] for item in results)
    statuses: dict[str, int] = {}
    for status, _latency in results:
        statuses[str(status)] = statuses.get(str(status), 0) + 1
    p95 = latencies[max(0, int(len(latencies) * 0.95) - 1)]
    failures = sum(count for status, count in statuses.items() if not status.startswith("2"))
    report = {
        "target": target,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "duration_seconds": round(duration, 3),
        "requests_per_second": round(args.requests / duration, 2),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 2),
            "p95": round(p95, 2),
            "max": round(max(latencies), 2),
        },
        "statuses": statuses,
        "failure_rate": round(failures / args.requests, 4),
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if failures == 0 and p95 <= args.p95_ms else 1


if __name__ == "__main__":
    raise SystemExit(main())
