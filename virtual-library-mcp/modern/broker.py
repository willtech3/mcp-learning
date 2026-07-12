"""
Subscription fan-out for MCP 2026-07-28 ``subscriptions/listen`` (SEP-2575).

The 2026-07-28 revision removed every long-lived, connection-scoped channel
the protocol used to have: the Streamable HTTP GET stream, protocol-level
sessions (SEP-2567), and the ``resources/subscribe``/``resources/unsubscribe``
RPCs are all gone.  Their single replacement is ``subscriptions/listen`` — an
ordinary JSON-RPC request whose RESPONSE is deferred until the subscription
ends.  All subscription state is scoped to that one request, which is what
keeps the protocol stateless: tear the request down and nothing lingers.

This module is the server-side heart of that pattern.  A
:class:`SubscriptionBroker` tracks every active listen request and fans
change events out to them, enforcing the three wire rules the spec is
strictest about:

1. **Acknowledgment first.**  ``notifications/subscriptions/acknowledged``
   MUST be the first message on every stream.  Its ``params.notifications``
   echoes the subset of the requested :class:`~modern.types.SubscriptionFilter`
   the server agreed to honor — omission of a requested type is how a server
   politely refuses it (clients are told to diff request vs ack).

2. **Strict opt-in.**  The server MUST NOT deliver notification types the
   client did not request.  In 2025-11-25 a server could push
   ``notifications/*/list_changed`` at will on any stream; now every type is
   gated on the filter.  ``resourceSubscriptions`` (the replacement for
   ``resources/subscribe``) is a list of exact resource URIs; this broker
   matches published URIs against it exactly.  The spec permits a server to
   deliver updates for *sub-resources* of a subscribed URI ("might be a
   sub-resource of the one that the client actually subscribed to") — we do
   not exercise that latitude, and document it here instead.

3. **subscriptionId tagging.**  EVERY notification delivered via a listen
   stream — including the acknowledgment — MUST carry
   ``_meta["io.modelcontextprotocol/subscriptionId"]`` set to the JSON-RPC id
   of the originating listen request.  On Streamable HTTP each stream is its
   own response body so the tag is technically redundant; on stdio (one
   shared channel, possibly several concurrent subscriptions) it is the ONLY
   way a client can demultiplex.  The tag is applied here, at the moment a
   notification is enqueued, so no transport can forget it.

Ending a subscription ("Graceful Closure"): when the SERVER tears a stream
down (shutdown), it SHOULD answer the original listen request with an empty
result whose ``_meta`` — required by the schema even though it duplicates the
response ``id`` — carries the subscriptionId, then close the stream.
:meth:`SubscriptionBroker.close_all` implements exactly that by placing the
graceful-close RESPONSE into each subscription's queue: consumers recognize
"a queue item without a ``method`` key" as end-of-stream, emit it, and stop.
When the CLIENT ends the subscription (closing the SSE response stream on
HTTP, ``notifications/cancelled`` on stdio) the server sends nothing further
— the transport just calls :attr:`ListenOutcome.close` to unregister.

Everything this broker hands to transports is a complete JSON-RPC wire
message (dict), so the HTTP and stdio drivers can serialize queue items
verbatim without knowing what they mean.

Spec references: MCP 2026-07-28, basic/patterns/subscriptions (SEP-2575);
basic/patterns/cancellation (server-sent ``notifications/cancelled`` is
scoped to stdio listen teardown); basic/transports/streamable-http §receiving
messages.
"""

import asyncio
import itertools
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Literal

from modern.types import (
    JSONRPC_VERSION,
    META_SUBSCRIPTION_ID,
    RESULT_COMPLETE,
    SubscriptionFilter,
)


