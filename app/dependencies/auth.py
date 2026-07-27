from fastapi import Header

from app.core.exceptions import UnauthorizedError
from app.core.security import Principal


async def get_principal(x_login_id: str | None = Header(default=None)) -> Principal:
    """Identity for this internal tool: the caller declares their own login
    id (their OpenIAM username) via the X-Login-Id header — there is no
    IdP/JWT in play, so this is not cryptographically verified. The
    diagnostic subject always comes from `principal.sub`, never from a
    request body field, keeping the rest of the system (intake, audit
    scoping, DiagnosticContext) unaware that the identity source changed.
    """
    if not x_login_id:
        raise UnauthorizedError("Missing X-Login-Id header")
    return Principal(sub=x_login_id)
