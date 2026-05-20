"""Tests for Agent Card builder — validates protobuf construction and field mapping."""

from __future__ import annotations

from google.protobuf.json_format import ParseDict

from a2a.types import AgentCard, AgentSkill

from core.domain.models.capability import AgentCapability

from adapter.agent_card_builder import build_agent_card, agent_card_to_dict


class TestBuildAgentCard:
    def test_empty_capabilities(self):
        """An empty capabilities list produces a card with no skills."""
        card = build_agent_card([], node_name="test-node")
        assert card.name == "test-node"
        assert len(card.skills) == 0

    def test_single_skill(self):
        """A single capability becomes one AgentSkill."""
        caps = [
            AgentCapability(
                profile_name="sherlock",
                node_id="local",
                display_name="Sherlock",
                description="Perception and research",
                intents=["consultation", "research"],
                tags=["perception", "linux"],
            ),
        ]
        card = build_agent_card(caps, node_name="proteus")
        assert len(card.skills) == 1
        skill = card.skills[0]
        assert skill.id == "skill/sherlock"
        assert skill.name == "Sherlock"
        assert skill.description == "Perception and research"
        assert "consultation" in skill.tags
        assert "linux" in skill.tags

    def test_multiple_skills(self):
        """Multiple capabilities produce multiple AgentSkills."""
        caps = [
            AgentCapability(
                profile_name="sherlock",
                node_id="local",
                display_name="Sherlock",
                description="Research",
                intents=["research"],
            ),
            AgentCapability(
                profile_name="builder",
                node_id="local",
                display_name="Builder",
                description="Code generation",
                intents=["action_request"],
            ),
        ]
        card = build_agent_card(caps, node_name="proteus")
        assert len(card.skills) == 2
        skill_ids = {s.id for s in card.skills}
        assert skill_ids == {"skill/sherlock", "skill/builder"}

    def test_interface_url(self):
        """Interface URL is set on supported_interfaces when provided."""
        card = build_agent_card(
            [],
            node_name="test",
            interface_url="http://100.96.0.2:8081",
        )
        assert len(card.supported_interfaces) == 1
        iface = card.supported_interfaces[0]
        assert iface.protocol_binding == "JSONRPC"
        assert iface.protocol_version == "1.0"
        assert iface.url == "http://100.96.0.2:8081"

    def test_no_interface_when_url_empty(self):
        """No supported_interfaces when interface_url is empty."""
        card = build_agent_card([], node_name="test", interface_url="")
        assert len(card.supported_interfaces) == 0

    def test_provider_info(self):
        """Provider info is set when URL or name provided."""
        card = build_agent_card(
            [],
            node_name="test",
            provider_name="Hermes",
            provider_url="https://hermes-agent.nousresearch.com",
        )
        assert card.provider.organization == "Hermes"
        assert card.provider.url == "https://hermes-agent.nousresearch.com"

    def test_default_input_output_modes(self):
        """Default input/output modes are always set."""
        card = build_agent_card([], node_name="test")
        assert list(card.default_input_modes) == ["text/plain"]
        assert list(card.default_output_modes) == ["text/plain"]

    def test_streaming_and_push_flags(self):
        """Capabilities flags are passed through."""
        card = build_agent_card([], node_name="test", streaming=True, push_notifications=True)
        assert card.capabilities.streaming is True
        assert card.capabilities.push_notifications is True

    def test_skill_examples(self):
        """Capability examples appear on the AgentSkill."""
        caps = [
            AgentCapability(
                profile_name="sherlock",
                node_id="local",
                display_name="Sherlock",
                description="Research",
                intents=["research"],
                examples=['{"topic": "Linux kernel"}'],
            ),
        ]
        card = build_agent_card(caps, node_name="test")
        assert len(card.skills[0].examples) == 1
        assert card.skills[0].examples[0] == '{"topic": "Linux kernel"}'


class TestAgentCardToDict:
    def test_round_trip(self):
        """AgentCard → dict → ParseDict preserves structure."""
        caps = [
            AgentCapability(
                profile_name="sherlock",
                node_id="local",
                display_name="Sherlock",
                description="Research",
                intents=["research"],
            ),
        ]
        card = build_agent_card(
            caps,
            node_name="proteus",
            node_description="Test node",
            node_version="1.0.0",
            interface_url="http://127.0.0.1:8081",
            provider_name="Hermes",
        )
        d = agent_card_to_dict(card)
        assert d["name"] == "proteus"
        assert d["description"] == "Test node"
        assert d["version"] == "1.0.0"
        assert "capabilities" in d
        assert "skills" in d
        assert len(d["skills"]) == 1
        assert "supported_interfaces" in d
        assert d["supported_interfaces"][0]["url"] == "http://127.0.0.1:8081"

    def test_dict_reparses_to_proto(self):
        """The dict output can be parsed back into an AgentCard."""
        caps = [
            AgentCapability(
                profile_name="sherlock",
                node_id="local",
                display_name="Sherlock",
                description="Research",
                intents=["research"],
            ),
        ]
        card1 = build_agent_card(caps, node_name="proteus")
        d = agent_card_to_dict(card1)
        card2 = ParseDict(d, AgentCard())
        assert card2.name == "proteus"
        assert card2.skills[0].name == "Sherlock"
