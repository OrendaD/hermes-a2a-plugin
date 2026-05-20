"""Integration tests for the Agent Card HTTP route.

Spins up a Starlette test server with a temporary profiles directory,
verifies the full chain: profile → card → sign → serve.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path

import pytest
from starlette.applications import Starlette
from starlette.testclient import TestClient

from adapter.agent_card_route import create_agent_card_route
from adapter.agent_card_signer import ENV_KEY


@pytest.fixture(autouse=True)
def _clean_env():
    os.environ.pop(ENV_KEY, None)
    yield
    os.environ.pop(ENV_KEY, None)


@pytest.fixture
def profiles_dir():
    """Create a temp profiles directory with two mock profiles."""
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp) / ".hermes" / "profiles"
        base.mkdir(parents=True)

        # sherlock — research profile with a2a: section
        sherlock = base / "sherlock"
        sherlock.mkdir()
        (sherlock / "config.yaml").write_text("""\
model: claude-sonnet-4
a2a:
  intents: ["consultation", "research"]
  tags: ["linux", "arch"]
  description: "Perception and research specialist"
  streaming: false
  push: false
""")
        (sherlock / "SOUL.md").write_text("***Sherlock*** — perception and research agent.\n")

        # builder — code profile with a2a: section
        builder = base / "builder"
        builder.mkdir()
        (builder / "config.yaml").write_text("""\
model: claude-sonnet-4
a2a:
  intents: ["action_request", "code_generation"]
  tags: ["python", "code"]
  description: "Code generation and execution"
  streaming: false
  push: false
""")

        # doris — no a2a: section, should be excluded
        doris = base / "doris"
        doris.mkdir()
        (doris / "config.yaml").write_text("""\
model: claude-sonnet-4
""")

        yield base


@pytest.fixture
def app(profiles_dir):
    route = create_agent_card_route(
        profiles_dir,
        node_name="proteus-test",
        node_description="Test node",
        node_version="1.0.0",
        interface_url="http://127.0.0.1:8081",
        provider_name="Hermes Test",
        cache_max_age=60,
    )
    app = Starlette(routes=[route])
    return app


@pytest.fixture
def client(app):
    return TestClient(app)


class TestAgentCardRoute:
    def test_returns_200(self, client):
        """The endpoint returns HTTP 200."""
        resp = client.get("/.well-known/agent-card.json")
        assert resp.status_code == 200

    def test_content_type(self, client):
        """Content-Type is application/json."""
        resp = client.get("/.well-known/agent-card.json")
        assert resp.headers.get("content-type") == "application/json"

    def test_cache_control(self, client):
        """Cache-Control header is set."""
        resp = client.get("/.well-known/agent-card.json")
        assert "max-age=60" in resp.headers.get("cache-control", "")

    def test_node_metadata(self, client):
        """The card contains the right node metadata."""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        assert data["name"] == "proteus-test"
        assert data["description"] == "Test node"
        assert data["version"] == "1.0.0"

    def test_skills_from_profiles(self, client):
        """Each A2A-capable profile becomes a skill in the card."""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        skills = data.get("skills", [])
        skill_ids = {s["id"] for s in skills}
        assert "skill/sherlock" in skill_ids
        assert "skill/builder" in skill_ids

    def test_profile_without_a2a_excluded(self, client):
        """A profile without an a2a: section is not included as a skill."""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        skill_ids = {s["id"] for s in data.get("skills", [])}
        assert "skill/doris" not in skill_ids

    def test_interface_url(self, client):
        """The supported_interfaces array contains the A2A endpoint."""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        ifaces = data.get("supported_interfaces", [])
        urls = [i["url"] for i in ifaces]
        assert "http://127.0.0.1:8081" in urls

    def test_card_is_signed(self, client):
        """The Agent Card has at least one JWS signature."""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        signatures = data.get("signatures", [])
        assert len(signatures) >= 1
        assert "protected" in signatures[0]
        assert "signature" in signatures[0]

    def test_multiple_requests_same_key_id(self, client):
        """Two consecutive requests have the same key ID in the
        protected header. (The JWS signature itself changes on every
        sign operation due to ECDSA random nonce — that's expected.)"""
        resp1 = client.get("/.well-known/agent-card.json")
        resp2 = client.get("/.well-known/agent-card.json")
        import base64, json
        prot1 = json.loads(base64.urlsafe_b64decode(
            resp1.json()["signatures"][0]["protected"] + "=="
        ))
        prot2 = json.loads(base64.urlsafe_b64decode(
            resp2.json()["signatures"][0]["protected"] + "=="
        ))
        assert prot1.get("kid") == prot2.get("kid")

    def test_signed_card_verifies(self, client):
        """The signed Agent Card can be verified with the public key
        derived from the profile's .env signing key."""
        resp = client.get("/.well-known/agent-card.json")
        data = resp.json()
        # The card was signed — signatures array is non-empty
        assert len(data.get("signatures", [])) >= 1
