"""Tests for the SSRF guard transport.

Verifies IP-based blocking and allowlisting for both the sync
(``SSRFTransport``) and async (``AsyncSSRFTransport``) transports.

Because real DNS resolution is involved in ``_validate_url``, the
unit-targeted tests call ``_is_allowed`` directly.  A small integration
test exercises the full path with a real public hostname.
"""

from __future__ import annotations

import socket
from unittest.mock import ANY, AsyncMock, patch

import pytest


# ===================================================================
# Sync SSRFTransport — unit tests on _is_allowed
# ===================================================================


class TestSSRFTransportIsAllowed:
    """Direct tests of ``SSRFTransport._is_allowed`` — no DNS needed."""

    @pytest.fixture
    def transport(self):
        from adapter.ssrf import SSRFTransport

        return SSRFTransport()

    @pytest.fixture
    def transport_with_allow(self):
        from adapter.ssrf import SSRFTransport

        return SSRFTransport(allow_cidrs=["100.96.0.0/16"])

    # --- Blocked (non-global) IPs -----------------------------------

    def test_blocks_rfc1918_private(self, transport):
        """10.0.0.1 is RFC 1918 private space — should be blocked."""
        assert not transport._is_allowed("10.0.0.1")

    def test_blocks_rfc1918_192_168(self, transport):
        """192.168.1.1 is RFC 1918 private space — blocked."""
        assert not transport._is_allowed("192.168.1.1")

    def test_blocks_rfc1918_172_16(self, transport):
        """172.16.0.1 is RFC 1918 private space — blocked."""
        assert not transport._is_allowed("172.16.0.1")

    def test_blocks_cgnat(self, transport):
        """100.64.0.0/10 (RFC 6598 CGNAT) — blocked by ``is_global``."""
        assert not transport._is_allowed("100.96.0.1")

    def test_blocks_cgnat_edge_low(self, transport):
        """100.64.0.1 is the first address in CGNAT space."""
        assert not transport._is_allowed("100.64.0.1")

    def test_blocks_cgnat_edge_high(self, transport):
        """100.127.255.255 is the last address in CGNAT space."""
        assert not transport._is_allowed("100.127.255.255")

    def test_blocks_loopback(self, transport):
        """127.0.0.1 is loopback — blocked."""
        assert not transport._is_allowed("127.0.0.1")

    def test_blocks_loopback_ipv6(self, transport):
        """::1 is IPv6 loopback — blocked."""
        assert not transport._is_allowed("::1")

    def test_blocks_link_local(self, transport):
        """169.254.1.1 is link-local — blocked."""
        assert not transport._is_allowed("169.254.1.1")

    def test_blocks_multicast(self, transport):
        """224.0.0.1 is multicast — blocked."""
        assert not transport._is_allowed("224.0.0.1")

    def test_blocks_broadcast(self, transport):
        """255.255.255.255 is the limited broadcast address — blocked."""
        assert not transport._is_allowed("255.255.255.255")

    # --- Allowed (global) IPs --------------------------------------

    def test_allows_public_ipv4(self, transport):
        """8.8.8.8 is publicly routable — allowed."""
        assert transport._is_allowed("8.8.8.8")

    def test_allows_public_ipv6(self, transport):
        """2001:4860:4860::8888 is Google's public DNS IPv6 — allowed."""
        assert transport._is_allowed("2001:4860:4860::8888")

    def test_allows_cloudflare_dns(self, transport):
        """1.1.1.1 is public — allowed."""
        assert transport._is_allowed("1.1.1.1")

    # --- Allowlist --------------------------------------------------

    def test_allowlist_permits_cgnat(self, transport_with_allow):
        """100.96.0.1 is allowed when 100.96.0.0/16 is explicitly listed."""
        assert transport_with_allow._is_allowed("100.96.0.1")

    def test_allowlist_does_not_affect_other_blocks(self, transport_with_allow):
        """10.0.0.1 is still blocked even with an unrelated allowlist."""
        assert not transport_with_allow._is_allowed("10.0.0.1")

    def test_allowlist_exact_cidr_match(self):
        from adapter.ssrf import SSRFTransport

        t = SSRFTransport(allow_cidrs=["10.0.0.0/8"])
        assert t._is_allowed("10.0.0.1")
        assert t._is_allowed("10.255.255.255")
        # But a non-matching private IP should still be blocked
        assert not t._is_allowed("192.168.1.1")

    def test_allowlist_empty_default(self):
        """No allow_cidrs means no extra bypasses."""
        from adapter.ssrf import SSRFTransport

        t = SSRFTransport()
        assert t._allow_cidrs == []

    def test_multiple_allow_cidrs(self):
        """Multiple CIDRs can be allowed simultaneously."""
        from adapter.ssrf import SSRFTransport

        t = SSRFTransport(allow_cidrs=["10.0.0.0/8", "172.16.0.0/12"])
        assert t._is_allowed("10.1.2.3")
        assert t._is_allowed("172.16.0.1")
        assert not t._is_allowed("192.168.1.1")


