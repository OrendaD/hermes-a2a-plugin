---
title: ADR-001 — Agent Card Signing: Algorithm & Key Storage
status: accepted
date: 2026-05-19
deciders: Proteus, Fleety
context: Phase 3 — A2A Protocol Adapter
---

# ADR-001: Agent Card Signing — Algorithm & Key Storage

## Context

The Hermes A2A plugin must publish signed Agent Cards per the A2A v1.0 specification (Section 8.4). Signatures let mesh peers verify that an Agent Card was issued by the node claiming it. The plugin needs to decide:

1. **Which signing algorithm** to use (ES256, ES384, ES521, RS256, HS256, EdDSA)
2. **Where to store the private key** (filesystem path, Keychain, KMS, env var, credential pool)

## Decision: ES256 with per-profile `.env` storage

### Algorithm: ES256 (ECDSA P-256)

Chosen over the available alternatives for these reasons:

| Criterion | ES256 | HS256 | RS256 | EdDSA |
|-----------|-------|-------|-------|-------|
| Asymmetric (no secret sharing) | ✅ | ❌ | ✅ | ✅ |
| Fast key generation (<100ms) | ✅ | ✅ | ❌ (2-5s for 2048-bit) | ✅ |
| Compact signatures | 64 bytes | 32 bytes | 256 bytes | 64 bytes |
| PyJWT stability (Hermes pinned) | ✅ Battle-tested since RFC 7517 | ✅ | ✅ | ⚠️ JWK parsing issues in older versions |
| FIPS 186-4 compliant | ✅ | ✅ | ✅ | ❌ |

**ES256** is the default for JWK (`kty: EC`, `crv: P-256`) per RFC 7517. The SDK's `create_agent_card_signer()` accepts any PyJWK-compatible key — this decision is not locked in forever. A future switch to EdDSA or KMS-backed RS256 requires only changing the `create_signer()` call.

**HS256 ruled out** because it's symmetric — verifiers need the same secret as signers. That works for single-node testing but breaks the mesh model where any node independently verifies any card.

**RS256 ruled out** because key generation takes seconds on an iMac, creating a poor setup-wizard experience. Signatures are 4× larger with no security benefit for self-descriptions.

**EdDSA ruled out** for now because PyJWT's implementation had known JWK edge cases at the time of Hermes v0.14.0's pinned dependency versions. When Hermes upgrades to a PyJWT version with stable EdDSA JWK support, this is the most likely successor.

### Key Storage: Per-profile `.env` file

```bash
# ~/.hermes/profiles/sherlock/.env (0o600)
A2A_SIGNING_KEY=<base64-encoded EC P-256 PEM>
```

The private key is stored as a **single-line base64-encoded PEM** in the profile's existing `.env` file. This is the same mechanism Hermes already uses for all per-profile secrets (API keys, tokens).

Evaluated alternatives:

| Approach | Audit-passing? | Cross-platform | Phase 3 feasible | Notes |
|----------|---------------|----------------|------------------|-------|
| Per-profile `.env` | ✅ Same as existing Hermes secrets | ✅ macOS, Linux, Windows | ✅ | Burdens no new infra. `0o600`, no VC, same pattern as `OPENAI_API_KEY`. |
| macOS Keychain only | ✅ | ❌ Linux, Windows need different backends | ❌ | Three implementations at v1. Linux fallback is always a file anyway. |
| Config YAML inline | ✅ On `0o600` file | ✅ | ✅ | Co-location argument was fair but `.env` is the existing, documented, audited Hermes pattern. |
| PEM file on disk | ❌ Predictable path, flag on any audit | ✅ | ✅ | Instant fail. No argument needed. |
| KMS / HSM | ✅ Gold standard | ❌ Cloud dependency | ❌ | Right answer for 100+ nodes. Over-engineered for a 3-node home mesh. ADR allows this as a Phase 4 upgrade path. |
| Hermes CredentialPool | ✅ | ✅ | ❌ | Built for provider API key failover — OAuth renewals, quota tracking, `STATUS_EXHAUSTED`. JWS signing fits none of that. Using it would be framework abuse. |

**Why `.env` wins:** The threat model is directory-poisoning — an attacker who compromises a mesh peer's filesystem can forge Agent Cards regardless of storage format. `.env` is `0o600`, excluded from version control, and already part of Hermes's security posture. Adding a new secret store for Phase 3 when `.env` exists and works would be architectural overhead with no security gain.

## Consequences

1. **Upgrade path.** When the mesh grows to KMS-managed keys, replace the loader:
   ```python
   # Phase 3 — .env
   b64_pem = os.environ["A2A_SIGNING_KEY"]
   
   # Phase 4 — KMS
   b64_pem = kms_client.decrypt(config["a2a"]["kms_ciphertext"])
   ```
   Same `create_signer()` call downstream.

2. **Key rotation.** Delete the line from `.env` and restart. `ensure_keys()` generates a new key. Mesh peers pick up the new Agent Card on next fetch.

3. **Multi-node.** Each node generates its own key. No key distribution needed — nodes exchange public keys as part of Agent Card discovery (the JWS signature includes the `kid` header, verifier fetches the public key from the card itself via `jku`).

## Future Considerations

- **Ed25519 / EdDSA** — When PyJWT in Hermes's dependency chain has stable support, switching is a one-line change in `create_signer()`. No key migration needed (new keypair on next startup).
- **TPM / Secure Enclave** — Signing happens at server startup. A wrapped key that's unlocked on boot and held in process memory would strengthen the audit story. The SDK's `create_agent_card_signer()` takes `str | bytes | PyJWK` — a hardware-wrapped key that exports its PEM on unlock would work without changing the signer API.
- **Key rotation at scale** — Not needed until the mesh has enough nodes that a compromised key is a meaningful blast radius. At that point, add a key store that supports `kid`-based versioning and rotate via config change + restart.
