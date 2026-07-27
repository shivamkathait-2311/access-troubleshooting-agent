from app.audit.events import AuditEvent
from app.core.logging import logger_adapter


class SiemShipper:
    """Outbound adapter forwarding audit events toward the SIEM. Phase 0:
    a no-op — a later phase implements a syslog/HTTP forwarder against
    settings.SIEM_ENDPOINT. Must never be on the hot path for recording an
    audit event (fire-and-forget / buffered, so a SIEM outage can't block
    diagnostics) — so this stays a no-op rather than raising until that
    forwarder exists, instead of failing every audit write in the meantime.
    """

    async def ship(self, event: AuditEvent) -> None:
        logger_adapter.debug(
            "SIEM forwarding not yet implemented; audit event recorded to DB only",
            event_type=event.event_type.value,
            correlation_id=event.correlation_id,
        )
