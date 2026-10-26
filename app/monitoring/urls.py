"""Helpers for rendering configured service URLs without leaking secrets."""

from urllib.parse import urlsplit, urlunsplit


def safe_service_url(value: str) -> str | None:
    """Return an HTTP(S) URL without credentials, query strings, or fragments."""
    try:
        parsed = urlsplit((value or "").strip())
        scheme = parsed.scheme.lower()
        hostname = parsed.hostname
        port = parsed.port
    except (TypeError, ValueError):
        return None

    if (
        scheme not in {"http", "https"}
        or not hostname
        or any(char.isspace() for char in (value or ""))
    ):
        return None

    # Preserve IPv6 host syntax and explicit ports, but never user-info.
    host = f"[{hostname}]" if ":" in hostname else hostname
    netloc = f"{host}:{port}" if port is not None else host
    path = parsed.path or "/"
    safe = urlunsplit((scheme, netloc, path, "", ""))
    return safe if len(safe) <= 512 else None
