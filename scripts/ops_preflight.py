#!/usr/bin/env python3
"""Read-only release preflight for app.kaigongba.net and split-service candidates."""

from __future__ import annotations

import argparse
import json
import socket
import ssl
import sys
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Check:
    name: str
    passed: bool
    severity: str
    detail: str


def _request(base_url: str, path: str, timeout: float) -> tuple[int, dict[str, str], bytes]:
    request = urllib.request.Request(
        f"{base_url.rstrip('/')}{path}",
        headers={"Accept": "application/json", "User-Agent": "kaigongba-ops-preflight/1.0"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, dict(response.headers.items()), response.read()
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, dict(exc.headers.items()), exc.read()
        finally:
            exc.close()


def _json(body: bytes) -> dict[str, Any] | None:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _header(headers: dict[str, str], name: str) -> str:
    lowered = name.lower()
    return next((value for key, value in headers.items() if key.lower() == lowered), "")


def _certificate_check(parsed: urllib.parse.ParseResult, warn_days: int) -> Check | None:
    if parsed.scheme != "https" or not parsed.hostname:
        return None
    port = parsed.port or 443
    context = ssl.create_default_context()
    with (
        socket.create_connection((parsed.hostname, port), timeout=10) as raw,
        context.wrap_socket(raw, server_hostname=parsed.hostname) as wrapped,
    ):
        certificate = wrapped.getpeercert()
    expires_text = str(certificate.get("notAfter") or "")
    if not expires_text:
        return Check("tls-certificate", False, "error", "certificate has no notAfter")
    expires_at = datetime.fromtimestamp(ssl.cert_time_to_seconds(expires_text), UTC)
    remaining_days = (expires_at - datetime.now(UTC)).total_seconds() / 86400
    return Check(
        "tls-certificate",
        remaining_days >= warn_days,
        "error" if remaining_days < warn_days else "info",
        f"expires={expires_at.isoformat()} remaining_days={remaining_days:.1f}",
    )


def run(base_url: str, profile: str, timeout: float, certificate_warn_days: int) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("--base-url must be an absolute HTTP(S) URL")
    if parsed.hostname not in {"127.0.0.1", "localhost", "::1"} and parsed.scheme != "https":
        raise ValueError("non-local preflight targets must use HTTPS")

    checks: list[Check] = []
    certificate = _certificate_check(parsed, certificate_warn_days)
    if certificate:
        checks.append(certificate)

    status, health_headers, health_body = _request(base_url, "/api/health", timeout)
    health = _json(health_body)
    checks.append(
        Check(
            "liveness",
            status == 200 and health is not None and health.get("status") == "ok",
            "error",
            f"status={status} payload_status={health.get('status') if health else 'invalid-json'}",
        )
    )

    status, ready_headers, ready_body = _request(base_url, "/api/ready", timeout)
    ready = _json(ready_body)
    ready_ok = status == 200 and ready is not None and ready.get("status") == "ready"
    checks.append(Check("readiness", ready_ok, "error", f"status={status}"))
    dependencies = ready.get("dependencies") if ready else None
    if isinstance(dependencies, dict):
        database_ok = dependencies.get("database") == "ok"
        checks.append(Check("database-readiness", database_ok, "error", str(dependencies.get("database"))))
        for name, value in sorted(dependencies.items()):
            if name == "database":
                continue
            available = value == "ok"
            strict = profile in {"combined-worker", "split"}
            checks.append(
                Check(
                    f"dependency-{name}",
                    available or not strict,
                    "error" if strict else "warning",
                    str(value),
                )
            )
    else:
        checks.append(
            Check("readiness-dependencies", profile == "compatibility", "error", "missing")
        )

    status, root_headers, body = _request(base_url, "/", timeout)
    content_type = _header(root_headers, "Content-Type")
    checks.append(
        Check(
            "frontend-entrypoint",
            status == 200 and "text/html" in content_type and b"<html" in body.lower(),
            "error",
            f"status={status} content_type={content_type or '-'}",
        )
    )

    status, _internal_headers, _internal_body = _request(
        base_url, "/api/internal/v1/identity/resolve", timeout
    )
    checks.append(Check("internal-api-boundary", status == 404, "error", f"status={status}"))

    security_headers = {
        "Strict-Transport-Security": "max-age=",
        "X-Content-Type-Options": "nosniff",
        "X-Frame-Options": "",
        "Referrer-Policy": "",
    }
    for name, expected_fragment in security_headers.items():
        value = _header(root_headers, name)
        passed = bool(value) and (not expected_fragment or expected_fragment in value)
        checks.append(Check(f"header-{name.lower()}", passed, "error", value or "missing"))

    request_id = _header(ready_headers, "X-Request-ID") or _header(health_headers, "X-Request-ID")
    checks.append(
        Check(
            "request-id-response",
            bool(request_id) or profile == "compatibility",
            "error" if profile in {"combined-worker", "split"} else "warning",
            request_id or "response header missing",
        )
    )

    errors = [item for item in checks if not item.passed and item.severity == "error"]
    warnings = [item for item in checks if not item.passed and item.severity == "warning"]
    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "baseUrl": base_url.rstrip("/"),
        "profile": profile,
        "passed": not errors,
        "errorCount": len(errors),
        "warningCount": len(warnings),
        "checks": [asdict(item) for item in checks],
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="开工吧只读生产预检")
    parser.add_argument("--base-url", required=True)
    parser.add_argument(
        "--profile",
        choices=("compatibility", "combined-worker", "split"),
        default="compatibility",
    )
    parser.add_argument("--timeout", type=float, default=15.0)
    parser.add_argument("--certificate-warn-days", type=int, default=21)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    try:
        report = run(args.base_url, args.profile, args.timeout, args.certificate_warn_days)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        print(f"Operations preflight failed: {exc}", file=sys.stderr)
        return 2
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(payload)
    print(payload, end="")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
