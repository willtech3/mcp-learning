"""
Tests for modern/mrtr.py and modern/context.py — the MRTR engine and the
ModernContext that feeds it.

These cover the load-bearing invariants of MCP 2026-07-28's Multi
Round-Trip Requests (SEP-2322):

- the requestState codec: HMAC integrity (tampering MUST be rejected),
  expiry, and the anti-replay binding to method/name/arguments/principal;
- the re-execution model: deterministic per-request call keys (elicit:0,
  elicit:1, sample:0, ...) and response memoization carried INSIDE the
  signed state across retries;
- ModernContext's FastMCP-compatible surface: elicit/sample return the
  same result shapes handlers already consume, capability gates raise
  -32021 with data.requiredCapabilities, and per-request logging/progress
  gating (SEP-2575/2577) is strict.
"""

import time
from typing import Literal

import pytest

from modern.context import (
    AcceptedElicitation,
    CancelledElicitation,
    DeclinedElicitation,
    InputRequiredInterrupt,
    ModernContext,
)
from modern.errors import (
    InvalidParamsError,
    MissingClientCapabilityError,
)
from modern.meta import RequestMeta
from modern.mrtr import (
    RequestStateCodec,
    canonical_arguments_hash,
    run_with_mrtr,
)
from modern.types import (
    PROTOCOL_VERSION,
    ClientCapabilities,
    Implementation,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_meta(
    caps: dict | None = None,
    log_level: str | None = None,
    progress_token: str | int | None = None,
) -> RequestMeta:
    return RequestMeta(
        protocol_version=PROTOCOL_VERSION,
        client_info=Implementation(name="test-client", version="1.0"),
        client_capabilities=ClientCapabilities.model_validate(caps or {}),
        log_level=log_level,
        progress_token=progress_token,
        trace={},
    )


ELICIT_CAPS = {"elicitation": {"form": {}}}


@pytest.fixture
def codec() -> RequestStateCodec:
    return RequestStateCodec(b"test-secret")


class NotificationRecorder:
    def __init__(self):
        self.sent: list[dict] = []

    async def __call__(self, message: dict) -> None:
        self.sent.append(message)


# ---------------------------------------------------------------------------
# RequestStateCodec — integrity, expiry, format
# ---------------------------------------------------------------------------


def fresh_payload(**overrides) -> dict:
    payload = {
        "v": 1,
        "m": "tools/call",
        "n": "checkout_book",
        "a": canonical_arguments_hash({"x": 1}),
        "p": "anon",
        "exp": int(time.time()) + 900,
        "r": {"elicit:0": {"action": "accept", "content": {}}},
    }
    payload.update(overrides)
    return payload


class TestRequestStateCodec:
    def test_round_trip(self, codec):
        payload = fresh_payload()
        assert codec.decode(codec.encode(payload)) == payload

    def test_tampered_payload_rejected(self, codec):
        state = codec.encode(fresh_payload())
        head, _, tail = state.partition(".")
        # Flip a character inside the base64 payload: the MAC no longer
        # matches — the spec's MUST-reject case.
        flipped = ("A" if head[10] != "A" else "B") + head[11:]
        tampered = head[:10] + flipped + "." + tail
        with pytest.raises(InvalidParamsError, match="integrity"):
            codec.decode(tampered)

    def test_tampered_mac_rejected(self, codec):
        state = codec.encode(fresh_payload())
        head, _, tail = state.partition(".")
        flipped = ("A" if tail[0] != "A" else "B") + tail[1:]
        with pytest.raises(InvalidParamsError, match="integrity"):
            codec.decode(head + "." + flipped)

    def test_wrong_secret_rejected(self, codec):
        other = RequestStateCodec(b"a-different-secret")
        with pytest.raises(InvalidParamsError, match="integrity"):
            other.decode(codec.encode(fresh_payload()))

    def test_malformed_format_rejected(self, codec):
        with pytest.raises(InvalidParamsError, match="format"):
            codec.decode("no-dot-anywhere")

    def test_expired_state_rejected(self, codec):
        state = codec.encode(fresh_payload(exp=int(time.time()) - 5))
        with pytest.raises(InvalidParamsError, match="expired"):
            codec.decode(state)

    def test_missing_expiry_rejected(self, codec):
        payload = fresh_payload()
        del payload["exp"]
        with pytest.raises(InvalidParamsError, match="expiry"):
            codec.decode(codec.encode(payload))

    def test_error_code_is_32602(self, codec):
        with pytest.raises(InvalidParamsError) as exc_info:
            codec.decode("junk.junk")
        assert exc_info.value.code == -32602


def test_arguments_hash_is_key_order_independent():
    # Canonical JSON: two clients serializing the same arguments in
    # different key orders MUST verify against the same state.
    a = canonical_arguments_hash({"patron_id": "p1", "book_isbn": "b1"})
    b = canonical_arguments_hash({"book_isbn": "b1", "patron_id": "p1"})
    assert a == b
    assert a != canonical_arguments_hash({"patron_id": "p1", "book_isbn": "b2"})


# ---------------------------------------------------------------------------
# run_with_mrtr — the re-execution engine
# ---------------------------------------------------------------------------


def two_question_handler():
    """An execute() that needs two answers — and counts its re-executions."""
    runs = {"count": 0}

    async def execute(collected: dict) -> dict:
        runs["count"] += 1
        if "elicit:0" not in collected:
            raise InputRequiredInterrupt(
                "elicit:0", {"method": "elicitation/create", "params": {"message": "first?"}}
            )
        if "elicit:1" not in collected:
            raise InputRequiredInterrupt(
                "elicit:1", {"method": "elicitation/create", "params": {"message": "second?"}}
            )
        return {"answers": [collected["elicit:0"], collected["elicit:1"]]}

    return execute, runs


class TestRunWithMrtr:
    async def test_three_trips_for_two_questions(self, codec):
        """The canonical MRTR flow: run, retry, retry — memo grows each time."""
        execute, runs = two_question_handler()
        common = {
            "method": "tools/call",
            "name": "demo",
            "arguments": {"x": 1},
            "codec": codec,
        }

        # Trip 1: nothing collected -> asks the FIRST question.
        r1 = await run_with_mrtr(execute, params={}, **common)
        assert r1["resultType"] == "input_required"
        assert list(r1["inputRequests"]) == ["elicit:0"]
        assert isinstance(r1["requestState"], str)

        # Trip 2: first answer arrives -> asks the SECOND question; the
        # state now carries answer #1 (the server itself kept nothing).
        r2 = await run_with_mrtr(
            execute,
            params={
                "requestState": r1["requestState"],
                "inputResponses": {"elicit:0": {"action": "accept", "content": {"a": 1}}},
            },
            **common,
        )
        assert r2["resultType"] == "input_required"
        assert list(r2["inputRequests"]) == ["elicit:1"]

        # Trip 3: both answers -> complete, with BOTH answers visible even
        # though answer #1 was only ever sent on trip 2 (memoization).
        r3 = await run_with_mrtr(
            execute,
            params={
                "requestState": r2["requestState"],
                "inputResponses": {"elicit:1": {"action": "accept", "content": {"b": 2}}},
            },
            **common,
        )
        assert r3["resultType"] == "complete"
        assert r3["answers"] == [
            {"action": "accept", "content": {"a": 1}},
            {"action": "accept", "content": {"b": 2}},
        ]
        # Re-execution model: the handler ran from the top on every trip.
        assert runs["count"] == 3

    async def test_state_bound_to_name(self, codec):
        execute, _ = two_question_handler()
        r1 = await run_with_mrtr(
            execute,
            method="tools/call",
            name="demo",
            arguments={},
            params={},
            codec=codec,
        )
        with pytest.raises(InvalidParamsError, match="bound to a different request"):
            await run_with_mrtr(
                execute,
                method="tools/call",
                name="OTHER_TOOL",  # replay onto a different tool
                arguments={},
                params={"requestState": r1["requestState"]},
                codec=codec,
            )

    async def test_state_bound_to_arguments(self, codec):
        execute, _ = two_question_handler()
        r1 = await run_with_mrtr(
            execute,
            method="tools/call",
            name="demo",
            arguments={"isbn": "111"},
            params={},
            codec=codec,
        )
        with pytest.raises(InvalidParamsError, match="different arguments"):
            await run_with_mrtr(
                execute,
                method="tools/call",
                name="demo",
                arguments={"isbn": "222"},  # consent must not transfer
                params={"requestState": r1["requestState"]},
                codec=codec,
            )

    async def test_state_bound_to_principal(self, codec):
        execute, _ = two_question_handler()
        r1 = await run_with_mrtr(
            execute,
            method="tools/call",
            name="demo",
            arguments={},
            params={},
            codec=codec,
            principal_id="alice",
        )
        with pytest.raises(InvalidParamsError, match="different principal"):
            await run_with_mrtr(
                execute,
                method="tools/call",
                name="demo",
                arguments={},
                params={"requestState": r1["requestState"]},
                codec=codec,
                principal_id="bob",
            )

    async def test_complete_result_gets_result_type(self, codec):
        async def execute(_collected):
            return {"content": []}  # handler forgot resultType

        result = await run_with_mrtr(
            execute, method="tools/call", name="t", arguments={}, params={}, codec=codec
        )
        assert result["resultType"] == "complete"

    async def test_non_dict_input_responses_rejected(self, codec):
        execute, _ = two_question_handler()
        with pytest.raises(InvalidParamsError, match="inputResponses"):
            await run_with_mrtr(
                execute,
                method="tools/call",
                name="demo",
                arguments={},
                params={"inputResponses": ["not", "a", "map"]},
                codec=codec,
            )


# ---------------------------------------------------------------------------
# ModernContext.elicit — FastMCP-shaped results over MRTR
# ---------------------------------------------------------------------------


class TestContextElicit:
    async def test_missing_capability_raises_32021(self):
        ctx = ModernContext(meta=make_meta(caps={}))
        with pytest.raises(MissingClientCapabilityError) as exc_info:
            await ctx.elicit("Proceed?")
        assert exc_info.value.code == -32021
        assert exc_info.value.data == {"requiredCapabilities": {"elicitation": {}}}

    async def test_url_only_capability_is_not_form(self):
        # We only send form-mode requests; a url-only client cannot serve them.
        ctx = ModernContext(meta=make_meta(caps={"elicitation": {"url": {}}}))
        with pytest.raises(MissingClientCapabilityError):
            await ctx.elicit("Proceed?")

    async def test_empty_elicitation_object_means_form(self):
        # Backwards compat rule: {"elicitation": {}} == {"elicitation": {"form": {}}}.
        ctx = ModernContext(meta=make_meta(caps={"elicitation": {}}))
        with pytest.raises(InputRequiredInterrupt):
            await ctx.elicit("Proceed?")

    async def test_interrupt_carries_approval_schema(self):
        """response_type=None -> the same approval-only schema FastMCP sends."""
        ctx = ModernContext(meta=make_meta(caps=ELICIT_CAPS))
        with pytest.raises(InputRequiredInterrupt) as exc_info:
            await ctx.elicit("Waive the fine?")
        interrupt = exc_info.value
        assert interrupt.key == "elicit:0"
        assert interrupt.input_request["method"] == "elicitation/create"
        params = interrupt.input_request["params"]
        assert params["message"] == "Waive the fine?"
        assert params["requestedSchema"] == {"type": "object", "properties": {}}

    async def test_deterministic_keys_in_call_order(self):
        memo = {"elicit:0": {"action": "accept", "content": {}}}
        ctx = ModernContext(meta=make_meta(caps=ELICIT_CAPS), memo=memo)
        first = await ctx.elicit("first?")
        assert first.action == "accept"
        with pytest.raises(InputRequiredInterrupt) as exc_info:
            await ctx.elicit("second?")
        assert exc_info.value.key == "elicit:1"

    async def test_memoized_accept_approval_only(self):
        memo = {"elicit:0": {"action": "accept", "content": {}}}
        ctx = ModernContext(meta=make_meta(caps=ELICIT_CAPS), memo=memo)
        answer = await ctx.elicit("Proceed?")
        assert isinstance(answer, AcceptedElicitation)
        assert answer.action == "accept"
        assert answer.data == {}

    async def test_memoized_accept_enum_unwraps_scalar(self):
        """Literal response types round-trip through FastMCP's own adapter:
        the wire sends {"value": ...}, the handler sees the bare scalar."""
        memo = {"elicit:0": {"action": "accept", "content": {"value": "12 months"}}}
        ctx = ModernContext(meta=make_meta(caps=ELICIT_CAPS), memo=memo)
        answer = await ctx.elicit(
            "Which term?", response_type=Literal["6 months", "12 months", "24 months"]
        )
        assert answer.action == "accept"
        assert answer.data == "12 months"

    async def test_memoized_decline_and_cancel(self):
        for action, expected in (
            ("decline", DeclinedElicitation),
            ("cancel", CancelledElicitation),
        ):
            ctx = ModernContext(
                meta=make_meta(caps=ELICIT_CAPS), memo={"elicit:0": {"action": action}}
            )
            answer = await ctx.elicit("Proceed?")
            assert isinstance(answer, expected)
            assert answer.action == action

    async def test_invalid_accept_content_is_rerequested(self):
        """Spec SHOULD: missing/invalid requested info -> a NEW
        InputRequiredResult, not an error. The bad answer is dropped from
        the memo so the retry asks the same question again."""
        memo = {"elicit:0": {"action": "accept", "content": {"value": "NOT_AN_OPTION"}}}
        ctx = ModernContext(meta=make_meta(caps=ELICIT_CAPS), memo=memo)
        with pytest.raises(InputRequiredInterrupt) as exc_info:
            await ctx.elicit("Which term?", response_type=Literal["6 months", "12 months"])
        assert exc_info.value.key == "elicit:0"
        assert "elicit:0" not in memo  # dropped, so the state won't replay it

    async def test_malformed_elicit_result_is_protocol_error(self):
        memo = {"elicit:0": {"action": "maybe???"}}  # not a valid action
        ctx = ModernContext(meta=make_meta(caps=ELICIT_CAPS), memo=memo)
        with pytest.raises(InvalidParamsError):
            await ctx.elicit("Proceed?")

    async def test_interrupt_is_not_swallowed_by_except_exception(self):
        """The reason InputRequiredInterrupt derives from BaseException:
        handlers wrap ctx.elicit in `except Exception` for capability
        fallback (tools/circulation.py does), and the MRTR unwind must
        escape that."""
        ctx = ModernContext(meta=make_meta(caps=ELICIT_CAPS))

        async def handler_style_elicit() -> None:
            # Mirrors the fallback pattern in tools/circulation.py.
            try:
                await ctx.elicit("Proceed?")
            except Exception:
                pytest.fail("InputRequiredInterrupt was swallowed by 'except Exception'")

        with pytest.raises(InputRequiredInterrupt):
            await handler_style_elicit()


# ---------------------------------------------------------------------------
# ModernContext.sample — sampling over MRTR (deprecated but functional)
# ---------------------------------------------------------------------------

TEXT_ANSWER = {
    "role": "assistant",
    "content": {"type": "text", "text": "The capital of France is Paris."},
    "model": "claude-x",
    "stopReason": "endTurn",
}


class TestContextSample:
    async def test_missing_capability_raises_32021(self):
        ctx = ModernContext(meta=make_meta(caps={}))
        with pytest.raises(MissingClientCapabilityError) as exc_info:
            await ctx.sample("hello")
        assert exc_info.value.data == {"requiredCapabilities": {"sampling": {}}}

    async def test_tools_need_sampling_tools_capability(self):
        def a_tool(q: str) -> str:
            return q

        ctx = ModernContext(meta=make_meta(caps={"sampling": {}}))
        with pytest.raises(MissingClientCapabilityError) as exc_info:
            await ctx.sample("hello", tools=[a_tool])
        assert exc_info.value.data == {"requiredCapabilities": {"sampling": {"tools": {}}}}

    async def test_interrupt_carries_wire_request(self):
        ctx = ModernContext(meta=make_meta(caps={"sampling": {}}))
        with pytest.raises(InputRequiredInterrupt) as exc_info:
            await ctx.sample("What is 2+2?", system_prompt="Be brief.", max_tokens=50)
        interrupt = exc_info.value
        assert interrupt.key == "sample:0"
        assert interrupt.input_request["method"] == "sampling/createMessage"
        params = interrupt.input_request["params"]
        assert params["messages"] == [
            {"role": "user", "content": {"type": "text", "text": "What is 2+2?"}}
        ]
        assert params["maxTokens"] == 50  # wire-REQUIRED field
        assert params["systemPrompt"] == "Be brief."

    async def test_max_tokens_defaults_like_fastmcp(self):
        ctx = ModernContext(meta=make_meta(caps={"sampling": {}}))
        with pytest.raises(InputRequiredInterrupt) as exc_info:
            await ctx.sample("hi")
        assert exc_info.value.input_request["params"]["maxTokens"] == 512

    async def test_memoized_answer_returns_text(self):
        ctx = ModernContext(meta=make_meta(caps={"sampling": {}}), memo={"sample:0": TEXT_ANSWER})
        result = await ctx.sample("capital of France?")
        assert result.text == "The capital of France is Paris."
        assert result.result == result.text

    async def test_tool_loop_costs_one_key_per_turn(self):
        """SEP-1577 tool-enabled sampling under MRTR: turn 1 asks for a tool
        call (sample:0), the SERVER executes it, turn 2 returns the final
        text (sample:1). Each turn is one full retry of the original
        request in the real flow."""
        calls: list[dict] = []

        def search_catalog(genre: str) -> list[str]:
            calls.append({"genre": genre})
            return ["Book A", "Book B"]

        memo = {
            "sample:0": {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": "call-1",
                        "name": "search_catalog",
                        "input": {"genre": "Mystery"},
                    },
                ],
                "model": "claude-x",
                "stopReason": "toolUse",
            },
            "sample:1": TEXT_ANSWER,
        }
        caps = {"sampling": {"tools": {}}}
        ctx = ModernContext(meta=make_meta(caps=caps), memo=memo)
        result = await ctx.sample("recommend a mystery", tools=[search_catalog])
        assert calls == [{"genre": "Mystery"}]  # the server ran the tool
        assert result.text == "The capital of France is Paris."
        # The transcript grew: user prompt, assistant tool_use, user
        # tool_result, assistant final answer.
        roles = [m["role"] for m in result.history]
        assert roles == ["user", "assistant", "user", "assistant"]
        tool_result = result.history[2]["content"][0]
        assert tool_result["type"] == "tool_result"
        assert tool_result["toolUseId"] == "call-1"

    async def test_tool_loop_interrupt_for_next_turn(self):
        """With only turn 1 memoized, the loop must interrupt for sample:1,
        carrying the EXTENDED transcript (including the tool result)."""

        def echo(x: str) -> str:
            return x

        memo = {
            "sample:0": {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "c1", "name": "echo", "input": {"x": "hi"}}],
                "model": "m",
                "stopReason": "toolUse",
            },
        }
        ctx = ModernContext(meta=make_meta(caps={"sampling": {"tools": {}}}), memo=memo)
        with pytest.raises(InputRequiredInterrupt) as exc_info:
            await ctx.sample("go", tools=[echo])
        assert exc_info.value.key == "sample:1"
        messages = exc_info.value.input_request["params"]["messages"]
        assert len(messages) == 3  # user, assistant tool_use, user tool_result


