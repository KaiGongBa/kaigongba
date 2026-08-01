from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse

from fastapi import HTTPException
from sqlmodel import Session, select

from app.db.models import (
    ExternalAgentConnection,
    ExternalAgentNetworkPolicy,
)


def get_or_create_network_policy(
    db: Session,
    connection: ExternalAgentConnection,
) -> ExternalAgentNetworkPolicy:
    policy = db.exec(
        select(ExternalAgentNetworkPolicy).where(
            ExternalAgentNetworkPolicy.connection_id == connection.id
        )
    ).first()
    if policy:
        return policy
    hostname = (urlparse(connection.endpoint).hostname or "").lower()
    policy = ExternalAgentNetworkPolicy(
        tenant_id=connection.tenant_id,
        organization_id=connection.organization_id,
        connection_id=connection.id,
        allowed_domains_json=[hostname] if hostname else [],
        webhook_delivery_enabled=connection.transport in {"webhook", "a2a"} and bool(hostname),
        updated_by_user_id=connection.created_by_user_id,
    )
    db.add(policy)
    db.flush()
    return policy


def normalize_domains(values: list[str]) -> list[str]:
    result: set[str] = set()
    for raw in values:
        domain = raw.strip().lower().rstrip(".")
        domain = domain.removeprefix("*.")
        if not domain or len(domain) > 253 or "/" in domain or ":" in domain:
            raise HTTPException(status_code=422, detail=f"无效网络域名：{raw}")
        try:
            address = ipaddress.ip_address(domain)
        except ValueError:
            labels = domain.split(".")
            if any(not label or len(label) > 63 for label in labels):
                raise HTTPException(status_code=422, detail=f"无效网络域名：{raw}") from None
        else:
            if _blocked_address(address):
                raise HTTPException(status_code=422, detail=f"网络策略禁止私网/保留地址：{raw}")
        result.add(domain)
    return sorted(result)


def validate_outbound_endpoint(
    endpoint: str,
    policy: ExternalAgentNetworkPolicy,
    *,
    resolve_dns: bool = True,
) -> None:
    parsed = urlparse(endpoint)
    hostname = (parsed.hostname or "").lower().rstrip(".")
    if parsed.scheme != "https" or not hostname or parsed.username or parsed.password:
        raise HTTPException(status_code=422, detail="外部 Agent 端点必须是无内嵌凭据的 HTTPS URL")
    allowed = normalize_domains(policy.allowed_domains_json)
    blocked = normalize_domains(policy.blocked_domains_json)
    if any(_domain_matches(hostname, item) for item in blocked):
        raise HTTPException(status_code=403, detail="外部 Agent 端点命中组织网络黑名单")
    if not allowed or not any(_domain_matches(hostname, item) for item in allowed):
        raise HTTPException(status_code=403, detail="外部 Agent 端点不在组织网络白名单")
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if resolve_dns:
            try:
                resolved = {
                    item[4][0]
                    for item in socket.getaddrinfo(hostname, parsed.port or 443, type=socket.SOCK_STREAM)
                }
            except OSError as exc:
                raise HTTPException(status_code=503, detail="外部 Agent 域名解析失败") from exc
            if not resolved:
                raise HTTPException(status_code=503, detail="外部 Agent 域名没有可用地址") from None
            for raw in resolved:
                if _blocked_address(ipaddress.ip_address(raw)):
                    raise HTTPException(
                        status_code=403,
                        detail="外部 Agent 域名解析到私网或保留地址",
                    ) from None
    else:
        if _blocked_address(address):
            raise HTTPException(status_code=403, detail="外部 Agent 端点不能使用私网或保留地址")


def _domain_matches(hostname: str, policy_domain: str) -> bool:
    return hostname == policy_domain or hostname.endswith(f".{policy_domain}")


def _blocked_address(address: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
    return bool(
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )
