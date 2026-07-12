"""
Tests for modern/types.py, modern/errors.py, and modern/meta.py.

These exercise the MCP 2026-07-28 wire contracts:

- strict per-request ``_meta`` validation (SEP-2575): the required trio of
  protocolVersion/clientInfo/clientCapabilities, plus the exact error codes
  the spec mandates for each failure mode (-32602 vs -32022);
- the Base64 sentinel header codec (SEP-2243 value encoding), including the
  spec's own worked examples and the anti-ambiguity rule;
- the error hierarchy's JSON-RPC code -> HTTP status mapping;
- serialization invariants: required resultType (SEP-2322) and required
  ttlMs/cacheScope on cacheable results (SEP-2549), camelCase aliases,
  tolerance for unknown capability fields.
"""

import pytest

from modern.errors import (
    HeaderMismatchError,
    InternalError,
    InvalidParamsError,
    InvalidRequestError,
    McpError,
    MethodNotFoundError,
    MissingClientCapabilityError,
    ParseError,
    UnsupportedProtocolVersionError,
)
from modern.meta import (
    RequestMeta,
    decode_header_value,
    encode_header_value,
    parse_request_meta,
)
from modern.types import (
    META_CLIENT_CAPS,
    META_CLIENT_INFO,
    META_LOG_LEVEL,
    META_PROGRESS_TOKEN,
    META_PROTOCOL_VERSION,
    PROTOCOL_VERSION,
    SUPPORTED_VERSIONS,
    CallToolResult,
    ClientCapabilities,
    DiscoverResult,
    ElicitRequest,
    ElicitRequestURLParams,
    Implementation,
    InputRequiredResult,
    ListToolsResult,
    ServerCapabilities,
    SubscriptionFilter,
    TextContent,
    Tool,
    complete_result,
    error_response,
)


def make_meta(**overrides) -> dict:
    """A minimal valid _meta object, with per-test overrides."""
    meta = {
        META_PROTOCOL_VERSION: PROTOCOL_VERSION,
        META_CLIENT_INFO: {"name": "TestClient", "version": "1.0.0"},
        META_CLIENT_CAPS: {},
    }
    meta.update(overrides)
    return meta


# ---------------------------------------------------------------------------
# parse_request_meta — happy paths
# ---------------------------------------------------------------------------


class TestParseRequestMetaHappyPath:
    def test_minimal_valid_meta(self):
        meta = parse_request_meta({"_meta": make_meta()})

        assert isinstance(meta, RequestMeta)
        assert meta.protocol_version == PROTOCOL_VERSION
        assert meta.client_info.name == "TestClient"
        assert meta.client_info.version == "1.0.0"
        assert isinstance(meta.client_capabilities, ClientCapabilities)
        # Optional fields default to their opted-out states.
        assert meta.log_level is None
        assert meta.progress_token is None
        assert meta.trace == {}

    def test_full_meta_with_all_optionals(self):
        traceparent = "00-0af7651916cd43dd8448eb211c80319c-00f067aa0ba902b7-01"
        meta = parse_request_meta(
            {
                "name": "some_tool",
                "_meta": make_meta(
                    **{
                        META_LOG_LEVEL: "warning",
                        META_PROGRESS_TOKEN: "tok-123",
                        "traceparent": traceparent,
                        "tracestate": "vendor=value",
                        "baggage": "userId=alice",
                    }
                ),
            }
        )

        assert meta.log_level == "warning"
        assert meta.progress_token == "tok-123"
        assert meta.trace == {
            "traceparent": traceparent,
            "tracestate": "vendor=value",
            "baggage": "userId=alice",
        }

    def test_integer_progress_token(self):
        meta = parse_request_meta({"_meta": make_meta(**{META_PROGRESS_TOKEN: 42})})
        assert meta.progress_token == 42

    def test_capabilities_parsed_into_model(self):
        meta = parse_request_meta(
            {
                "_meta": make_meta(
                    **{
                        META_CLIENT_CAPS: {
                            "elicitation": {"form": {}, "url": {}},
                            "sampling": {"tools": {}},
                            "extensions": {"io.modelcontextprotocol/tasks": {}},
                        }
                    }
                )
            }
        )

        caps = meta.client_capabilities
        assert caps.elicitation is not None
        assert caps.elicitation.form == {}
        assert caps.elicitation.url == {}
        assert caps.sampling is not None
        assert caps.sampling.tools == {}
        assert caps.extensions == {"io.modelcontextprotocol/tasks": {}}

    def test_client_info_extra_fields_tolerated(self):
        meta = parse_request_meta(
            {
                "_meta": make_meta(
                    **{
                        META_CLIENT_INFO: {
                            "name": "TestClient",
                            "version": "1.0.0",
                            "title": "Test Client",
                            "someFutureField": "kept",
                        }
                    }
                )
            }
        )
        assert meta.client_info.title == "Test Client"