# ---------------------------------------------------------------------------
# Progress + logging gating (per-request, SEP-2575/2577)
# ---------------------------------------------------------------------------


class TestProgressAndLogging:
    async def test_progress_without_token_is_noop(self):
        recorder = NotificationRecorder()
        ctx = ModernContext(meta=make_meta(), notify=recorder)
        await ctx.report_progress(50, total=100)
        assert recorder.sent == []

    async def test_progress_echoes_token(self):
        recorder = NotificationRecorder()
        ctx = ModernContext(meta=make_meta(progress_token="tok-9"), notify=recorder)
        await ctx.report_progress(50, total=100, message="halfway")
        assert recorder.sent == [
            {
                "jsonrpc": "2.0",
                "method": "notifications/progress",
                "params": {
                    "progressToken": "tok-9",
                    "progress": 50,
                    "total": 100,
                    "message": "halfway",
                },
            }
        ]

    async def test_no_log_level_means_no_messages(self):
        """The 2026-07-28 MUST: no logLevel in _meta -> no
        notifications/message for this request, period."""
        recorder = NotificationRecorder()
        ctx = ModernContext(meta=make_meta(), notify=recorder)
        await ctx.error("something terrible")
        assert recorder.sent == []

    async def test_level_filtering_uses_rfc5424_order(self):
        recorder = NotificationRecorder()
        ctx = ModernContext(meta=make_meta(log_level="warning"), notify=recorder)
        await ctx.info("too quiet")  # info < warning: dropped
        await ctx.error("loud enough")  # error >= warning: sent
        assert len(recorder.sent) == 1
        assert recorder.sent[0]["method"] == "notifications/message"
        assert recorder.sent[0]["params"]["level"] == "error"
        assert recorder.sent[0]["params"]["data"] == "loud enough"
