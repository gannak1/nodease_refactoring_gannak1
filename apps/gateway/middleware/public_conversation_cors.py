from __future__ import annotations

from starlette.types import ASGIApp, Message, Receive, Scope, Send


class PublicConversationCorsBoundaryMiddleware:
    """Keep public Conversation API outside the legacy credentialed CORS mesh.

    Public parent origins authorize iframe embedding through CSP only.  The
    iframe document calls this API same-origin, so target lifecycle routes must
    neither answer cross-origin preflight nor inherit global CORS headers.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if scope["type"] != "http" or not _is_public_conversation_path(
            scope.get("path", "")
        ):
            await self.app(scope, receive, send)
            return

        if scope["method"] == "OPTIONS":
            await send(
                {
                    "type": "http.response.start",
                    "status": 404,
                    "headers": [
                        (b"cache-control", b"no-store"),
                        (b"content-length", b"0"),
                    ],
                }
            )
            await send({"type": "http.response.body", "body": b""})
            return

        async def send_without_cors(message: Message) -> None:
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = _strip_cors_and_origin_vary(
                    message.get("headers", [])
                )
            await send(message)

        await self.app(scope, receive, send_without_cors)


def _is_public_conversation_path(path: str) -> bool:
    prefix = "/api/v1/run-public/"
    if not path.startswith(prefix):
        return False
    remainder = path[len(prefix) :]
    _slug, separator, suffix = remainder.partition("/")
    if not _slug or not separator:
        return False
    return suffix == "conversations" or suffix == "conversation" or suffix.startswith(
        "conversation/"
    )


def _strip_cors_and_origin_vary(
    headers: list[tuple[bytes, bytes]],
) -> list[tuple[bytes, bytes]]:
    sanitized: list[tuple[bytes, bytes]] = []
    for name, value in headers:
        normalized_name = name.lower()
        if normalized_name.startswith(b"access-control-"):
            continue
        if normalized_name == b"vary":
            retained = [
                part.strip()
                for part in value.decode("latin-1").split(",")
                if part.strip().lower() != "origin"
            ]
            if retained:
                sanitized.append((name, ", ".join(retained).encode("latin-1")))
            continue
        sanitized.append((name, value))
    return sanitized


__all__ = ["PublicConversationCorsBoundaryMiddleware"]