# ---------------------------------------------------------------------------
# parse_request_meta — sad paths (-32602 Invalid params, HTTP 400)
# ---------------------------------------------------------------------------


class TestParseRequestMetaSadPath:
    def test_params_none_rejected(self):
        with pytest.raises(InvalidParamsError) as exc_info:
            parse_request_meta(None)
        assert exc_info.value.code == -32602
        assert exc_info.value.http_status == 400

    def test_params_missing_meta_rejected(self):
        with pytest.raises(InvalidParamsError) as exc_info:
            parse_request_meta({"name": "some_tool"})
        assert exc_info.value.code == -32602
        assert "_meta" in exc_info.value.message

    def test_meta_wrong_type_rejected(self):
        with pytest.raises(InvalidParamsError):
            parse_request_meta({"_meta": "not-an-object"})

    @pytest.mark.parametrize(
        "missing_key",
        [META_PROTOCOL_VERSION, META_CLIENT_INFO, META_CLIENT_CAPS],
    )
    def test_each_required_key_missing_rejected(self, missing_key):
        meta = make_meta()
        del meta[missing_key]

        with pytest.raises(InvalidParamsError) as exc_info:
            parse_request_meta({"_meta": meta})

        assert exc_info.value.code == -32602
        assert exc_info.value.http_status == 400
        # The error names the missing key so clients can fix their request.
        assert missing_key in exc_info.value.message

    def test_client_info_missing_version_rejected(self):
        with pytest.raises(InvalidParamsError):
            parse_request_meta({"_meta": make_meta(**{META_CLIENT_INFO: {"name": "NoVersion"}})})

    def test_client_info_not_an_object_rejected(self):
        with pytest.raises(InvalidParamsError):
            parse_request_meta({"_meta": make_meta(**{META_CLIENT_INFO: "TestClient/1.0"})})

    def test_client_capabilities_not_an_object_rejected(self):
        with pytest.raises(InvalidParamsError):
            parse_request_meta({"_meta": make_meta(**{META_CLIENT_CAPS: ["elicitation"]})})

    def test_invalid_log_level_rejected(self):
        # The spec routes "invalid log level" to -32602.
        with pytest.raises(InvalidParamsError):
            parse_request_meta({"_meta": make_meta(**{META_LOG_LEVEL: "verbose"})})

    @pytest.mark.parametrize("bad_token", [True, [1, 2], {"t": 1}, 1.5])
    def test_invalid_progress_token_rejected(self, bad_token):
        with pytest.raises(InvalidParamsError):
            parse_request_meta({"_meta": make_meta(**{META_PROGRESS_TOKEN: bad_token})})

    def test_non_string_trace_values_dropped_not_fatal(self):
        # Trace keys are opaque passthrough; a bogus non-string value is
        # simply not propagated rather than failing the whole request.
        meta = parse_request_meta({"_meta": make_meta(traceparent=12345)})
        assert meta.trace == {}


# ---------------------------------------------------------------------------
# parse_request_meta — version rejection (-32022, HTTP 400)
# ---------------------------------------------------------------------------


