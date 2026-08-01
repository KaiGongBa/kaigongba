from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Annotated

from fastapi import Depends, Header, HTTPException
from sqlmodel import Session, select

from app.db import get_session
from app.db.models import ExternalAgentConnection, ExternalAgentCredential
from app.external_agents.credential_vault import token_digest
from app.external_agents.rate_limit import enforce_external_agent_rate_limit


@dataclass(frozen=True)
class ExternalAgentPrincipal:
    connection: ExternalAgentConnection
    credential: ExternalAgentCredential

    @property
    def scopes(self) -> set[str]:
        return set(self.credential.scopes_json)

    def require_scope(self, scope: str) -> None:
        if scope not in self.scopes:
            raise HTTPException(status_code=403, detail=f"外部 Agent 凭据缺少权限：{scope}")


def require_external_agent(
    db: Annotated[Session, Depends(get_session)],
    authorization: Annotated[str | None, Header()] = None,
) -> ExternalAgentPrincipal:
    scheme, _, token = (authorization or "").partition(" ")
    if scheme.lower() != "bearer" or not token.startswith("kgb_agent_"):
        raise HTTPException(status_code=401, detail="缺少有效的外部 Agent 凭据")
    credential = db.exec(
        select(ExternalAgentCredential).where(
            ExternalAgentCredential.token_digest == token_digest(token),
            ExternalAgentCredential.status == "active",
        )
    ).first()
    if not credential:
        raise HTTPException(status_code=401, detail="外部 Agent 凭据无效或已撤销")
    if credential.expires_at and credential.expires_at <= datetime.now(UTC):
        raise HTTPException(status_code=401, detail="外部 Agent 凭据已过期")
    connection = db.get(ExternalAgentConnection, credential.connection_id)
    if not connection or connection.status == "disconnected":
        raise HTTPException(status_code=401, detail="外部 Agent 连接已断开")
    enforce_external_agent_rate_limit(db, connection)
    return ExternalAgentPrincipal(connection=connection, credential=credential)
