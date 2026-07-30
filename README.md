# Access Troubleshooting Agent

A generic, system-agnostic diagnostic agent that resolves common access issues
(login failures, permission denials, locked accounts, outages) without a
helpdesk ticket. It runs a diagnostic pipeline — system availability, account
status, auth events, authorization, path/infrastructure — across pluggable
connectors, then returns a self-service fix, an approval-gated remediation, or
an escalation with a full diagnostic bundle.

Read-only by default. Full auditability. Decision-making is a deterministic
state machine by default (`DiagnosticOrchestrator`, not an LLM); an opt-in LLM
tool-calling agent (`LLMDiagnosticOrchestrator`) exists as an alternative — see
"LLM diagnostic agent" under Status.

## Status

Phase 1 MVP, in progress, targeting OpenIAM as the first connector (not
Keycloak, the design doc's reference implementation — swapped since OpenIAM
is the real system available for testing).

Working end-to-end, verified live against a real OpenIAM instance:
- Intake: caller supplies a `login_id` (e.g. `test.client22`, not an internal
  ID) → resolved to the real subject via `ConnectorSPI.resolve_subject_sub`
  (`GET /webconsole/rest/api/users/search`) before anything else runs; no
  match → clean `LOGIN_NOT_FOUND` error, no diagnostic request created →
  LLM-parsed complaint (OpenAI) → the 4-check deterministic funnel (system
  availability, account status, auth events, authorization) → outcome
  mapping (self-service fix / access gap / escalation) → audit trail.
- `OpenIAMConnector`: all 7 methods implemented — `resolve_subject_sub`,
  `check_availability` (per-*user* managed-system connection-test status via
  `managedsys-dashboard/search`, not a generic ping — confirmed live),
  `get_user_status` (locked and disabled are confirmed live against real
  accounts; password_expired and deprovisioned are implemented against
  confirmed-live field shapes — `principalList[].pwdExp`, `.active`,
  `.status` — but not yet verified against a real account actually in one
  of those states; deprovisioned's `"DELETE"` login-status value in
  particular is an explicit unconfirmed guess, see code comment),
  `get_auth_events` (`/webconsole/rest/api/auditlog/search`, which needed
  two fixes beyond the initial guess — a required `offset` query param
  missing from the public docs, and session cookies alongside the OAuth
  bearer token, now cached in Redis — see `token_client.py`),
  `get_effective_permissions`, `get_required_permissions`,
  `get_permission_audit_events`.
- Auth-events failure causes: `wrong_password`, `invalid_login`, and
  `account_locked` are real, confirmed-live causes, parsed from the audit
  log's embedded `errorCode` (not the `action` field, which is just
  `"LOGIN"` for every attempt regardless of outcome — see
  `_extract_failure_cause` in `app/connectors/openiam/connector.py`).
- LLM diagnostic agent (`app/orchestrator/agent_loop.py`,
  `LLMDiagnosticOrchestrator`): an opt-in alternative to the deterministic
  funnel — set `DIAGNOSTIC_ORCHESTRATOR_MODE=llm_agent` to enable (default
  is `deterministic`). The LLM gets tool-calling access to the same 6
  read-only checks (zero-argument tools, redacted results — no raw vendor
  text, IDs, IPs, or reset URLs ever reach it) and decides which to call,
  in what order, and when to stop; `cause_code`/`Outcome` are always
  re-derived by the same deterministic step modules, never trusted from
  LLM output, and any failure fails closed to escalation. Smoke-tested live
  against real OpenAI: works and matches the deterministic path on simple,
  single-cause complaints (e.g. a locked account, an outage); does **not**
  yet reliably reach a final answer on anything requiring more than ~2
  tool calls — `gpt-4o-mini` tends to call every tool one at a time rather
  than stopping early or batching, exhausting the default 6-turn budget
  before it can answer. Not yet proven better than the deterministic path;
  see "Known gaps."