class TestVersionRejection:
    @pytest.mark.parametrize("requested", ["2025-11-25", "2024-11-05", "1900-01-01"])
    def test_non_modern_version_rejected_with_exact_data_shape(self, requested):
        with pytest.raises(UnsupportedProtocolVersionError) as exc_info:
            parse_request_meta({"_meta": make_meta(**{META_PROTOCOL_VERSION: requested})})

        err = exc_info.value
        assert err.code == -32022
        assert err.http_status == 400
        # data MUST carry both keys with these exact names (schema
        # UnsupportedProtocolVersionError).
        assert err.data == {
            "supported": list(SUPPORTED_VERSIONS),
            "requested": requested,
        }

    def test_supported_list_advertises_dual_era_versions(self):
        # The modern dispatcher rejects legacy versions, but the ERROR still
        # advertises them: the dual-era server serves 2025-11-25 via its
        # legacy (FastMCP) path, and clients pick from data.supported.
        with pytest.raises(UnsupportedProtocolVersionError) as exc_info:
            parse_request_meta({"_meta": make_meta(**{META_PROTOCOL_VERSION: "1900-01-01"})})
        supported = exc_info.value.data["supported"]
        assert PROTOCOL_VERSION in supported
        assert "2025-11-25" in supported

    def test_non_string_version_is_invalid_params_not_version_error(self):
        with pytest.raises(InvalidParamsError):
            parse_request_meta({"_meta": make_meta(**{META_PROTOCOL_VERSION: 20260728})})

    def test_error_response_serialization(self):
        with pytest.raises(UnsupportedProtocolVersionError) as exc_info:
            parse_request_meta({"_meta": make_meta(**{META_PROTOCOL_VERSION: "1900-01-01"})})

        response = exc_info.value.to_error_response(1)
        assert response["jsonrpc"] == "2.0"
        assert response["id"] == 1
        assert response["error"]["code"] == -32022
        assert response["error"]["data"]["requested"] == "1900-01-01"


# ---------------------------------------------------------------------------
# Base64 sentinel codec (SEP-2243 value encoding)
# ---------------------------------------------------------------------------


class TestSentinelCodec:
    def test_plain_ascii_passthrough(self):
        assert encode_header_value("get_weather") == "get_weather"
        assert decode_header_value("get_weather") == "get_weather"

    def test_ascii_with_interior_space_passthrough(self):
        # Space and HTAB are legal INSIDE an RFC 9110 field value.
        assert encode_header_value("Seattle, WA") == "Seattle, WA"

    def test_uri_passthrough(self):
        uri = "file:///projects/myapp/config.json"
        assert encode_header_value(uri) == uri

    def test_non_ascii_encoded_spec_example(self):
        # Worked example straight from the spec.
        assert encode_header_value("Hello, 世界") == "=?base64?SGVsbG8sIOS4lueVjA==?="
        assert decode_header_value("=?base64?SGVsbG8sIOS4lueVjA==?=") == "Hello, 世界"

    def test_leading_trailing_whitespace_encoded_spec_example(self):
        # HTTP strips OWS around field values, so padding must be encoded.
        assert encode_header_value(" padded ") == "=?base64?IHBhZGRlZCA=?="
        assert decode_header_value("=?base64?IHBhZGRlZCA=?=") == " padded "

    def test_newline_encoded_spec_example(self):
        # Control characters (CR/LF especially — header injection!) must
        # never appear raw in a field value.
        assert encode_header_value("line1\nline2") == "=?base64?bGluZTEKbGluZTI=?="
        assert decode_header_value("=?base64?bGluZTEKbGluZTI=?=") == "line1\nline2"

    def test_literal_sentinel_reencoded_spec_example(self):
        # Anti-ambiguity rule: a literal value shaped like a sentinel MUST be
        # encoded even though it is plain ASCII.
        literal = "=?base64?literal?="
        encoded = encode_header_value(literal)
        assert encoded == "=?base64?PT9iYXNlNjQ/bGl0ZXJhbD89?="
        assert decode_header_value(encoded) == literal

    def test_sentinel_markers_are_case_sensitive(self):
        # Uppercase markers are NOT the sentinel — the value is literal.
        literal = "=?BASE64?SGVsbG8=?="
        assert decode_header_value(literal) == literal
        # And since it is header-safe and does not match the (lowercase)
        # sentinel pattern, encode passes it through too.
        assert encode_header_value(literal) == literal

    def test_empty_string_passthrough(self):
        assert encode_header_value("") == ""
        assert decode_header_value("") == ""

    @pytest.mark.parametrize(
        "value",
        [
            "get_weather",
            "Hello, 世界",
            " padded ",
            "line1\nline2",
            "=?base64?literal?=",
            "=?base64?=",  # minimal overlapping sentinel-shaped literal
            "\ttab-lead",
            "trailing-tab\t",
            "naïve café ☕",
            "library://books/978-0-134-68547-9",
            "?=",
            "=?base64?",
        ],
    )
    def test_round_trip(self, value):
        assert decode_header_value(encode_header_value(value)) == value

    def test_decode_invalid_base64_raises_header_mismatch(self):
        with pytest.raises(HeaderMismatchError) as exc_info:
            decode_header_value("=?base64?not!!valid!!base64?=")
        assert exc_info.value.code == -32020
        assert exc_info.value.http_status == 400

    def test_decode_invalid_utf8_raises_header_mismatch(self):
        # base64 of bytes ff fe — valid base64, invalid UTF-8.
        with pytest.raises(HeaderMismatchError):
            decode_header_value("=?base64?//4=?=")

    def test_decode_non_ascii_payload_raises_header_mismatch(self):
        with pytest.raises(HeaderMismatchError):
            decode_header_value("=?base64?SGVsbG8世?=")


