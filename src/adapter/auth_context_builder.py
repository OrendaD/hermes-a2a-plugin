"""Bearer-token based authentication context builder for A2A JSON-RPC.

Extracts ``Authorization: Bearer <token>`` from incoming Starlette requests,
validates the token against a ``PeerRegistry``, and builds a
``ServerCallContext`` with either an authenticated ``User`` (when the token
matches a known peer) or an ``UnauthenticatedUser`` (otherwise).

Auth enforcement is deliberately deferred — this builder only populates the
context; downstream middleware/handlers can check ``context.user.is_authenticated``
to enforce access control.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from a2a.auth.user import UnauthenticatedUser, User
from a2a.server.context import ServerCallContext
from a2a.server.routes.common import ServerCallContextBuilder

from adapter.peer_registry import PeerRegistry

if TYPE_CHECKING:
    from starlette.requests import Request


class _AuthenticatedUser(User):
    """Minimal User implementation for an authenticated peer."""

    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def is_authenticated(self) -> bool:
        return True

    @property
    def user_name(self) -> str:
        return self._name


class BearerTokenContextBuilder(ServerCallContextBuilder):
    """Builds a ServerCallContext from the incoming request's bearer token.

    Reads the ``Authorization`` header, strips the ``Bearer `` prefix,
    and validates the token against the provided ``PeerRegistry``.

    If the token is valid the context carries an authenticated ``User``
    whose ``user_name`` is the peer name. Otherwise the context carries
    ``UnauthenticatedUser()``.
    """

    def __init__(self, peer_registry: PeerRegistry) -> None:
        self._registry = peer_registry

    def build(self, request: Request) -> ServerCallContext:
        auth = request.headers.get("Authorization", "")
        token = auth.removeprefix("Bearer ").strip()

        if token:
            peer = self._registry.validate_bearer_token(token)
            if peer is not None:
                return ServerCallContext(
                    user=_AuthenticatedUser(peer.name),
                    state={
                        "peer_name": peer.name,
                        "headers": dict(request.headers),
                    },
                )

        return ServerCallContext(
            user=UnauthenticatedUser(),
            state={"headers": dict(request.headers)},
        )
