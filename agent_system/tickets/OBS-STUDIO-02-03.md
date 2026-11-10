# OBS-STUDIO-02-03 — Claude native agent integration

Status: compatibility research started; adapter not implemented or enabled.
Parent: [OBS-STUDIO-02](OBS-STUDIO-02.md). Checked: 2026-11-10.

## Scope and acceptance

Implement a second adapter through the supported Claude Agent SDK/native binary
without a replacement tool loop. Preserve native sessions, streaming, approval
meaning, bounded interrupt/owned-process cleanup, scoped Studio research tools
and the independent snapshot/backtest approval. Show only supported native
controls; keep provider identity immutable per conversation.

Admission requires a real installed/authenticated provider: strategy authoring,
file/command decisions, approved canonical backtest, results, cancellation,
shutdown and native conversation resume after restart. Protocol fixtures alone
do not qualify. Claude, Cursor Agent and DeepSeek executables were not found on
the current PATH; only Codex is presently admitted. No additional agent or paid
service was installed during this compatibility check.

## Current primary-source findings

The [SDK overview](https://code.claude.com/docs/en/agent-sdk/overview) describes a
Python/TypeScript library that runs the native binary and provides permissions,
sessions, streaming and MCP. This fits the existing Python adapter boundary.
Its integration guidance directs product developers toward API-key authentication
and restricts offering Claude account login without approval. For an SDK-backed
selector, it recommends the label **Claude Agent**, rather than Claude Code.

The [native integration guidance](https://code.claude.com/docs/en/legal-and-compliance)
also describes products running an unmodified Claude Code binary: users retain
its authentication methods and authenticate for themselves, with usage billed to
them. It prohibits collecting or intermediating users' account credentials and
tokens. Observa must not add its own Claude OAuth flow, extract credentials, or
promise to resell access. Review the exact selected SDK/binary arrangement against
that guidance before implementing onboarding; this note is not a legal clearance.

The [plan usage article](https://support.claude.com/en/articles/15036540-use-the-claude-agent-sdk-with-your-claude-plan)
currently says SDK and `claude -p` usage signed into a Claude plan still draws on
subscription limits. Its October 7 update separately describes linked Console API
credits for some plans. Billing availability is not by itself permission for an
embedded sign-in flow, nor a guarantee of account quota. Do not imply an API key
and a consumer subscription are interchangeable.

## Implementation sequence

1. Inspect the current supported Python SDK transport, permission callbacks,
   native configuration isolation, session resume and cancellation behavior.
   Pin a tested version; avoid private or reverse-engineered protocol hooks.
2. Resolve supported authentication/readiness without requesting inference or
   copying credentials. Existing user-owned native setup remains provider-owned.
3. Add the optional adapter and native controls with failure-path tests. Keep it
   unavailable until live acceptance evidence exists. Do not weaken isolation or
   silently fall back to automatic approvals to bypass an unsupported feature.
4. Run the acceptance workflow using an explicitly configured account. If the
   chosen route requires a new paid dependency or materially changes the approved
   architecture, present that concrete decision before proceeding.