# ---------------------------------------------------------------------------
# Error hierarchy: code / http_status mapping
# ---------------------------------------------------------------------------


class TestErrorHttpStatusMapping:
    @pytest.mark.parametrize(
        ("error", "code", "http_status"),
        [
            (ParseError(), -32700, 400),
            (InvalidRequestError(), -32600, 400),
            (MethodNotFoundError(), -32601, 404),
            (InvalidParamsError("bad params"), -32602, 400),
            (InternalError(), -32603, 500),
            (HeaderMismatchError(), -32020, 400),
            (MissingClientCapabilityError({"elicitation": {}}), -32021, 400),
            (UnsupportedProtocolVersionError("1900-01-01", ["2026-07-28"]), -32022, 400),
        ],
    )
    def test_code_and_http_status(self, error, code, http_status):
        assert error.code == code
        assert error.http_status == http_status
        assert isinstance(error, McpError)

    def test_base_mcp_error_defaults(self):
        err = McpError(-32000, "custom implementation-defined error")
        assert err.http_status == 400
        assert err.data is None

    def test_missing_capability_data_shape(self):
        # Schema: data.requiredCapabilities is REQUIRED and shaped like a
        # ClientCapabilities object.
        err = MissingClientCapabilityError({"elicitation": {"form": {}}})
        assert err.data == {"requiredCapabilities": {"elicitation": {"form": {}}}}
        assert err.required == {"elicitation": {"form": {}}}

    def test_unsupported_version_data_shape(self):
        err = UnsupportedProtocolVersionError("1900-01-01", ("2026-07-28", "2025-11-25"))
        assert err.data == {
            "supported": ["2026-07-28", "2025-11-25"],
            "requested": "1900-01-01",
        }

    def test_to_error_response_with_and_without_id(self):
        err = InvalidParamsError("missing _meta")
        with_id = err.to_error_response("req-1")
        assert with_id == {
            "jsonrpc": "2.0",
            "id": "req-1",
            "error": {"code": -32602, "message": "missing _meta"},
        }
        # id omitted (not null) when the request id was unreadable.
        without_id = err.to_error_response(None)
        assert "id" not in without_id

    def test_errors_are_raisable_and_carry_message(self):
        with pytest.raises(McpError, match="unknown tool"):
            raise InvalidParamsError("unknown tool 'frobnicate'")


