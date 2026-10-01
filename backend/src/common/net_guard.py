"""common/net_guard.py — refuse fetches of internal addresses (SSRF, TL-08).

A tool that fetches a URL the model chose checks it here first. Only ``http``
and ``https`` are allowed, and every address the host resolves to must be a
public one: no loopback (the platform's own API), private networks, link-local
(``169.254.169.254``, cloud instance metadata), carrier-grade NAT, multicast or
reserved ranges, in IPv4 or IPv6 (including IPv4-mapped IPv6).

A browser checks every request it makes — redirects, frames, subresources and
script-driven navigation — not only the first URL (see
``HeadlessBrowserTool``). DNS is resolved at check time; a host that answers
differently a moment later (DNS rebinding) is out of reach of a check like this
and is why the browser should run behind the egress proxy (TL-15).
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
from typing import Optional
from urllib.parse import urlsplit

__all__ = ["BlockedURL", "check_url", "check_url_sync", "is_public_address"]

_ALLOWED_SCHEMES = frozenset({"http", "https"})


class BlockedURL(ValueError):
    """A URL a tool may not fetch."""


def is_public_address(address: str) -> bool:
    """True for an address on the public internet."""
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


async def _addresses(host: str, port: Optional[int]) -> list[str]:
    loop = asyncio.get_running_loop()
    infos = await loop.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
    return [str(info[4][0]) for info in infos]


def _split(url: str) -> tuple[str, Optional[int]]:
    parts = urlsplit(str(url or "").strip())
    if parts.scheme.lower() not in _ALLOWED_SCHEMES:
        raise BlockedURL(f"only http and https URLs may be fetched, not {parts.scheme or 'none'!r}")
    host = parts.hostname
    if not host:
        raise BlockedURL(f"no host in URL {url!r}")
    try:
        return host, parts.port
    except ValueError as exc:
        raise BlockedURL(f"bad port in URL {url!r}") from exc


def _verdict(host: str, addresses: list[str]) -> None:
    blocked = [a for a in addresses if not is_public_address(a)]
    if not addresses or blocked:
        raise BlockedURL(
            f"{host!r} resolves to a non-public address ({', '.join(blocked) or 'none'}); "
            "internal hosts may not be fetched")


def _literal(host: str) -> Optional[list[str]]:
    try:
        return [str(ipaddress.ip_address(host))]
    except ValueError:
        return None


async def check_url(url: str) -> None:
    """Return when ``url`` may be fetched; raise :class:`BlockedURL` otherwise."""
    host, port = _split(url)
    addresses = _literal(host)
    if addresses is None:
        try:
            addresses = await _addresses(host, port)
        except OSError as exc:
            raise BlockedURL(f"cannot resolve {host!r}: {exc}") from exc
    _verdict(host, addresses)


def check_url_sync(url: str) -> None:
    """:func:`check_url` for synchronous callers (WeasyPrint's URL fetcher)."""
    host, port = _split(url)
    addresses = _literal(host)
    if addresses is None:
        try:
            infos = socket.getaddrinfo(host, port or 443, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise BlockedURL(f"cannot resolve {host!r}: {exc}") from exc
        addresses = [str(info[4][0]) for info in infos]
    _verdict(host, addresses)
