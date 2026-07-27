from dataclasses import dataclass


@dataclass(frozen=True)
class Principal:
    """The identity of the requester (and, if elevated, the subject they are
    diagnosing on behalf of). This is a self-declared login id, not a
    cryptographically verified token — see app/dependencies/auth.py. Still
    never take a subject from a client-supplied body field or LLM output;
    it must come from `sub`."""

    sub: str
    roles: tuple[str, ...] = ()

    def has_role(self, role: str) -> bool:
        return role in self.roles
