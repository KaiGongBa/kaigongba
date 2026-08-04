from pydantic import BaseModel


class IdentityResolveRequest(BaseModel):
    access_token: str


class IdentityProjection(BaseModel):
    id: str
    tenant_id: str
    username: str
    display_name: str | None = None
    role: str
    source: str
