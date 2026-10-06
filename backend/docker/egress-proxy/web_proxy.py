"""hb-egress-proxy, web mode: the open web, never an internal address (TL-18).

The browser in a tenant's ``web`` container reaches the internet only through
this proxy (the container sits on an ``--internal`` network). Unlike the
allow-list mode it lets any public host through, so the check that matters is
the address: every host is resolved here, every address it resolves to must
be public — no loopback, private, link-local (cloud metadata), CGNAT, ULA,
multicast or reserved ranges, IPv4-mapped forms included — and the proxy
connects to an address it checked, so a name that answers differently a moment
later (DNS rebinding) cannot reach an internal host. tinyproxy cannot do this:
it filters names, not the addresses it connects to.

HTTPS is a ``CONNECT`` tunnel to port 443 or 80; plain HTTP is forwarded with
the request line rewritten to origin form. Standard library only.
"""
from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import socket
from urllib.parse import urlsplit

PORT = int(os.environ.get("PORT", "8888"))
# Marks a refusal, so the browser runner reports a refused step rather than a
# page that happens to say "refused".
REFUSED_HEADER = "X-HB-Egress-Refused"
CONNECT_PORTS = {443, 80}
MAX_HEAD = 64 * 1024
log = logging.getLogger("web-proxy")


def is_public(address: str) -> bool:
    try:
        ip = ipaddress.ip_address(address.split("%", 1)[0])
    except ValueError:
        return False
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_global and not ip.is_multicast


class Refused(Exception):
    pass


async def public_address(host: str, port: int) -> str:
    """The address to connect to: refused unless every address is public."""
    host = host.strip("[]")
    try:
        addresses = [str(ipaddress.ip_address(host))]
    except ValueError:
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        except OSError as exc:
            raise Refused(f"cannot resolve {host}: {exc}") from exc
        addresses = [str(info[4][0]) for info in infos]
    blocked = [a for a in addresses if not is_public(a)]
    if not addresses or blocked:
        raise Refused(f"{host} resolves to a non-public address ({', '.join(blocked) or 'none'})")
    return addresses[0]


async def pipe(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
    try:
        while data := await reader.read(65536):
            writer.write(data)
            await writer.drain()
    except (ConnectionError, OSError):
        pass
    finally:
        try:
            writer.close()
        except Exception:  # noqa: BLE001
            pass


async def refuse(writer: asyncio.StreamWriter, reason: str) -> None:
    body = f"refused by the sandbox egress proxy: {reason}\n".encode()
    flat = reason.replace("\r", " ").replace("\n", " ")
    writer.write(b"HTTP/1.1 403 Forbidden\r\nContent-Type: text/plain\r\nConnection: close\r\n"
                 + f"{REFUSED_HEADER}: {flat}\r\nContent-Length: {len(body)}\r\n\r\n".encode() + body)
    try:
        await writer.drain()
    finally:
        writer.close()


async def handle(client_r: asyncio.StreamReader, client_w: asyncio.StreamWriter) -> None:
    try:
        head = await client_r.readuntil(b"\r\n\r\n")
    except (asyncio.IncompleteReadError, asyncio.LimitOverrunError, ConnectionError):
        client_w.close()
        return
    lines = head.decode("latin-1").split("\r\n")
    try:
        method, target, version = lines[0].split(" ", 2)
    except ValueError:
        await refuse(client_w, "bad request line")
        return
    try:
        if method.upper() == "CONNECT":
            host, _, port_s = target.rpartition(":")
            port = int(port_s)
            if port not in CONNECT_PORTS:
                raise Refused(f"port {port} is not allowed")
            address = await public_address(host, port)
            upstream_r, upstream_w = await asyncio.open_connection(address, port)
            client_w.write(b"HTTP/1.1 200 Connection Established\r\n\r\n")
            await client_w.drain()
        else:
            parts = urlsplit(target)
            if parts.scheme != "http" or not parts.hostname:
                raise Refused("only absolute http:// requests and CONNECT tunnels are proxied")
            port = parts.port or 80
            address = await public_address(parts.hostname, port)
            upstream_r, upstream_w = await asyncio.open_connection(address, port)
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
            kept = [h for h in lines[1:] if h and not h.lower().startswith(("proxy-", "connection:"))]
            upstream_w.write(("\r\n".join([f"{method} {path} {version}", *kept, "Connection: close"])
                              + "\r\n\r\n").encode("latin-1"))
            await upstream_w.drain()
    except Refused as exc:
        log.info("refused %s %s: %s", method, target, exc)
        await refuse(client_w, str(exc))
        return
    except (OSError, ValueError) as exc:
        await refuse(client_w, f"cannot connect: {exc}")
        return
    await asyncio.gather(pipe(client_r, upstream_w), pipe(upstream_r, client_w))


async def main() -> None:
    server = await asyncio.start_server(handle, "0.0.0.0", PORT, limit=MAX_HEAD)
    log.info("web egress proxy on :%d", PORT)
    async with server:
        await server.serve_forever()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    asyncio.run(main())