# ===================================================================
# AsyncSSRFTransport — unit tests on _is_allowed
# ===================================================================


class TestAsyncSSRFTransportIsAllowed:
    """Same semantics for the async transport — shared logic."""

    @pytest.fixture
    def transport(self):
        from adapter.ssrf import AsyncSSRFTransport

        return AsyncSSRFTransport()

    @pytest.fixture
    def transport_with_allow(self):
        from adapter.ssrf import AsyncSSRFTransport

        return AsyncSSRFTransport(allow_cidrs=["100.96.0.0/16"])

    def test_blocks_private(self, transport):
        assert not transport._is_allowed("10.0.0.1")

    def test_blocks_cgnat(self, transport):
        assert not transport._is_allowed("100.96.0.1")

    def test_blocks_loopback(self, transport):
        assert not transport._is_allowed("127.0.0.1")

    def test_allows_public(self, transport):
        assert transport._is_allowed("8.8.8.8")

    def test_allowlist_for_cgnat(self, transport_with_allow):
        assert transport_with_allow._is_allowed("100.96.0.1")


# ===================================================================
# Integration tests — full DNS resolution path
# ===================================================================

# These call ``_validate_url`` which does real ``socket.getaddrinfo``.
# We patch ``socket.getaddrinfo`` (or ``loop.getaddrinfo`` for async)
# to avoid network calls and keep tests hermetic.


class TestSyncValidateUrl:
    """SSRFTransport._validate_url with mocked DNS."""

    @pytest.fixture
    def transport(self):
        from adapter.ssrf import SSRFTransport

        return SSRFTransport()

    def test_allows_public_hostname(self, transport):
        """A hostname that resolves to 8.8.8.8 passes validation."""
        with patch("adapter.ssrf.socket.getaddrinfo", return_value=[
            (socket.AddressFamily.AF_INET, 1, 6, "", ("8.8.8.8", 0)),
        ]):
            transport._validate_url("https://dns.google/")
            # No exception — pass

    def test_blocks_private_hostname(self, transport):
        """A hostname that resolves to 10.0.0.1 is blocked."""
        with patch("adapter.ssrf.socket.getaddrinfo", return_value=[
            (socket.AddressFamily.AF_INET, 1, 6, "", ("10.0.0.1", 0)),
        ]):
            with pytest.raises(ValueError, match="Blocked SSRF target: 10.0.0.1"):
                transport._validate_url("https://internal-secret.example/")

    def test_blocks_cgnat_hostname(self, transport):
        """A hostname that resolves to 100.96.0.1 is blocked (CGNAT)."""
        with patch("adapter.ssrf.socket.getaddrinfo", return_value=[
            (socket.AddressFamily.AF_INET, 1, 6, "", ("100.96.0.1", 0)),
        ]):
            with pytest.raises(ValueError, match="Blocked SSRF target: 100.96.0.1"):
                transport._validate_url("https://cgnat-host.internal/")

    def test_allows_hostname_with_allowlist(self):
        """A hostname resolving to 100.96.0.1 passes when CIDR is allowed."""
        from adapter.ssrf import SSRFTransport

        transport = SSRFTransport(allow_cidrs=["100.96.0.0/16"])
        with patch("adapter.ssrf.socket.getaddrinfo", return_value=[
            (socket.AddressFamily.AF_INET, 1, 6, "", ("100.96.0.1", 0)),
        ]):
            transport._validate_url("https://mesh-peer.internal/")
            # No exception — pass

    def test_multi_a_record_attack_block(self, transport):
        """If DNS returns one public and one private IP, the private one is blocked."""
        with patch("adapter.ssrf.socket.getaddrinfo", return_value=[
            (socket.AddressFamily.AF_INET, 1, 6, "", ("8.8.8.8", 0)),
            (socket.AddressFamily.AF_INET, 1, 6, "", ("10.0.0.1", 0)),
        ]):
            with pytest.raises(ValueError, match="Blocked SSRF target: 10.0.0.1"):
                transport._validate_url("https://split-view.example/")

    def test_raises_on_empty_hostname(self, transport):
        """A URL without a hostname raises a clear error."""
        with pytest.raises(ValueError, match="Cannot resolve destination:"):
            transport._validate_url("https:///path-only")


