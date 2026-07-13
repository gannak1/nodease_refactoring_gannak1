"""Fail-closed HTTP/session configuration helpers."""

from urllib.parse import urlsplit


_DEVELOPMENT_SESSION_SECRET = "your-secret-key-change-in-production"


def resolve_session_signing_secret(
    configured_secret: str | None,
    *,
    node_env: str | None,
) -> str:
    secret = configured_secret or ""
    is_blank = not secret.strip()
    normalized_environment = (node_env or "").strip().lower()
    if normalized_environment == "production" and (
        is_blank or secret.strip() == _DEVELOPMENT_SESSION_SECRET
    ):
        raise RuntimeError("Production session signing secret is not configured")
    return secret if not is_blank else _DEVELOPMENT_SESSION_SECRET


def parse_credentialed_cors_origins(raw_value: str) -> list[str]:
    origins: list[str] = []
    for raw_origin in raw_value.split(","):
        origin = raw_origin.strip()
        if not origin:
            continue
        if origin == "*":
            raise RuntimeError("Credentialed CORS does not allow wildcard origins")

        parsed = urlsplit(origin)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("CORS_ORIGINS must contain HTTP(S) origins")

        normalized = f"{parsed.scheme}://{parsed.netloc}"
        if normalized not in origins:
            origins.append(normalized)

    if not origins:
        raise RuntimeError("At least one credentialed CORS origin is required")
    return origins
