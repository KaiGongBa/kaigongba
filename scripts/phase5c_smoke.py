#!/usr/bin/env python3
from __future__ import annotations

import json
import os
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
class CheckResult:
    name: str
    method: str
    path: str
    expected: list[int]
    actual: int
    passed: bool
    detail: str


class SmokeFailure(RuntimeError):
    pass


def _required(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise SmokeFailure(f"Missing required environment variable: {name}")
    return value


class ReadOnlySmoke:
    def __init__(self) -> None:
        self.base_url = _required("KGB_PHASE5C_BASE_URL").rstrip("/")
        parsed = urllib.parse.urlparse(self.base_url)
        if parsed.scheme != "https" and parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise SmokeFailure("Non-local Phase 5C smoke targets must use HTTPS")
        self.timeout = float(os.getenv("KGB_PHASE5C_TIMEOUT_SECONDS", "15"))
        self.results: list[CheckResult] = []
        self._ssl_context = ssl.create_default_context()

    def request(
        self,
        name: str,
        method: str,
        path: str,
        *,
        expected: set[int],
        token: str | None = None,
        body: dict[str, Any] | None = None,
    ) -> Any:
        if method not in {"GET", "POST"} or (method == "POST" and path != "/api/auth/login"):
            raise SmokeFailure(f"Read-only smoke rejected mutating request: {method} {path}")
        data = None if body is None else json.dumps(body).encode()
        headers = {"Accept": "application/json"}
        if data is not None:
            headers["Content-Type"] = "application/json"
        if token:
            headers["Authorization"] = f"Bearer {token}"
        request = urllib.request.Request(
            f"{self.base_url}{path}",
            data=data,
            headers=headers,
            method=method,
        )
        status = 0
        payload: Any = None
        detail = ""
        try:
            with urllib.request.urlopen(
                request,
                timeout=self.timeout,
                context=self._ssl_context,
            ) as response:
                status = response.status
                raw = response.read()
        except urllib.error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        except (urllib.error.URLError, TimeoutError) as exc:
            detail = f"network error: {exc.reason if hasattr(exc, 'reason') else exc}"
            self.results.append(CheckResult(name, method, path, sorted(expected), 0, False, detail))
            raise SmokeFailure(f"{name}: {detail}") from exc
        if raw:
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError:
                payload = None
                detail = "non-JSON response"
        passed = status in expected
        self.results.append(
            CheckResult(name, method, path, sorted(expected), status, passed, detail)
        )
        if not passed:
            raise SmokeFailure(f"{name}: expected {sorted(expected)}, got {status}")
        return payload

    def login(self, role: str, username: str, password: str, tenant_id: str) -> str:
        payload = self.request(
            f"{role} login",
            "POST",
            "/api/auth/login",
            expected={200},
            body={"tenant_id": tenant_id, "username": username, "password": password},
        )
        token = payload.get("token") if isinstance(payload, dict) else None
        if not isinstance(token, str) or not token:
            raise SmokeFailure(f"{role} login returned no token")
        return token


def _query(path: str, **values: str) -> str:
    return f"{path}?{urllib.parse.urlencode(values)}"


def run() -> dict[str, Any]:
    smoke = ReadOnlySmoke()
    tenant_id = _required("KGB_PHASE5C_TENANT_ID")
    buyer_org = _required("KGB_PHASE5C_BUYER_ORGANIZATION_ID")
    provider_org = _required("KGB_PHASE5C_PROVIDER_ORGANIZATION_ID")
    order_id = _required("KGB_PHASE5C_ORDER_ID")
    dispute_id = _required("KGB_PHASE5C_DISPUTE_ID")

    smoke.request("liveness", "GET", "/api/health", expected={200})
    smoke.request("readiness", "GET", "/api/ready", expected={200})
    buyer = smoke.login(
        "buyer",
        _required("KGB_PHASE5C_BUYER_USERNAME"),
        _required("KGB_PHASE5C_BUYER_PASSWORD"),
        tenant_id,
    )
    provider = smoke.login(
        "provider",
        _required("KGB_PHASE5C_PROVIDER_USERNAME"),
        _required("KGB_PHASE5C_PROVIDER_PASSWORD"),
        tenant_id,
    )
    admin = smoke.login(
        "admin",
        _required("KGB_PHASE5C_ADMIN_USERNAME"),
        _required("KGB_PHASE5C_ADMIN_PASSWORD"),
        tenant_id,
    )

    buyer_workspace = smoke.request(
        "buyer order workspace",
        "GET",
        _query(f"/api/transactions/orders/{order_id}/workspace", organizationId=buyer_org),
        expected={200},
        token=buyer,
    )
    provider_workspace = smoke.request(
        "provider order workspace",
        "GET",
        _query(f"/api/transactions/orders/{order_id}/workspace", organizationId=provider_org),
        expected={200},
        token=provider,
    )
    if not isinstance(buyer_workspace, dict):
        raise SmokeFailure("Buyer workspace returned an invalid payload")
    if not isinstance(provider_workspace, dict):
        raise SmokeFailure("Provider workspace returned an invalid payload")
    if buyer_workspace.get("perspective") != "buyer":
        raise SmokeFailure("Buyer workspace did not return buyer perspective")
    if provider_workspace.get("perspective") != "provider":
        raise SmokeFailure("Provider workspace did not return provider perspective")

    smoke.request(
        "buyer cross-organization order denial",
        "GET",
        _query(f"/api/transactions/orders/{order_id}/workspace", organizationId=provider_org),
        expected={403},
        token=buyer,
    )
    smoke.request(
        "provider cross-organization order denial",
        "GET",
        _query(f"/api/transactions/orders/{order_id}/workspace", organizationId=buyer_org),
        expected={403},
        token=provider,
    )

    order_payload = buyer_workspace.get("order")
    if not isinstance(order_payload, dict):
        raise SmokeFailure("Buyer workspace returned an invalid order payload")
    payment_order_id = order_payload.get("paymentOrderId")
    if not isinstance(payment_order_id, str) or not payment_order_id:
        raise SmokeFailure("Buyer workspace returned no payment order ID")
    payment_order = smoke.request(
        "demo payment boundary",
        "GET",
        _query(
            f"/api/transactions/payment-orders/{payment_order_id}",
            organizationId=buyer_org,
        ),
        expected={200},
        token=buyer,
    )
    if not isinstance(payment_order, dict) or payment_order.get("channel") != "demo":
        raise SmokeFailure("Payment order is not constrained to the demo channel")

    for label, token, own_org, other_org in (
        ("buyer", buyer, buyer_org, provider_org),
        ("provider", provider, provider_org, buyer_org),
    ):
        smoke.request(
            f"{label} own dispute",
            "GET",
            _query(f"/api/disputes/cases/{dispute_id}", organizationId=own_org),
            expected={200},
            token=token,
        )
        smoke.request(
            f"{label} cross-organization dispute denial",
            "GET",
            _query(f"/api/disputes/cases/{dispute_id}", organizationId=other_org),
            expected={403},
            token=token,
        )

    smoke.request(
        "ordinary user platform dispute denial",
        "GET",
        "/api/disputes/platform/dashboard",
        expected={403},
        token=buyer,
    )
    smoke.request(
        "administrator platform dispute dashboard",
        "GET",
        "/api/disputes/platform/dashboard",
        expected={200},
        token=admin,
    )
    ai_market = smoke.request(
        "AI employee market",
        "GET",
        "/api/marketplace/ai-services",
        expected={200},
        token=buyer,
    )
    skill_market = smoke.request(
        "Skill market",
        "GET",
        "/api/marketplace/skills",
        expected={200},
        token=buyer,
    )
    smoke.request(
        "external Agent management",
        "GET",
        _query("/api/enterprise/external-agents", organizationId=provider_org),
        expected={200},
        token=provider,
    )
    if not isinstance(ai_market, dict) or "items" not in ai_market:
        raise SmokeFailure("AI employee market response is missing items")
    if not isinstance(skill_market, dict) or "items" not in skill_market:
        raise SmokeFailure("Skill market response is missing items")

    return {
        "schemaVersion": 1,
        "generatedAt": datetime.now(UTC).isoformat(),
        "baseUrl": smoke.base_url,
        "mode": "read-only",
        "paymentBoundary": "demo-only",
        "passed": all(item.passed for item in smoke.results),
        "checks": [asdict(item) for item in smoke.results],
    }


def main() -> int:
    try:
        report = run()
    except SmokeFailure as exc:
        print(f"Phase 5C smoke failed: {exc}", file=sys.stderr)
        return 1
    payload = json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    output = os.getenv("KGB_PHASE5C_SMOKE_REPORT", "").strip()
    if output:
        path = Path(output)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(payload)
    print(f"Phase 5C read-only smoke passed: {len(report['checks'])} checks")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