# ---------------------------------------------------------------------------
# DiscoverResult / CacheableResult serialization (SEP-2549, SEP-2322)
# ---------------------------------------------------------------------------


class TestDiscoverResultSerialization:
    def make_discover_result(self, **overrides) -> DiscoverResult:
        kwargs: dict = {
            "supported_versions": list(SUPPORTED_VERSIONS),
            "capabilities": ServerCapabilities(
                tools={"listChanged": True},
                extensions={"io.modelcontextprotocol/skills": {"directoryRead": True}},
            ),
            "server_info": Implementation(name="virtual-library", version="0.1.0"),
            "ttl_ms": 3_600_000,
            "cache_scope": "public",
        }
        kwargs.update(overrides)
        return DiscoverResult(**kwargs)

    def test_wire_shape_includes_all_required_fields(self):
        wire = self.make_discover_result().to_wire()

        # SEP-2322: resultType REQUIRED on every result.
        assert wire["resultType"] == "complete"
        # SEP-2549: ttlMs and cacheScope REQUIRED on cacheable results.
        assert wire["ttlMs"] == 3_600_000
        assert wire["cacheScope"] == "public"
        # camelCase aliases on the wire, not snake_case.
        assert wire["supportedVersions"] == list(SUPPORTED_VERSIONS)
        assert wire["serverInfo"] == {"name": "virtual-library", "version": "0.1.0"}
        assert "supported_versions" not in wire
        assert "server_info" not in wire

    def test_extensions_survive_serialization(self):
        wire = self.make_discover_result().to_wire()
        assert wire["capabilities"]["extensions"] == {
            "io.modelcontextprotocol/skills": {"directoryRead": True}
        }
        assert wire["capabilities"]["tools"] == {"listChanged": True}

    def test_optional_instructions_omitted_when_absent(self):
        wire = self.make_discover_result().to_wire()
        assert "instructions" not in wire

        wire = self.make_discover_result(instructions="A library server.").to_wire()
        assert wire["instructions"] == "A library server."

    def test_parses_spec_wire_example(self):
        # Verbatim example from the draft schema documentation.
        result = DiscoverResult.model_validate(
            {
                "resultType": "complete",
                "supportedVersions": ["2026-07-28"],
                "capabilities": {"tools": {}, "resources": {}},
                "serverInfo": {"name": "ExampleServer", "version": "1.0.0"},
                "instructions": "This server provides weather and resource utilities.",
                "ttlMs": 3600000,
                "cacheScope": "public",
            }
        )
        assert result.supported_versions == ["2026-07-28"]
        assert result.ttl_ms == 3600000
        assert result.cache_scope == "public"

    def test_negative_ttl_rejected(self):
        with pytest.raises(ValueError, match=r"ttlMs|greater than or equal"):
            self.make_discover_result(ttl_ms=-1)

    def test_invalid_cache_scope_rejected(self):
        with pytest.raises(ValueError, match=r"cacheScope|cache_scope"):
            self.make_discover_result(cache_scope="shared")

    def test_list_tools_result_carries_cache_fields(self):
        result = ListToolsResult(
            tools=[Tool(name="search_catalog", input_schema={"type": "object"})],
            ttl_ms=300_000,
            cache_scope="private",
        )
        wire = result.to_wire()
        assert wire["resultType"] == "complete"
        assert wire["ttlMs"] == 300_000
        assert wire["cacheScope"] == "private"
        assert wire["tools"][0]["inputSchema"] == {"type": "object"}


# ---------------------------------------------------------------------------
# Capability models tolerate unknown fields (capabilities are open sets)
# ---------------------------------------------------------------------------


