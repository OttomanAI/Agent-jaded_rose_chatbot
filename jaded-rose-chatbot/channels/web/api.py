"""FastAPI WebSocket endpoint for the Jaded Rose web chat widget.

Maintains a persistent connection per browser session, routes messages
through the Supervisor, and streams replies back to the client.
"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from core.memory import ConversationMemory
from core.supervisor import Supervisor

logger = logging.getLogger(__name__)

router = APIRouter()

_supervisor = Supervisor()
_memory = ConversationMemory()


@router.websocket("/ws/chat")
async def websocket_chat(websocket: WebSocket) -> None:
    """Handle a WebSocket connection for the live chat widget.

    Protocol
    --------
    Client sends JSON: ``{"message": "...", "session_id": "..."}``
    Server replies JSON: ``{"reply": "...", "session_id": "..."}``

    If the client omits ``session_id`` a new one is generated and returned
    in the first response so the client can persist it in sessionStorage.

    Args:
        websocket: The incoming WebSocket connection.
    """
    await websocket.accept()
    session_id: str | None = None

    try:
        while True:
            raw = await websocket.receive_text()
            try:
                data = json.loads(raw)
            except json.JSONDecodeError:
                await websocket.send_json({"error": "Invalid JSON"})
                continue

            message = data.get("message", "").strip()
            if not message:
                await websocket.send_json({"error": "Empty message"})
                continue

            # Resolve or create session ID
            session_id = data.get("session_id") or session_id or f"web:{uuid.uuid4().hex[:12]}"

            logger.info("Web chat [%s]: %s", session_id, message[:120])

            # Send a typing indicator so the widget can show animation
            await websocket.send_json({"typing": True, "session_id": session_id})

            try:
                reply = await _supervisor.process(
                    message=message,
                    session_id=session_id,
                    channel="web",
                )
            except Exception:
                logger.exception("Supervisor error for web session %s", session_id)
                reply = (
                    "Sorry, something went wrong on our end. "
                    "Please try again or email us at support@jadedrose.com 💌"
                )

            await websocket.send_json({
                "reply": reply,
                "session_id": session_id,
                "typing": False,
            })

    except WebSocketDisconnect:
        logger.info("Web chat disconnected: %s", session_id)
    except Exception:
        logger.exception("WebSocket error for session %s", session_id)
        try:
            await websocket.close()
        except Exception:
            pass
