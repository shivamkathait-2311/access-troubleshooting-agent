from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application settings with environment-specific configuration."""

    # ==================== Environment ====================
    ENV: str = "development"
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # ==================== API ====================
    PROJECT_NAME: str = "Access Troubleshooting Agent"
    VERSION: str = "0.1.0"
    DESCRIPTION: str = "Generic, system-agnostic access/login/permission diagnostic agent"

    # ==================== Server ====================
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # ==================== CORS ====================
    CORS_ORIGINS: list[str] = ["http://localhost:3000"]
    CORS_ALLOW_CREDENTIALS: bool = True
    CORS_ALLOW_METHODS: list[str] = ["*"]
    CORS_ALLOW_HEADERS: list[str] = ["*"]

    # ==================== Database ====================
    # Ports 5433/6380 match docker-compose.yml's host-port remap (done to
    # avoid clashing with other local Postgres/Redis instances).
    DATABASE_URL: str = (
        "postgresql+asyncpg://ata_user:ata_password@localhost:5433/ata_db"
    )
    DATABASE_POOL_SIZE: int = 5
    DATABASE_MAX_OVERFLOW: int = 10
    DATABASE_ECHO: bool = False
    AUDIT_DB_SCHEMA: str = "audit"

    # ==================== Redis ====================
    REDIS_URL: str = "redis://localhost:6380/0"

    # ==================== Vault (secrets) ====================
    VAULT_ADDR: str = "http://localhost:8200"
    VAULT_ROLE: str = "access-troubleshooting-agent"

    # ==================== LLM ====================
    # Both LLM call sites (app/llm/intake_parser.py, app/llm/explanation.py)
    # are single-shot, zero-tool-authority calls — see app/llm/client.py.
    OPENAI_API_KEY: str = ""
    OPENAI_INTAKE_MODEL: str = "gpt-4o-mini"
    OPENAI_EXPLANATION_MODEL: str = "gpt-4o-mini"

    # ==================== Policy store ====================
    POLICY_DIR: str = "app/policy/policies"

    # ==================== Intake surfaces ====================
    SLACK_BOT_TOKEN: str = ""
    SLACK_SIGNING_SECRET: str = ""
    TEAMS_APP_ID: str = ""
    TEAMS_APP_SECRET: str = ""

    # ==================== Audit / SIEM ====================
    SIEM_ENDPOINT: str = ""

    # ==================== OpenIAM ====================
    # Admin credential exchanged for an access token via the real staging
    # flow (see app/connectors/openiam/token_client.py): POST
    # /idp/rest/api/auth/public/login -> authToken, then GET
    # /idp/oauth2/authorize (bearer authToken) -> 302 with access_token in
    # the redirect fragment. Not a user's credential — a single service
    # identity used by OpenIAMConnector.
    OPENIAM_BASE_URL: str = ""
    OPENIAM_CLIENT_ID: str = ""
    OPENIAM_CLIENT_SECRET: str = ""
    OPENIAM_ADMIN_USERNAME: str = ""
    OPENIAM_ADMIN_PASSWORD: str = ""
    OPENIAM_REDIRECT_URI: str = ""
    OPENIAM_OAUTH_RESPONSE_TYPE: str = "token"
    OPENIAM_TOKEN_REFRESH_MARGIN_SECONDS: int = 60
    # Self-service "forgot password" link template — {base_url} and {login}
    # get substituted in by OpenIAMConnector.get_user_status(). See
    # app/connectors/openiam/connector.py::_build_password_reset_url.
    OPENIAM_PASSWORD_RESET_URL_TEMPLATE: str = (
        "{base_url}/idp/auth-select?reqAuthTypes=PASSWORD_AUTH,PUSH_AUTH,CERT_AUTH,SMS_AUTH,"
        "VOICE_AUTH,CHALLENGE_RESPONSE_AUTH,DUO_AUTH,TOTP_AUTH,CRIIPTO_AUTH,KERB_AUTH,WEB_AUTH,"
        "EMAIL_AUTH&login={login}&postbackUrl=%2Fidp%2FresetPasswordForm%3Flogin%3D{login}"
    )

    # ==================== Diagnostic funnel ====================
    # How far back step 3 (auth events) looks for the subject's most recent
    # login attempt. See app/orchestrator/steps/step3_auth_events.py.
    DIAGNOSTIC_AUTH_EVENTS_LOOKBACK_HOURS: int = 24
    # Used only when the caller omits ComplaintIntake.system_id — a
    # convenience for today's single-system reality, not a permanent
    # hardcode. See app/services/intake_service.py.
    DEFAULT_SYSTEM_ID: str = "openiam"

    # ==================== Kill switch ====================
    # Agent-wide switch halts all diagnostic runs; remediation switch halts
    # only remediation while diagnostics keep running. See app/core/killswitch.py
    # and app/remediation/killswitch.py.
    AGENT_KILL_SWITCH_ENABLED: bool = False
    REMEDIATION_KILL_SWITCH_ENABLED: bool = False

    # ==================== Observability ====================
    ENABLE_METRICS: bool = True

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    """Return a cached Settings instance."""
    return Settings()


settings = get_settings()