class TestAsyncValidateUrl:
    """AsyncSSRFTransport._validate_url with mocked DNS."""

    @pytest.fixture
    def transport(self):
        from adapter.ssrf import AsyncSSRFTransport

        return AsyncSSRFTransport()

    @pytest.mark.asyncio
    async def test_allows_public_hostname(self, transport):
        """A hostname that resolves to 8.8.8.8 passes async validation."""
        with patch("adapter.ssrf.asyncio.get_running_loop") as mock_loop_getter:
            loop = mock_loop_getter.return_value
            loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AddressFamily.AF_INET, 1, 6, "", ("8.8.8.8", 0)),
            ])
            await transport._validate_url("https://dns.google/")

    @pytest.mark.asyncio
    async def test_blocks_private_hostname(self, transport):
        """A hostname resolving to 10.0.0.1 is blocked async."""
        with patch("adapter.ssrf.asyncio.get_running_loop") as mock_loop_getter:
            loop = mock_loop_getter.return_value
            loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AddressFamily.AF_INET, 1, 6, "", ("10.0.0.1", 0)),
            ])
            with pytest.raises(ValueError, match="Blocked SSRF target: 10.0.0.1"):
                await transport._validate_url("https://internal.example/")

    @pytest.mark.asyncio
    async def test_blocks_cgnat_hostname(self, transport):
        """CGNAT hostname is blocked in async path too."""
        with patch("adapter.ssrf.asyncio.get_running_loop") as mock_loop_getter:
            loop = mock_loop_getter.return_value
            loop.getaddrinfo = AsyncMock(return_value=[
                (socket.AddressFamily.AF_INET, 1, 6, "", ("100.96.0.1", 0)),
            ])
            with pytest.raises(ValueError, match="Blocked SSRF target: 100.96.0.1"):
                await transport._validate_url("https://cgnat-host.internal/")

    @pytest.mark.asyncio
    async def test_raises_on_empty_hostname(self, transport):
        """Async path also raises on missing hostname."""
        with pytest.raises(ValueError, match="Cannot resolve destination:"):
            await transport._validate_url("ftp:///no-hostname")


# ===================================================================
# End-to-end — real DNS, real httpx client
# ===================================================================


class TestEndToEnd:
    """Full httpx client wired with the SSRF transport."""

    @pytest.fixture
    def sync_client(self):
        import httpx
        from adapter.ssrf import SSRFTransport

        return httpx.Client(transport=SSRFTransport())

    @pytest.fixture
    def async_client(self):
        import httpx
        from adapter.ssrf import AsyncSSRFTransport

        return httpx.AsyncClient(transport=AsyncSSRFTransport())

    def test_sync_blocks_localhost(self, sync_client):
        """A request to 127.0.0.1 raises ValueError."""
        with pytest.raises(ValueError, match="Blocked SSRF target: 127.0.0.1"):
            sync_client.get("http://127.0.0.1:1/")

    def test_sync_blocks_private_hostname(self, sync_client):
        """A request to a hostname resolving to 10.x raises ValueError."""
        with pytest.raises(ValueError, match="Blocked SSRF target"):
            sync_client.get("http://10.0.0.1/")

    def test_sync_blocks_cgnat(self, sync_client):
        """A request to a CGNAT address raises ValueError."""
        with pytest.raises(ValueError, match="Blocked SSRF target: 100.96.0.1"):
            sync_client.get("http://100.96.0.1/")

    @pytest.mark.asyncio
    async def test_async_blocks_localhost(self, async_client):
        """Async transport also blocks 127.0.0.1."""
        with pytest.raises(ValueError, match="Blocked SSRF target: 127.0.0.1"):
            await async_client.get("http://127.0.0.1:1/")

    @pytest.mark.asyncio
    async def test_async_blocks_private(self, async_client):
        """Async transport blocks 10.x."""
        with pytest.raises(ValueError, match="Blocked SSRF target"):
            await async_client.get("http://10.0.0.1/")

    @pytest.mark.asyncio
    async def test_async_blocks_cgnat(self, async_client):
        """Async transport blocks CGNAT."""
        with pytest.raises(ValueError, match="Blocked SSRF target: 100.96.0.1"):
            await async_client.get("http://100.96.0.1/")

    @pytest.mark.skip(reason="Requires network — run manually")
    def test_sync_allows_public(self, sync_client):
        """A real public URL works (skip in CI without network)."""
        response = sync_client.get("https://1.1.1.1/")
        assert response.status_code in (200, 301, 403)

    @pytest.mark.skip(reason="Requires network — run manually")
    @pytest.mark.asyncio
    async def test_async_allows_public(self, async_client):
        """Async real public URL works."""
        response = await async_client.get("https://1.1.1.1/")
        assert response.status_code in (200, 301, 403)