@dataclass
class ListenOutcome:
    """Everything a transport needs to serve one ``subscriptions/listen``.

    This mirrors the ``ListenOutcome`` contract in the design's dispatcher
    section; it is defined here (the broker is what actually builds it) so
    the dispatcher can simply re-export or pass it through.  Transports
    consume it structurally — only the three attributes below matter:

    - ``ack``: the ``notifications/subscriptions/acknowledged`` message,
      already subscriptionId-tagged.  MUST be sent first.
    - ``queue``: subsequent complete JSON-RPC messages.  Items carrying a
      ``method`` key are notifications to forward; an item WITHOUT a
      ``method`` key is the graceful-close JSON-RPC *response* (enqueued by
      :meth:`SubscriptionBroker.close_all`) — send it, then end the stream.
    - ``close``: unregister the subscription and get the graceful-close
      response.  Idempotent, and deliberately **await-free** inside, so a
      transport can call it during cancellation/disconnect cleanup without
      risking a second ``CancelledError`` at an await point.  On client
      disconnect the transport calls it and DISCARDS the result (the spec
      forbids sending anything further for a cancelled request); on stdio
      teardown the driver emits ``notifications/cancelled`` and then this
      response.
    """

    ack: dict[str, Any]
    queue: asyncio.Queue[dict[str, Any]]
    close: Callable[[], Awaitable[dict[str, Any]]]


@dataclass
class _Subscription:
    """Broker-internal record of one active listen stream."""

    request_id: str | int
    #: Honored boolean opt-ins.  Falsy filter values (absent, ``false``) mean
    #: "not subscribed" — the spec treats omission as non-subscription and we
    #: fold an explicit ``false`` into the same bucket.
    tools: bool
    prompts: bool
    resources: bool
    #: Exact resource URIs opted into via ``resourceSubscriptions``.
    resource_uris: frozenset[str]
    queue: asyncio.Queue[dict[str, Any]] = field(default_factory=asyncio.Queue)


