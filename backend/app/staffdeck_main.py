from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.api import (
    agents,
    channels,
    chat,
    feedback,
    general_skills,
    knowledge,
    knowledge_bases,
    memories,
    mock,
    model_configs,
    persona,
    scheduled_tasks,
    sessions,
    skills,
    staffdeck_internal,
    tools,
    traces,
    ui_config,
)
from app.app_factory import create_api_app
from app.async_jobs import shutdown_async_jobs
from app.channels import start_channel_services, stop_channel_services
from app.config import get_settings
from app.db.startup import prepare_database
from app.scheduled_tasks.worker import start_background_worker, stop_background_worker
from app.service_runtime import validate_staffdeck_runtime


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    validate_staffdeck_runtime(get_settings())
    prepare_database()
    start_background_worker()
    start_channel_services()
    try:
        yield
    finally:
        stop_channel_services()
        stop_background_worker()
        shutdown_async_jobs()


app = create_api_app("staffdeck", lifespan=lifespan)


app.include_router(chat.router)
app.include_router(agents.chat_router)
app.include_router(agents.scope_router)
app.include_router(agents.enterprise_router)
app.include_router(ui_config.chat_router)
app.include_router(ui_config.enterprise_router)
app.include_router(general_skills.router)
app.include_router(knowledge_bases.router)
app.include_router(knowledge.router)
app.include_router(skills.router)
app.include_router(model_configs.router)
app.include_router(memories.router)
app.include_router(feedback.router)
app.include_router(persona.router)
app.include_router(scheduled_tasks.enterprise_router)
app.include_router(scheduled_tasks.chat_router)
app.include_router(scheduled_tasks.chat_draft_router)
app.include_router(channels.router)
app.include_router(tools.router)
app.include_router(tools.mcp_router)
app.include_router(sessions.router)
app.include_router(traces.router)
app.include_router(mock.router)
app.include_router(staffdeck_internal.router)
