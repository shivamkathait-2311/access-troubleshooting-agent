# Access Troubleshooting Agent

A generic, system-agnostic diagnostic agent that resolves common access issues
(login failures, permission denials, locked accounts, outages) without a
helpdesk ticket. It runs a deterministic diagnostic pipeline — system
availability, account status, auth events, authorization, path/infrastructure
— across pluggable connectors, then returns a self-service fix, an
approval-gated remediation, or an escalation with a full diagnostic bundle.

Read-only by default. Deterministic decision-making (the orchestrator is a
state machine, not an LLM). Full auditability.

## Status

Phase 1 MVP, in progress, targeting OpenIAM as the first connector (not
Keycloak, the design doc's reference implementation — swapped since OpenIAM
is the real system available for testing).

Working end-to-end, verified live against a real OpenIAM instance:
- Intake (LLM-parsed via OpenAI) → the 4-check deterministic funnel (system
  availability, account status, auth events, authorization) → outcome
  mapping (self-service fix / access gap / escalation) → audit trail.
- `OpenIAMConnector`: all 5 methods implemented and confirmed live,
  including `get_auth_events` (`/webconsole/rest/api/auditlog/search`),
  which needed two fixes beyond the initial guess — a required `offset`
  query param missing from the public docs, and session cookies (not just
  the OAuth bearer token) for this specific endpoint, now cached in Redis
  alongside the access token (see `token_client.py`).
- 4 named unit test scenarios (locked account, expired password, missing
  role, outage) pass against a fake connector — see
  `tests/orchestrator/test_diagnostic_funnel.py`.

Known gaps:
- `get_user_status` can't yet detect an expired password — OpenIAM's
  `UserBean.userStatus` has no such value; the real flag lives elsewhere
  and hasn't been located in a live response yet.
- `Outcome.REMEDIATION_PENDING` is deliberately unreachable — no
  remediation playbooks exist yet (see `app/orchestrator/state_machine.py`
  for the reasoning).
- Remediation (`app/remediation/`, `app/api/remediation.py`) and step 5
  (path/infrastructure, `app/logquery/`) are out of scope for this phase —
  stubs only, by design, not gaps to fix.
- No `docs/threat-model.md` yet (a Phase 0 deliverable per the design doc).

## Architecture

- **`app/api/`** — FastAPI routers (health, intake, Slack/Teams webhooks,
  diagnostics, remediation, audit).
- **`app/orchestrator/`** — deterministic 5-step diagnostic funnel. Fail-closed:
  any error/timeout becomes `INCONCLUSIVE` and escalates. The only component
  allowed to invoke remediation.
- **`app/connectors/`** — pluggable system SPI (`ConnectorSPI`). Onboarding a
  new system is policy config, not new orchestrator code.
- **`app/policy/`** — declarative, Git-managed per-system YAML (connector
  config, health endpoints, role↔resource maps, playbook references). Loaded
  once at boot; no runtime write path.
- **`app/llm/`** — two narrow, zero-tool-authority LLM calls: an intake
  parser (free text → structured, schema-validated request) and an
  explanation layer (redacted verdict codes → user-facing text).
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
