"""Jaded Rose Chatbot — FastAPI application entry point.

Mounts webhook routes for Telegram, WhatsApp and Gmail, exposes a WebSocket
endpoint for the web chat widget, and starts the Telegram bot poller on
application startup.
"""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from channels.telegram.webhooks import router as telegram_router
from channels.whatsapp.webhooks import router as whatsapp_router
from channels.gmail.listener import router as gmail_router
from channels.web.api import router as web_router
from channels.telegram.bot import start_telegram_polling, stop_telegram_polling


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Manage startup and shutdown lifecycle events."""
    # Start Telegram polling in a background task
    polling_task = asyncio.create_task(start_telegram_polling())
    yield
    # Graceful shutdown
    await stop_telegram_polling()
    polling_task.cancel()
    try:
        await polling_task
    except asyncio.CancelledError:
        pass


app = FastAPI(
    title="Jaded Rose Chatbot",
    description="Multi-channel AI customer service chatbot for Jaded Rose",
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow the web widget to connect from any Shopify storefront
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Routes ──────────────────────────────────────────────────────────────
app.include_router(telegram_router, prefix="/webhook/telegram", tags=["Telegram"])
app.include_router(whatsapp_router, prefix="/webhook/whatsapp", tags=["WhatsApp"])
app.include_router(gmail_router, prefix="/webhook/gmail", tags=["Gmail"])
app.include_router(web_router, tags=["Web Chat"])

# Serve the web widget static files
app.mount("/static", StaticFiles(directory="channels/web"), name="static")


@app.get("/health", tags=["Health"])
async def health_check() -> JSONResponse:
    """Return a simple health-check response."""
    return JSONResponse(content={"status": "ok", "service": "jaded-rose-chatbot"})
