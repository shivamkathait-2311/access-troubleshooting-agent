# Shared classification of OpenIAM's raw permission-audit action strings —
# used by both step4_authorization.py's deterministic revoke/sync-advisory
# logic and app/orchestrator/agent_tools.py's redacted tool result for the
# LLM diagnostic agent, so there's one source of truth for "which raw
# actions mean what," not two independently-drifting copies.

# Actions that mean "this specific role/group was removed" — the basis of
# the access_revoked cause. Raw OpenIAM action strings, same as auth_events'
# cause_code being an unbounded raw action string — not normalized here.
REVOKE_ACTIONS = {"DELETE_USER_FROM_ROLE", "DELETE_USER_FROM_GROUP"}

# Provisioning/reconciliation actions — advisory only. Their result/success
# semantics aren't confirmed against OpenIAM's real behavior yet (see
# app/connectors/openiam/connector.py's _SYNC_ACTIONS docstring), so these
# are surfaced as a factual note in `detail` and never gate PASS/FAIL.
SYNC_ADVISORY_ACTIONS = {
    "PROVISIONING",
    "GROUP_PROVISIONING",
    "SEND_REPORT_OF_FAILED_PROVISION_REQUESTS",
    "RETRY_PROVISIONING",
    "RECONCILE_USER",
    "RECONCILE_IDM_WITH_TARGET",
    "RECONCILE_TARGET_WITH_IDM",
    "RECONCILIATION_RECORD_FALSE",
    "SYNCHRONIZATION_ORPHAN",
}
