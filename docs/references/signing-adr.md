---
title: "ADR-001 — Agent Card Signing: Algorithm & Key Storage"
status: accepted
date: 2026-05-19
deciders: Proteus, Fleety
context: Phase 3 — A2A Protocol Adapter
created: 2026-06-16
type: reference
tags: [a2a, signing, adr, security]
---

# ADR-001: Agent Card Signing — Algorithm & Key Storage

## Context

The A2A plugin must publish signed Agent Cards per the A2A v1.0 specification (Section 8.4). Signatures let mesh peers verify that an Agent Card was issued by the node claiming it. The plugin needs to decide:

1. **Which signing algorithm** to use (ES256, ES384, ES521, RS256, HS256, EdDSA)
2. **Where to store the private key** (filesystem path, Keychain, KMS, env var, credential pool)

## Decision: ES256 with per-profile `.env` storage

### Algorithm: ES256 (ECDSA P-256)

| Criterion | ES256 | HS256 | RS256 | EdDSA |
|-----------|-------|-------|-------|-------|
| Asymmetric (no secret sharing) | ✅ | ❌ | ✅ | ✅ |
| Fast key generation (<100ms) | ✅ | ✅ | ❌ (2-5s for 2048-bit) | ✅ |
| Compact signatures | 64 bytes | 32 bytes | 256 bytes | 64 bytes |
| PyJWT stability (Hermes pinned) | ✅ Battle-tested | ✅ | ✅ | ⚠️ JWK edge cases |
| FIPS 186-4 compliant | ✅ | ✅ | ✅ | ❌ |

**ES256** is the default for JWK (`kty: EC`, `crv: P-256`) per RFC 7517. A future switch to EdDSA or KMS-backed RS256 requires only changing the `create_signer()` call.

**HS256 ruled out** — symmetric, so verifiers need the same secret as signers. Breaks the mesh model where any node independently verifies any card.

**RS256 ruled out** — key generation takes seconds, creating a poor setup experience. Signatures are 4× larger with no security benefit for self-descriptions.

**EdDSA ruled out for now** — PyJWT's implementation had known JWK edge cases at Hermes v0.14.0's pinned dependency versions. Most likely successor when Hermes upgrades PyJWT.

### Key Storage: Per-profile `.env` file

```bash
# ~/.hermes/profiles/<name>/.env (0o600)
A2A_SIGNING_KEY=<base64-encoded EC P-256 PEM>
```

The private key is stored as a single-line base64-encoded PEM in the profile's existing `.env` file. This is the same mechanism Hermes already uses for all per-profile secrets.

**Why `.env` wins:** The threat model is directory-poisoning — an attacker who compromises a mesh peer's filesystem can forge Agent Cards regardless of storage format. `.env` is `0o600`, excluded from version control, and already part of Hermes's security posture. Adding a new secret store when `.env` exists and works would be architectural overhead with no security gain.

| Approach | Audit-passing? | Cross-platform | Notes |
|----------|---------------|----------------|-------|
| Per-profile `.env` | ✅ | ✅ | Same pattern as existing Hermes secrets |
| macOS Keychain only | ✅ | ❌ | Linux fallback is always a file |
| Config YAML inline | ✅ | ✅ | Co-location fair but `.env` is the documented pattern |
| PEM file on disk | ❌ | ✅ | Instant fail on audit |
| KMS / HSM | ✅ | ❌ | Right answer for 100+ nodes, over-engineered for small mesh |

## Consequences

1. **Upgrade path.** When the mesh grows to KMS-managed keys, replace the loader — same `create_signer()` call downstream.

2. **Key rotation.** Delete the line from `.env` and restart. `ensure_keys()` generates a new key. Mesh peers pick up the new Agent Card on next fetch.

3. **Multi-node.** Each node generates its own key. No key distribution needed — nodes exchange public keys as part of Agent Card discovery (the JWS signature includes the `kid` header, verifier fetches the public key from the card itself via `jku`).

## Future Considerations

- **Ed25519 / EdDSA** — When PyJWT has stable support, switching is a one-line change in `create_signer()`. No key migration needed.
- **TPM / Secure Enclave** — Signing happens at server startup. A wrapped key unlocked on boot and held in process memory would strengthen the audit story.
- **Key rotation at scale** — Not needed until the mesh has enough nodes that a compromised key is a meaningful blast radius.
