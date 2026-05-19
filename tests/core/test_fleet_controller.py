"""Fleet Controller tests — routing, discovery, availability, node preference."""

from __future__ import annotations

from core.domain.models.intent import TaskIntent
from core.domain.models.capability import AgentCapability


class TestFCRegistration:
    def test_register_profile(self, populated_fc):
        """A registered profile appears in discover()."""
        results = populated_fc.discover("diagnose")
        assert len(results) == 1
        assert results[0].profile_name == "ray"

    def test_register_duplicate_overwrites(self, populated_fc, ray_cap):
        """Re-registering the same profile updates its capability."""
        updated = AgentCapability(
            profile_name="ray",
            node_id="local",
            display_name="Ray v2",
            description="Updated diagnostics",
            intents=["diagnose", "consultation", "forensics"],
        )
        populated_fc.register_profile(updated)
        results = populated_fc.discover("forensics")
        assert len(results) == 1
        assert results[0].display_name == "Ray v2"


class TestFCRoutingExplicit:
    def test_route_to_specific_profile(self, populated_fc):
        """Routing with target_profile dispatches to that profile."""
        intent = TaskIntent(
            intent_type="diagnose",
            payload={"symptoms": "502 error"},
            target_profile="ray",
        )
        dispatch = populated_fc.route(intent)
        assert dispatch.status == "dispatched"
        assert dispatch.profile_name == "ray"

    def test_route_to_unknown_profile(self, populated_fc):
        """Routing to a non-existent profile returns unavailable."""
        intent = TaskIntent(
            intent_type="diagnose",
            payload={},
            target_profile="nonexistent",
        )
        dispatch = populated_fc.route(intent)
        assert dispatch.status == "unavailable"
        assert "not found" in dispatch.message.lower()

    def test_route_profile_wrong_intent(self, populated_fc):
        """Routing a profile that can't handle the intent returns unavailable."""
        intent = TaskIntent(
            intent_type="deploy",  # Ray doesn't do deploy
            payload={},
            target_profile="ray",
        )
        dispatch = populated_fc.route(intent)
        assert dispatch.status == "unavailable"
        assert "cannot handle" in dispatch.message.lower()

    def test_route_profile_wrong_node(self, populated_fc):
        """Routing to a profile on the wrong node returns unavailable."""
        intent = TaskIntent(
            intent_type="diagnose",
            payload={},
            target_profile="odin",  # Odin is on remote node
            target_node="local",  # But we're asking for local
        )
        dispatch = populated_fc.route(intent)
        assert dispatch.status == "unavailable"
        assert "not" in dispatch.message and "100.96.0.1" in dispatch.message


class TestFCRoutingBestMatch:
    def test_route_best_match_across_all_nodes(self, populated_fc):
        """Without target, FC finds the best match across all profiles."""
        intent = TaskIntent(
            intent_type="diagnose",
            payload={"symptoms": "502"},
        )
        dispatch = populated_fc.route(intent)
        assert dispatch.status == "dispatched"
        assert dispatch.profile_name == "ray"

    def test_route_prefers_local_over_remote(self, populated_fc):
        """When a local and remote profile both match, FC picks local."""
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "test"},
        )
        dispatch = populated_fc.route(intent)
        # Both ray (local) and odin (remote) can handle consultation
        assert dispatch.status == "dispatched"
        assert dispatch.profile_name == "ray"  # local preferred

    def test_route_to_remote_when_no_local_match(self, populated_fc):
        """When only remote profiles match, FC routes to remote."""
        intent = TaskIntent(
            intent_type="research",
            payload={"topic": "Arch Linux"},
        )
        dispatch = populated_fc.route(intent)
        assert dispatch.status == "dispatched"
        assert dispatch.profile_name == "odin"  # only odin does research

    def test_route_to_specific_node(self, populated_fc):
        """FC targets a specific node when target_node is set."""
        intent = TaskIntent(
            intent_type="consultation",
            payload={"question": "test"},
            target_node="100.96.0.1",  # odin's node
        )
        dispatch = populated_fc.route(intent)
        assert dispatch.status == "dispatched"
        assert dispatch.profile_name == "odin"

    def test_route_no_match(self, populated_fc):
        """When no profile can handle the intent, returns unavailable."""
        intent = TaskIntent(
            intent_type="sing",
            payload={"song": "never gonna give you up"},
        )
        dispatch = populated_fc.route(intent)
        assert dispatch.status == "unavailable"
        assert "no profile" in dispatch.message.lower()


class TestFCAvailability:
    def test_profile_busy_returns_no_capacity(self, populated_fc):
        """A busy profile returns no_capacity."""
        # Dispatch first task to ray
        intent = TaskIntent(
            intent_type="diagnose",
            payload={},
            target_profile="ray",
        )
        first = populated_fc.route(intent)
        assert first.status == "dispatched"

        # Try dispatching another to ray while busy
        second = populated_fc.route(intent)
        assert second.status == "no_capacity"
        assert "busy" in second.message.lower()

    def test_release_frees_profile(self, populated_fc):
        """After release, a profile can accept new tasks."""
        intent = TaskIntent(
            intent_type="diagnose",
            payload={},
            target_profile="ray",
        )
        first = populated_fc.route(intent)
        assert first.status == "dispatched"

        # Release
        populated_fc.release(first.task_id, "ray")

        # Try again — should succeed
        second = populated_fc.route(intent)
        assert second.status == "dispatched"

    def test_availability_per_profile(self, populated_fc):
        """Each profile has independent availability."""
        # Busy ray
        populated_fc.route(TaskIntent(
            intent_type="diagnose", payload={}, target_profile="ray"
        ))
        # ops should still be available
        dispatch = populated_fc.route(TaskIntent(
            intent_type="deploy", payload={}, target_profile="ops"
        ))
        assert dispatch.status == "dispatched"
        assert dispatch.profile_name == "ops"


class TestFCDiscover:
    def test_discover_by_intent(self, populated_fc):
        """Discover finds profiles matching an intent type."""
        results = populated_fc.discover("review")
        assert len(results) == 1
        assert results[0].profile_name == "reviewer"

    def test_discover_by_tags(self, populated_fc):
        """Discover can narrow by tags (tag fallback when intent doesn't match directly)."""
        # Use an intent_type no profile handles directly so only tag matching applies
        results = populated_fc.discover("unknown_intent", tags=["linux"])
        assert len(results) == 2  # ray and odin both have "linux" tag
        profile_names = {r.profile_name for r in results}
        assert "ray" in profile_names
        assert "odin" in profile_names

    def test_discover_returns_all_matching(self, populated_fc):
        """Discover can return multiple profiles."""
        results = populated_fc.discover("consultation")
        assert len(results) == 2  # ray + odin
