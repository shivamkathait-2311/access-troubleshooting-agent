from typing import Any

from app.connectors.base import ConnectorSPI
from app.connectors.db_grants.postgres import PostgresGrantsConnector
from app.connectors.keycloak.connector import KeycloakConnector
from app.connectors.ldap.connector import LdapConnector
from app.connectors.openiam.connector import OpenIAMConnector
from app.connectors.rest_generic.connector import GenericRestConnector
from app.core.exceptions import ConnectorNotRegisteredError

_CONNECTOR_TYPES: dict[str, type[ConnectorSPI]] = {
    "keycloak": KeycloakConnector,
    "ldap": LdapConnector,
    "db_grants_postgres": PostgresGrantsConnector,
    "rest_generic": GenericRestConnector,
    "openiam": OpenIAMConnector,
}


class ConnectorRegistry:
    """Maps a policy's `connector.type` string to a connector class.

    Built once at app startup from the loaded PolicyStore (see
    app/policy/store.py) — adding a new system type is a one-line addition
    to _CONNECTOR_TYPES plus a new connector implementation, never a change
    to the orchestrator.
    """

    def __init__(self) -> None:
        self._instances: dict[str, ConnectorSPI] = {}

    def get_connector(
        self, connector_id: str, connector_type: str, config: dict[str, Any]
    ) -> ConnectorSPI:
        if connector_id in self._instances:
            return self._instances[connector_id]

        connector_cls = _CONNECTOR_TYPES.get(connector_type)
        if connector_cls is None:
            raise ConnectorNotRegisteredError(
                f"No connector registered for type '{connector_type}'"
            )

        instance = connector_cls(connector_id, config)
        self._instances[connector_id] = instance
        return instance