class SubscriptionBroker:
    """Fan-out hub connecting server-side change events to listen streams.

    Single-event-loop object: registration happens in async request handlers
    and publishes come from synchronous callbacks (e.g. the registry's
    ``on_list_changed`` hook), all on the same loop, so no locking is needed
    — ``asyncio.Queue.put_nowait`` never blocks on an unbounded queue.
    """

    def __init__(self) -> None:
        super().__init__()
        self._subscriptions: dict[int, _Subscription] = {}
        # Internal registration tokens: the JSON-RPC request id is NOT a
        # safe key (ids are only unique per client, and two clients may both
        # open a listen with id 1).
        self._tokens = itertools.count(1)

    @property
    def active_subscription_count(self) -> int:
        """Number of currently registered listen streams (introspection)."""
        return len(self._subscriptions)

    async def listen(
        self,
        request_id: str | int,
        subscription_filter: SubscriptionFilter | dict[str, Any],
    ) -> ListenOutcome:
        """Register a ``subscriptions/listen`` request and build its outcome.

        ``request_id`` is the listen request's JSON-RPC id — it becomes the
        ``io.modelcontextprotocol/subscriptionId`` tag on every message this
        subscription ever delivers (spec MUST, including the ack).

        This broker supports all four filter types, so the acknowledged
        subset equals whatever the client actually opted into; a broker that
        could not honor a type would omit it here, and that omission IS the
        refusal signal (there is no error for "unsupported filter type").
        """
        if isinstance(subscription_filter, dict):
            subscription_filter = SubscriptionFilter.model_validate(subscription_filter)

        subscription = _Subscription(
            request_id=request_id,
            tools=bool(subscription_filter.tools_list_changed),
            prompts=bool(subscription_filter.prompts_list_changed),
            resources=bool(subscription_filter.resources_list_changed),
            resource_uris=frozenset(subscription_filter.resource_subscriptions or ()),
        )
        token = next(self._tokens)
        self._subscriptions[token] = subscription

        # The honored filter: only truthy opt-ins appear.  An empty object is
        # legal — the stream stays open but will only ever see keepalives and
        # the graceful close.
        honored: dict[str, Any] = {}
        if subscription.tools:
            honored["toolsListChanged"] = True
        if subscription.prompts:
            honored["promptsListChanged"] = True
        if subscription.resources:
            honored["resourcesListChanged"] = True
        if subscription.resource_uris:
            honored["resourceSubscriptions"] = sorted(subscription.resource_uris)

        ack: dict[str, Any] = {
            "jsonrpc": JSONRPC_VERSION,
            "method": "notifications/subscriptions/acknowledged",
            "params": {
                "_meta": {META_SUBSCRIPTION_ID: request_id},
                "notifications": honored,
            },
        }

        async def close() -> dict[str, Any]:
            # Await-free by contract (see ListenOutcome docstring): the pop
            # must survive being called from cancellation cleanup, where any
            # suspension point would re-raise CancelledError.
            self._subscriptions.pop(token, None)
            return self._graceful_response(request_id)

        return ListenOutcome(ack=ack, queue=subscription.queue, close=close)

    def publish_list_changed(self, kind: Literal["tools", "prompts", "resources"]) -> None:
        """Deliver ``notifications/{kind}/list_changed`` to opted-in streams.

        Strict opt-in (spec MUST NOT send unrequested types): a subscriber
        who asked only for ``toolsListChanged`` never sees prompt or resource
        list changes, no matter how often they fire.
        """
        method = f"notifications/{kind}/list_changed"
        for subscription in list(self._subscriptions.values()):
            # The _Subscription field names deliberately match the ``kind``
            # values so the opt-in check is a single attribute lookup.
            if getattr(subscription, kind):
                subscription.queue.put_nowait(self._notification(method, subscription.request_id))

    def publish_resource_updated(self, uri: str) -> None:
        """Deliver ``notifications/resources/updated`` for one resource URI.

        Matching is EXACT against each subscriber's ``resourceSubscriptions``
        list.  The spec allows a server to also notify for sub-resources of a
        subscribed URI (the notification's ``uri`` "might be a sub-resource
        of the one that the client actually subscribed to"); this broker
        keeps the simpler exact-match semantics — publishers who want
        sub-resource behavior can publish the parent URI explicitly.
        """
        for subscription in list(self._subscriptions.values()):
            if uri in subscription.resource_uris:
                notification = self._notification(
                    "notifications/resources/updated",
                    subscription.request_id,
                    extra={"uri": uri},
                )
                subscription.queue.put_nowait(notification)

    async def close_all(self) -> None:
        """Gracefully close every stream (server shutdown).

        Per the subscriptions page the server SHOULD answer each listen
        request with an empty result before closing the stream — that
        response (a queue item with no ``method`` key) is the end-of-stream
        signal transports watch for.  Subscriptions are unregistered
        immediately, so publishes racing with shutdown are dropped rather
        than delivered after the graceful close.

        On stdio the driver additionally sends ``notifications/cancelled``
        referencing the listen request id before this response (the
        cancellation page's MUST for server-side teardown, which the schema
        scopes to stdio); on HTTP the response itself terminates the SSE
        stream and no cancelled notification exists.
        """
        for token, subscription in list(self._subscriptions.items()):
            self._subscriptions.pop(token, None)
            subscription.queue.put_nowait(self._graceful_response(subscription.request_id))

    @staticmethod
    def _notification(
        method: str,
        request_id: str | int,
        extra: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Build a complete, subscriptionId-tagged JSON-RPC notification."""
        params: dict[str, Any] = dict(extra or {})
        params["_meta"] = {META_SUBSCRIPTION_ID: request_id}
        return {"jsonrpc": JSONRPC_VERSION, "method": method, "params": params}

    @staticmethod
    def _graceful_response(request_id: str | int) -> dict[str, Any]:
        """The graceful-close JSON-RPC response (``SubscriptionsListenResult``).

        The schema REQUIRES ``_meta`` with the subscriptionId here even
        though it trivially equals the response's own ``id`` — a quirk worth
        modeling faithfully, since client validators enforce it.
        """
        return {
            "jsonrpc": JSONRPC_VERSION,
            "id": request_id,
            "result": {
                "resultType": RESULT_COMPLETE,
                "_meta": {META_SUBSCRIPTION_ID: request_id},
            },
        }
