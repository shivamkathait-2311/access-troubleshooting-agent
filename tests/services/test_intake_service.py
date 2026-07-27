"""IntakeService.submit()'s login-resolution behavior — see
app/services/intake_service.py. Fakes/mocks for the connector, policy
store, repository, audit, and LLM client, so no network/DB is touched."""

from unittest.mock import AsyncMock

import pytest

from app.connectors.base import ConnectorSPI
from app.core.exceptions import LoginNotFoundError
from app.policy.schema import ConnectorConfig, SystemPolicy
from app.schemas.intake import ComplaintCategory, ComplaintIntake, DiagnosticRequestDraft
from app.services.intake_service import IntakeService

_SYSTEM_ID = "openiam"


class _FakeConnector(ConnectorSPI):
    """Only resolve_subject_sub is exercised by IntakeService.submit()."""

    def __init__(self, resolved_sub: str | None):
        super().__init__(_SYSTEM_ID, {})
        self._resolved_sub = resolved_sub
        self.resolve_calls: list[str] = []

    async def resolve_subject_sub(self, login_id: str) -> str | None:
        self.resolve_calls.append(login_id)
        return self._resolved_sub

    async def check_availability(self, subject_sub: str):
        raise NotImplementedError

    async def get_user_status(self, subject_sub: str):
        raise NotImplementedError

    async def get_auth_events(self, subject_sub: str, time_window):
        raise NotImplementedError

    async def get_effective_permissions(self, subject_sub: str, resource: str):
        raise NotImplementedError

    async def get_required_permissions(self, resource: str):
        raise NotImplementedError

    async def get_permission_audit_events(self, subject_sub: str, time_window):
        raise NotImplementedError


class _FakePolicyStore:
    def __init__(self, policy: SystemPolicy):
        self._policy = policy

    def get(self, system_id: str) -> SystemPolicy:
        assert system_id == self._policy.system_id
        return self._policy


class _FakeConnectorRegistry:
    def __init__(self, connector: ConnectorSPI):
        self._connector = connector

    def get_connector(self, connector_id: str, connector_type: str, config: dict):
        return self._connector


def _make_policy() -> SystemPolicy:
    return SystemPolicy(
        system_id=_SYSTEM_ID,
        display_name="OpenIAM",
        connector=ConnectorConfig(type="openiam", credential_path="secret/connectors/openiam"),
    )


def _make_intake() -> ComplaintIntake:
    return ComplaintIntake(
        login_id="test.client22", free_text="i can not log in", system_id=_SYSTEM_ID
    )


def _make_service(connector: ConnectorSPI) -> IntakeService:
    llm_client = AsyncMock()
    llm_client.parse = AsyncMock(
        return_value=DiagnosticRequestDraft(
            complaint_category=ComplaintCategory.LOGIN_FAILURE,
            free_text_summary="Can't log in",
        )
    )
    repository = AsyncMock()
    audit = AsyncMock()
    policy_store = _FakePolicyStore(_make_policy())
    connector_registry = _FakeConnectorRegistry(connector)
    return IntakeService(llm_client, repository, audit, policy_store, connector_registry)


async def test_submit_resolves_login_and_persists_subject_sub() -> None:
    connector = _FakeConnector(resolved_sub="8a80816f9f3615c8019f3b2735150040")
    service = _make_service(connector)

    request_model = await service.submit(
        login_id="test.client22", intake=_make_intake(), correlation_id="corr-1"
    )

    assert connector.resolve_calls == ["test.client22"]
    assert request_model.subject_sub == "8a80816f9f3615c8019f3b2735150040"
    assert request_model.requester_sub == "8a80816f9f3615c8019f3b2735150040"
    service.repository.create_request.assert_awaited_once()
    service.audit.record.assert_awaited_once()


async def test_submit_raises_login_not_found_when_connector_returns_none() -> None:
    connector = _FakeConnector(resolved_sub=None)
    service = _make_service(connector)

    with pytest.raises(LoginNotFoundError):
        await service.submit(login_id="nope", intake=_make_intake(), correlation_id="corr-2")

    # Not found should fail fast — no LLM spend, no persistence, no audit.
    service.repository.create_request.assert_not_awaited()
    service.llm_client.parse.assert_not_awaited()
    service.audit.record.assert_not_awaited()
