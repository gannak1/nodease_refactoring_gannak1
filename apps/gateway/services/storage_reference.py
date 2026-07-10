"""Pure validation helpers for storage object deletion references."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import unquote, urlparse


class StorageDeleteError(RuntimeError):
    """Base error for storage object deletion failures."""


class StorageReferenceError(StorageDeleteError):
    """Raised when a delete reference is outside the configured storage boundary."""


def _invalid_reference() -> StorageReferenceError:
    return StorageReferenceError("storage_reference_invalid")


def _validate_s3_key(key: str) -> str:
    if not key or key.startswith("/") or "\\" in key:
        raise _invalid_reference()
    if len(key.encode("utf-8")) > 1024:
        raise _invalid_reference()
    if any(ord(character) < 32 or ord(character) == 127 for character in key):
        raise _invalid_reference()

    segments = key.split("/")
    if any(segment in {"", ".", ".."} for segment in segments):
        raise _invalid_reference()
    if segments[0] != "uploads":
        raise _invalid_reference()
    return key


def resolve_s3_delete_key(
    reference: str,
    *,
    bucket_name: str,
    region: str | None,
) -> str:
    """Resolve an approved S3 URL/key to the configured bucket's canonical key."""
    raw_reference = str(reference or "").strip()
    bucket = str(bucket_name or "").strip()
    if not raw_reference or not bucket:
        raise _invalid_reference()

    parsed = urlparse(raw_reference)
    if parsed.query or parsed.fragment or parsed.username or parsed.password:
        raise _invalid_reference()

    if parsed.scheme == "s3":
        if parsed.netloc != bucket:
            raise _invalid_reference()
        key = unquote(parsed.path.lstrip("/"))
        return _validate_s3_key(key)

    if parsed.scheme in {"http", "https"}:
        try:
            parsed_port = parsed.port
        except ValueError:
            raise _invalid_reference() from None
        if parsed.scheme != "https" or not parsed.hostname or parsed_port is not None:
            raise _invalid_reference()

        virtual_hosts = {f"{bucket}.s3.amazonaws.com"}
        path_style_hosts = {"s3.amazonaws.com"}
        normalized_region = str(region or "").strip()
        if normalized_region:
            virtual_hosts.add(f"{bucket}.s3.{normalized_region}.amazonaws.com")
            path_style_hosts.add(f"s3.{normalized_region}.amazonaws.com")

        path = unquote(parsed.path.lstrip("/"))
        if parsed.hostname in virtual_hosts:
            key = path
        elif parsed.hostname in path_style_hosts:
            path_bucket, separator, key = path.partition("/")
            if not separator or path_bucket != bucket:
                raise _invalid_reference()
        else:
            raise _invalid_reference()
        return _validate_s3_key(key)

    if parsed.scheme or parsed.netloc:
        raise _invalid_reference()
    return _validate_s3_key(raw_reference)


def resolve_local_delete_path(reference: str, *, upload_root: str | Path) -> Path:
    """Resolve a local delete reference and enforce configured-root containment."""
    raw_reference = str(reference or "").strip()
    if not raw_reference or "://" in raw_reference:
        raise _invalid_reference()

    try:
        root = Path(upload_root).resolve(strict=False)
        candidate = Path(raw_reference)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved = candidate.resolve(strict=False)
    except (OSError, RuntimeError):
        raise _invalid_reference() from None

    try:
        relative = resolved.relative_to(root)
    except ValueError:
        raise _invalid_reference() from None
    if not relative.parts:
        raise _invalid_reference()
    return resolved
