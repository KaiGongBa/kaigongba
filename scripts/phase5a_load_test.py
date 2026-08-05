#!/usr/bin/env python3
from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import statistics
import sys
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
    parser.add_argument("--warmup", type=int, default=10)
    parser.add_argument("--timeout", type=float, default=5.0)
    parser.add_argument("--p95-ms", type=float, default=800.0)
    parser.add_argument("--max-failure-rate", type=float, default=0.0)
    parser.add_argument("--expected-status", type=int, default=200)
    parser.add_argument("--output")
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
    if args.warmup < 0 or args.warmup > 10_000:
        raise SystemExit("--warmup must be between 0 and 10000")
    if not 0 <= args.max_failure_rate <= 1:
        raise SystemExit("--max-failure-rate must be between 0 and 1")
    if args.expected_status < 100 or args.expected_status > 599:
        raise SystemExit("--expected-status must be a valid HTTP status")
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

    if args.warmup:
        with concurrent.futures.ThreadPoolExecutor(max_workers=min(args.concurrency, args.warmup)) as executor:
            warmup_results = list(executor.map(request_once, range(args.warmup)))
        if any(status != args.expected_status for status, _latency in warmup_results):
            raise SystemExit("Warmup failed; refusing to start measured load")

    started = time.perf_counter()
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as executor:
        results = list(executor.map(request_once, range(args.requests)))
    duration = time.perf_counter() - started
    latencies = sorted(item[1] for item in results)
    statuses: dict[str, int] = {}
    for status, _latency in results:
        statuses[str(status)] = statuses.get(str(status), 0) + 1
    def percentile(fraction: float) -> float:
        return latencies[max(0, min(len(latencies) - 1, int(len(latencies) * fraction) - 1))]

    p50 = percentile(0.50)
    p95 = percentile(0.95)
    p99 = percentile(0.99)
    failures = sum(count for status, count in statuses.items() if int(status) != args.expected_status)
    failure_rate = failures / args.requests
    report = {
        "target": target,
        "requests": args.requests,
        "concurrency": args.concurrency,
        "warmup_requests": args.warmup,
        "expected_status": args.expected_status,
        "duration_seconds": round(duration, 3),
        "requests_per_second": round(args.requests / duration, 2),
        "latency_ms": {
            "mean": round(statistics.fmean(latencies), 2),
            "p50": round(p50, 2),
            "p95": round(p95, 2),
            "p99": round(p99, 2),
            "max": round(max(latencies), 2),
        },
        "statuses": statuses,
        "failure_rate": round(failure_rate, 4),
        "thresholds": {
            "p95_ms": args.p95_ms,
            "max_failure_rate": args.max_failure_rate,
        },
        "passed": failure_rate <= args.max_failure_rate and p95 <= args.p95_ms,
    }
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        from pathlib import Path

        output = Path(args.output)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(payload)
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, urllib.error.URLError) as exc:
        print(f"Load test failed: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