- 111 tests across `tests/` (connectors, orchestrator steps, the LLM
  agent's control flow and tool redaction, verdict messages, the OpenAI
  client's tool-calling plumbing, intake service) — see `tests/orchestrator/
  test_diagnostic_funnel.py` for the funnel's named scenarios (locked
  account, expired password, missing role, outage) and `tests/orchestrator/
  test_agent_loop.py`/`test_agent_tools.py` for the LLM agent.

Known gaps:
- `get_user_status`'s `password_expired`/`deprovisioned` detection hasn't
  been verified against a real account actually in that state yet (unlike
  `locked`/`disabled`, which have been) — built against confirmed-live
  field shapes, not a confirmed-live trigger. `deprovisioned`'s `"DELETE"`
  login-status value specifically is an unconfirmed guess.
- Auth-events causes `mfa_failure`/`session_expiry` (from the original
  design doc's list) have no confirmed live signal yet — no MFA-triggering
  test scenario has been found in this OpenIAM instance's audit history, so
  there's nothing to confirm a real errorCode against. Anything not yet
  mapped still passes through as the raw errorCode rather than being
  dropped.
- The LLM diagnostic agent doesn't reliably finish for non-trivial
  (multi-tool) cases within the default turn budget — see above. Candidate
  fixes (raise `LLM_AGENT_MAX_TOOL_TURNS`, push the prompt harder toward
  batching/early-stop, try a stronger model) are identified but not tried.
- `Outcome.REMEDIATION_PENDING` is deliberately unreachable — no
  remediation playbooks exist yet (see `app/orchestrator/outcome_policy.py`
  for the reasoning).
- Remediation (`app/remediation/`, `app/api/remediation.py`) and step 5
  (path/infrastructure, `app/logquery/`) are out of scope for this phase —
  stubs only, by design, not gaps to fix.
- No `docs/threat-model.md` yet (a Phase 0 deliverable per the design doc).

## Architecture

- **`app/api/`** — FastAPI routers (health, intake, Slack/Teams webhooks,
  diagnostics, remediation, audit).
- **`app/orchestrator/`** — 5-step diagnostic funnel, only 4 steps wired up
  (step 5/path-infrastructure is a stub, never walked). Two interchangeable
  implementations of `DiagnosticOrchestratorProtocol`: `DiagnosticOrchestrator`
  (`state_machine.py`, default) walks the 4 steps in a fixed order,
  stopping at the first non-PASS; `LLMDiagnosticOrchestrator`
  (`agent_loop.py`, opt-in) lets an LLM decide which to check and when to
  stop instead — see Status. Both share the same outcome policy
  (`outcome_policy.py`) and fail-closed rule: any error/timeout/budget
  exhaustion becomes `INCONCLUSIVE` and escalates, never a raw exception.
  The only components allowed to invoke remediation.
- **`app/connectors/`** — pluggable system SPI (`ConnectorSPI`). Onboarding a
  new system is policy config, not new orchestrator code. Only `OpenIAMConnector`
  is a real implementation; Keycloak/LDAP/DB-grants/generic-REST are stubs.
- **`app/policy/`** — declarative, Git-managed per-system YAML (connector
  config, health endpoints, role↔resource maps, playbook references). Loaded
  once at boot; no runtime write path.
- **`app/llm/`** — three LLM call sites via `LLMClient`. Two are narrow,
  zero-tool-authority calls (`parse`/`complete`): an intake parser (free
  text → structured, schema-validated request) and an explanation layer
  (redacted verdict codes → user-facing text, written but not currently
  wired into the response path — static templates are used instead, see
  `verdict_messages.py`). The third, `run_tool_turn`, is a deliberately
  separate capability that *does* have tool authority — used only by the
  opt-in LLM diagnostic agent (`app/orchestrator/agent_loop.py`), calling
  6 fixed, zero-argument, read-only tools (`app/orchestrator/agent_tools.py`)
  whose results are redacted before the model ever sees them (no raw
  vendor text, IDs, IPs, actor identities, or reset URLs).
- **`app/remediation/`** — allow-listed, tiered playbooks only, approval-gated
  above tier 0, with a kill switch and rollback capture.
- **`app/audit/`** — append-only record of every run/check/verdict/action.

## Getting Started

```bash
uv sync
docker compose up -d            # Postgres + Redis
# docker compose --profile connectors up -d   # + Keycloak, for connector dev
make migrate
make run
```

`GET /health` should return 200 and `GET /metrics` should return Prometheus
text once the app is running.

Docker is only used here for Postgres and Redis. The app itself is never
containerized in dev — `make run` (and the `Dockerfile`'s `CMD`) both just run
plain uvicorn:

```bash
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

Point `DATABASE_URL`/`REDIS_URL` in `.env` at any reachable Postgres/Redis
(the `docker-compose.yml` instances, or ones you run natively) and this works
with no Docker involved at all.

`uv run` picks up the project's `.venv` automatically, so activating it isn't
required. To activate it manually instead (e.g. to run `python`, `pytest`,
etc. directly without the `uv run` prefix):

```bash
source .venv/bin/activate
# ... run commands directly, e.g. uvicorn app.main:app --reload ...
deactivate
```

If `.venv` doesn't exist yet or looks stale, recreate it with `uv sync`.

## Configuration

Copy `.env.example` to `.env` and fill in values. See `app/core/config.py`
for the full settings surface.

## Testing

```bash
make test
make lint
make typecheck
```

## Policy Authoring

System policies live under `app/policy/policies/*.yaml` and are validated at
process startup (`app/policy/loader.py`). Changes must go through a PR review
— there is deliberately no runtime API to edit policy.

## Contributing

This is an early-stage internal tool. Open a PR; policy and playbook changes
require review per the security model described in the project design doc.