class TestCapabilityTolerance:
    def test_client_capabilities_unknown_fields_kept(self):
        caps = ClientCapabilities.model_validate(
            {
                "elicitation": {"form": {}},
                "someFutureCapability": {"setting": 1},
            }
        )
        assert caps.elicitation is not None
        # Unknown members are tolerated AND round-tripped.
        assert caps.to_wire()["someFutureCapability"] == {"setting": 1}

    def test_server_capabilities_unknown_fields_kept(self):
        caps = ServerCapabilities.model_validate(
            {
                "tools": {"listChanged": True},
                "somethingNew": {},
            }
        )
        assert caps.to_wire()["somethingNew"] == {}

    def test_nested_capability_unknown_fields_kept(self):
        caps = ClientCapabilities.model_validate({"elicitation": {"form": {}, "voice": {}}})
        assert caps.elicitation is not None
        assert caps.elicitation.to_wire()["voice"] == {}

    def test_empty_capabilities_object_is_valid(self):
        # {} = "no optional capabilities" — the common minimal request.
        caps = ClientCapabilities.model_validate({})
        assert caps.elicitation is None
        assert caps.sampling is None
        assert caps.extensions is None


# ---------------------------------------------------------------------------
# MRTR result shapes and helpers
# ---------------------------------------------------------------------------


class TestResultShapesAndHelpers:
    def test_input_required_result_parses_spec_example(self):
        # Verbatim (trimmed) from schema/draft/examples/InputRequiredResult.
        result = InputRequiredResult.model_validate(
            {
                "resultType": "input_required",
                "inputRequests": {
                    "github_login": {
                        "method": "elicitation/create",
                        "params": {
                            "message": "Please provide your GitHub username",
                            "requestedSchema": {
                                "type": "object",
                                "properties": {"name": {"type": "string"}},
                                "required": ["name"],
                            },
                        },
                    }
                },
                "requestState": "eyJsb2NhdGlvbiI6Ik5ldyBZb3JrIn0",
            }
        )
        assert result.result_type == "input_required"
        assert result.input_requests is not None
        request = result.input_requests["github_login"]
        assert isinstance(request, ElicitRequest)
        assert request.method == "elicitation/create"
        assert result.request_state == "eyJsb2NhdGlvbiI6Ik5ldyBZb3JrIn0"

    def test_input_required_result_defaults_result_type(self):
        result = InputRequiredResult(request_state="opaque")
        assert result.to_wire() == {
            "resultType": "input_required",
            "requestState": "opaque",
        }

    def test_url_mode_elicit_request(self):
        request = ElicitRequest(
            params=ElicitRequestURLParams(
                mode="url",
                message="Complete sign-in in your browser",
                url="https://example.com/auth",
            )
        )
        wire = request.to_wire()
        assert wire["method"] == "elicitation/create"
        assert wire["params"]["mode"] == "url"

    def test_call_tool_result_wire_shape(self):
        result = CallToolResult(content=[TextContent(text="3 books found")])
        wire = result.to_wire()
        assert wire["resultType"] == "complete"
        assert wire["content"] == [{"type": "text", "text": "3 books found"}]
        assert "isError" not in wire  # defaults are omitted, not nulled

    def test_subscription_filter_aliases(self):
        f = SubscriptionFilter.model_validate(
            {
                "toolsListChanged": True,
                "resourceSubscriptions": ["library://books/978-0-134-68547-9"],
            }
        )
        assert f.tools_list_changed is True
        assert f.resource_subscriptions == ["library://books/978-0-134-68547-9"]
        assert f.prompts_list_changed is None

    def test_complete_result_helper_defaults_result_type(self):
        assert complete_result({"tools": []}) == {"tools": [], "resultType": "complete"}

    def test_complete_result_helper_preserves_explicit_result_type(self):
        payload = {"resultType": "input_required", "requestState": "x"}
        assert complete_result(payload)["resultType"] == "input_required"

    def test_error_response_helper(self):
        response = error_response(7, -32602, "unknown prompt", data={"name": "nope"})
        assert response == {
            "jsonrpc": "2.0",
            "id": 7,
            "error": {"code": -32602, "message": "unknown prompt", "data": {"name": "nope"}},
        }

    def test_error_response_helper_omits_absent_id_and_data(self):
        response = error_response(None, -32700, "Parse error")
        assert response == {"jsonrpc": "2.0", "error": {"code": -32700, "message": "Parse error"}}
