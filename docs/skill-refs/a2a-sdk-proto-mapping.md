# Proto Descriptor Mapping — a2a-sdk v1.0

Key discoveries from M0.3/M1.2 integration testing. The a2a-sdk v1.0.3 protobuf types differ from spec documentation examples in several field names.

## Golden Rule: Always check the protobuf descriptor, not the docs

```python
from a2a.types import AgentCard, AgentCapabilities
for f in AgentCard.DESCRIPTOR.fields:
    print(f.name)
```

This prints the EXACT field names the SDK expects. Spec docs, blog posts, and example code may use outdated or different names.

## AgentCard Field Corrections

| Field location | Expected name | Actual name |
|---|---|---|
| `AgentCard` top-level | `url` | **Removed** — use `supported_interfaces[i].url` |
| `AgentCard.capabilities` | `streaming`, `push` | `streaming`, `push_notifications` |
| `AgentCard.provider` | `.origin`, `.name` | **`url`** (for URL), **`organization`** (for name) |
| `AgentCard.default_input_modes` | `["text"]` | Works with `["text/plain"]` |
| `Task` state | `.state` | **Removed** — use `Task.status` (a `TaskStatus` message with `.state`, `.message`, `.timestamp`) |

## JSON-RPC Protocol Quirks

| Expectation | Reality |
|---|---|
| Method names `tasks/get`, `message/send` | **PascalCase**: `GetTask`, `ListTasks`, `SendMessage`, `CancelTask` |
| Role `user`, `agent` | **SCREAMING_SNAKE**: `ROLE_USER`, `ROLE_AGENT` |
| Version header optional | **Required**. Defaults to `0.3` if missing → `VersionNotSupportedError` |

## AgentExecutor ABC

Abstract methods: **`execute()` + `cancel()`** — must implement both.

## JWS Signing

- Algorithm: ES256 (EC P-256)
- Keys: PEM format, stored in `~/.hermes/plugins/a2a/keys/`
- Signer: `create_agent_card_signer(signing_key=private_pem, protected_header=ProtectedHeader(kid='a2a-key-v1', alg='ES256'))`
- Verifier: `create_signature_verifier(lambda kid, jku: public_pem, algorithms=['ES256'])`
