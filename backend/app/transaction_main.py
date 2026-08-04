from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    auth,
    collaboration,
    disputes,
    executions,
    external_agents,
    identity_internal,
    marketplace,
    marketplace_management,
    transactions,
)
from app.app_factory import create_api_app
from app.config import get_settings
from app.db.startup import prepare_database
from app.service_runtime import validate_transaction_runtime
from app.transaction.object_storage import get_order_object_store
from app.transaction.outbox_worker import (
    start_transaction_outbox_worker,
    stop_transaction_outbox_worker,
)


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_transaction_runtime(get_settings())
    prepare_database()
    start_transaction_outbox_worker()
    try:
        yield
    finally:
        stop_transaction_outbox_worker()


app = create_api_app(
    "transaction-core",
    lifespan=lifespan,
    readiness_checks={"object_storage": lambda: get_order_object_store().healthcheck()},
)


app.include_router(auth.router)
app.include_router(identity_internal.router)
app.include_router(marketplace.router)
app.include_router(marketplace_management.router)
app.include_router(transactions.router)
app.include_router(executions.router)
app.include_router(external_agents.enterprise_router)
app.include_router(external_agents.agent_router)
app.include_router(collaboration.router)
app.include_router(disputes.router)
