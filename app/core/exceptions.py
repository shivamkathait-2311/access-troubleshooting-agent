class AppError(Exception):
    """Base application error. Subclasses set status_code/error_code."""

    status_code = 500
    error_code = "INTERNAL_ERROR"

    def __init__(self, message: str, *, error_code: str | None = None):
        self.message = message
        if error_code:
            self.error_code = error_code
        super().__init__(message)


class ValidationError(AppError):
    status_code = 400
    error_code = "VALIDATION_ERROR"


class UnauthorizedError(AppError):
    status_code = 401
    error_code = "UNAUTHORIZED"


class ForbiddenError(AppError):
    status_code = 403
    error_code = "FORBIDDEN"


class NotFoundError(AppError):
    status_code = 404
    error_code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = 409
    error_code = "CONFLICT"


class ExternalServiceError(AppError):
    status_code = 502
    error_code = "EXTERNAL_SERVICE_ERROR"


class ServiceUnavailableError(AppError):
    status_code = 503
    error_code = "SERVICE_UNAVAILABLE"


class PayloadTooLargeError(AppError):
    status_code = 413
    error_code = "PAYLOAD_TOO_LARGE"


# ---- Domain-specific errors ----


class PolicyValidationError(AppError):
    """A system policy YAML file failed schema validation at load time."""

    status_code = 500
    error_code = "POLICY_VALIDATION_ERROR"


class ConnectorNotRegisteredError(NotFoundError):
    """A policy references a connector type with no registered implementation."""

    error_code = "CONNECTOR_NOT_REGISTERED"


class LoginNotFoundError(NotFoundError):
    """No user found matching a caller-supplied login id
    (ConnectorSPI.resolve_subject_sub returned None)."""

    error_code = "LOGIN_NOT_FOUND"


class RemediationTierForbiddenError(ForbiddenError):
    """Attempted remediation at a tier that is out of scope (e.g. tier 3)."""

    error_code = "REMEDIATION_TIER_FORBIDDEN"


class ApprovalRequiredError(ForbiddenError):
    """A tier-2 remediation was attempted without a completed approval."""

    error_code = "APPROVAL_REQUIRED"


class KillSwitchEngagedError(ServiceUnavailableError):
    """The agent-wide or remediation-scoped kill switch is engaged."""

    error_code = "KILL_SWITCH_ENGAGED"


class DiagnosticInconclusiveError(AppError):
    """Raised internally when a check cannot be completed; orchestrator
    catches this and converts it to an INCONCLUSIVE verdict (fail-closed)."""

    status_code = 200
    error_code = "DIAGNOSTIC_INCONCLUSIVE"


class OpenIAMAuthError(ExternalServiceError):
    """OpenIAM token fetch/refresh failed."""

    error_code = "OPENIAM_AUTH_ERROR"


class EmbeddingProviderError(AppError):
    """Configured embedding provider/model is invalid, or its reported
    dimension doesn't match RAG_EMBEDDING_DIMENSION (fail-fast, since a
    silent mismatch would corrupt the pgvector column)."""

    status_code = 500
    error_code = "EMBEDDING_PROVIDER_ERROR"


class UnsupportedFileTypeError(ValidationError):
    """An uploaded document's extension isn't one parsers.py handles."""

    error_code = "UNSUPPORTED_FILE_TYPE"


class FileTooLargeError(PayloadTooLargeError):
    """An uploaded document exceeds RAG_UPLOAD_MAX_BYTES."""

    error_code = "FILE_TOO_LARGE"
