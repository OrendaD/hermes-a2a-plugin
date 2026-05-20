"""SSRF guard — httpx transport that validates destination IPs.

Uses `not addr.is_global` as the catch-all, which correctly catches
RFC 6598 CGNAT addresses (100.64.0.0/10) that Python's `ipaddress.is_private`
misses. The allowlist takes precedence over the blocklist check, so you can
explicitly permit specific CIDR ranges (e.g., your mesh VPN subnet).
"""

from __future__ import annotations

import asyncio
import ipaddress
import socket
from urllib.parse import urlparse

from httpx import AsyncHTTPTransport, HTTPTransport, Request, Response


class SSRFTransport(HTTPTransport):
    """httpx synchronous transport that validates all destinations against an SSRF blocklist.

    Parameters
    ----------
    allow_cidrs:
        Optional list of CIDR strings (e.g. ``["100.96.0.0/16"]``) to explicitly
        allow. These are checked *before* the global-routability check so that
        private infrastructure CIDRs (RFC 1918, CGNAT, etc.) can be permitted
        when they are part of the trusted mesh.
    **kwargs:
        Forwarded to ``httpx.HTTPTransport``.
    """

    def __init__(self, allow_cidrs: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._allow_cidrs = [ipaddress.ip_network(c) for c in (allow_cidrs or [])]

    # ------------------------------------------------------------------
    # Internal validation
    # ------------------------------------------------------------------

    def _is_allowed(self, ip_str: str) -> bool:
        """Return *True* if the IP is allowed to be connected to."""
        addr = ipaddress.ip_address(ip_str)

        # Explicit allowlist takes precedence
        for net in self._allow_cidrs:
            if addr in net:
                return True

        # ``is_global`` is the primary gate — it returns *False* for:
        #   - RFC 1918  (10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16)
        #   - RFC 6598  (100.64.0.0/10, aka CGNAT — missed by ``is_private``)
        #   - Loopback (127.0.0.0/8, ::1)
        #   - Link-local (169.254.0.0/16, fe80::/10)
        #
        # NOTE: Python's ``is_global`` does *not* exclude multicast (224.0.0.0/4)
        #       for IPv4 (it does for IPv6). We explicitly check those too so
        #       the guard isn't weaker for v4 destinations.
        if not addr.is_global:
            return False
        # Explicitly block multicast and reserved ranges
        if addr.is_multicast or addr.is_reserved:
            return False

        return True

    def _validate_url(self, url: str) -> None:
        """Resolve *url* and raise ``ValueError`` if any destination IP is blocked."""
        hostname = urlparse(url).hostname
        if not hostname:
            raise ValueError(f"Cannot resolve destination: {url}")

        # Resolve ALL addresses — catches multi-A-record / multi-AAAA
        # attacks where a malicious DNS returns one good IP and one bad IP.
        addrinfos = socket.getaddrinfo(hostname, None)
        for info in addrinfos:
            ip_str = info[4][0]
            if not self._is_allowed(ip_str):
                raise ValueError(
                    f"Blocked SSRF target: {ip_str} (resolved from {hostname})"
                )

    # ------------------------------------------------------------------
    # httpx transport hooks
    # ------------------------------------------------------------------

    def handle_request(self, request: Request) -> Response:
        """Validate every request before sending it."""
        self._validate_url(str(request.url))
        return super().handle_request(request)


class AsyncSSRFTransport(AsyncHTTPTransport):
    """Asynchronous counterpart of :class:`SSRFTransport`.

    Uses ``loop.getaddrinfo`` so DNS resolution does not block the event loop.
    """

    def __init__(self, allow_cidrs: list[str] | None = None, **kwargs):
        super().__init__(**kwargs)
        self._allow_cidrs = [ipaddress.ip_network(c) for c in (allow_cidrs or [])]

    # ------------------------------------------------------------------
    # Internal validation (shared logic, same docstring applied)
    # ------------------------------------------------------------------

    def _is_allowed(self, ip_str: str) -> bool:
        """Return *True* if the IP may be connected to.

        See ``SSRFTransport._is_allowed`` for the full semantics.
        """
        addr = ipaddress.ip_address(ip_str)
        for net in self._allow_cidrs:
            if addr in net:
                return True
        if not addr.is_global:
            return False
        if addr.is_multicast or addr.is_reserved:
            return False
        return True

    async def _validate_url(self, url: str) -> None:
        """Async DNS resolution + IP validation for *url*."""
        hostname = urlparse(url).hostname
        if not hostname:
            raise ValueError(f"Cannot resolve destination: {url}")

        loop = asyncio.get_running_loop()
        addrinfos = await loop.getaddrinfo(hostname, None)
        for info in addrinfos:
            ip_str = info[4][0]
            if not self._is_allowed(ip_str):
                raise ValueError(
                    f"Blocked SSRF target: {ip_str} (resolved from {hostname})"
                )

    # ------------------------------------------------------------------
    # httpx transport hooks
    # ------------------------------------------------------------------

    async def handle_async_request(self, request: Request) -> Response:
        """Validate every async request before sending it."""
        await self._validate_url(str(request.url))
        return await super().handle_async_request(request)
