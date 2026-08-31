import pytest
from fastapi.testclient import TestClient

from tests.unit.test_security import settings_fixture


def configure_required_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_fixture()
    monkeypatch.setenv("JWT_SECRET_KEY", settings.jwt_secret_key.get_secret_value())
    monkeypatch.setenv("FIELD_ENCRYPTION_KEY", settings.field_encryption_key.get_secret_value())
    monkeypatch.setenv("DATABASE_URL", settings.database_url)
    monkeypatch.setenv("DATABASE_URL_SYNC", settings.database_url_sync)
    monkeypatch.setenv("DATABASE_OWNER_URL", settings.database_owner_url)
    monkeypatch.setenv("REDIS_URL", settings.redis_url.get_secret_value())
    monkeypatch.setenv("CELERY_BROKER_URL", settings.celery_broker_url.get_secret_value())
    monkeypatch.setenv("CELERY_RESULT_BACKEND", settings.celery_result_backend.get_secret_value())


def test_application_starts_and_health_endpoint_responds(monkeypatch: pytest.MonkeyPatch) -> None:
    configure_required_environment(monkeypatch)
    from app.main import create_app

    app = create_app(settings_fixture())
    with TestClient(app) as client:
        response = client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_every_business_operation_declares_bearer_authentication(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_required_environment(monkeypatch)
    from app.main import create_app

    # `.openapi()` needs no request and no lifespan, but `create_app()` still
    # opens a real async engine and a real Redis client (`app.state.engine`,
    # `app.state.redis`) against the placeholder `settings_fixture()` DSNs.
    # Without a `with TestClient(...)` the lifespan never runs, so nothing
    # ever disposes them — a leaked engine bound to nonsense credentials,
    # observed to corrupt an unrelated, later test's real database connection
    # when this file runs before `tests/integration` in the same process.
    app = create_app(settings_fixture())
    with TestClient(app):
        schema = app.openapi()
    # Every entry is an operation that MUST be reachable without a token, with the
    # reason it is safe. Adding to this set is a security decision — it should be
    # rare, and each line should survive review on its own.
    public_operations = {
        ("/health", "get"),  # liveness, no dependencies, no data
        ("/ready", "get"),  # readiness, no data
        ("/metrics", "get"),  # network-restricted in production
        # A token cannot be obtained without these three; they are the entry point.
        # Each is rate limited (API.md §9) and returns a uniform response so it
        # cannot be used to enumerate accounts (SECURITY.md §2).
        ("/api/v1/auth/register", "post"),
        ("/api/v1/auth/login", "post"),
        # Authenticated by the httpOnly refresh cookie rather than a bearer token,
        # with rotation and reuse detection (ADR-0006).
        ("/api/v1/auth/refresh", "post"),
        # Recovery flows: reachable without a token by definition — a user who
        # cannot sign in is exactly who needs them. Each is rate limited and
        # answers uniformly so it cannot confirm an address exists.
        ("/api/v1/auth/resend-verification", "post"),
        ("/api/v1/auth/verify-email", "post"),
        ("/api/v1/auth/forgot-password", "post"),
        ("/api/v1/auth/reset-password", "post"),
        # Redeemed by someone who has no account and no tenant yet; the bearer
        # token is the authorization (migration 0011).
        ("/api/v1/invitations/accept", "post"),
        # Runs before a session exists — authenticated by possessing the
        # short-lived, rate-limited challenge token `/auth/login` issued, not
        # by a bearer token (SECURITY.md §12, Phase 11 MFA).
        ("/api/v1/auth/mfa/challenge", "post"),
    }
    offenders: list[str] = []
    for path, path_item in schema["paths"].items():
        for method, operation in path_item.items():
            if method not in {"get", "post", "patch", "put", "delete"}:
                continue
            if (path, method) in public_operations:
                continue
            security = operation.get("security", [])
            if not any("HTTPBearer" in requirement for requirement in security):
                offenders.append(f"{method.upper()} {path}")
    assert not offenders, "Business routes missing bearer auth: " + ", ".join(offenders)


def test_every_protected_operation_rejects_anonymous_requests(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_required_environment(monkeypatch)
    from app.main import create_app

    app = create_app(settings_fixture())
    public = {
        ("/health", "get"),
        ("/ready", "get"),
        ("/metrics", "get"),
        ("/api/v1/auth/register", "post"),
        ("/api/v1/auth/login", "post"),
        ("/api/v1/auth/refresh", "post"),
        # Recovery flows: reachable without a token by definition — a user who
        # cannot sign in is exactly who needs them. Each is rate limited and
        # answers uniformly so it cannot confirm an address exists.
        ("/api/v1/auth/resend-verification", "post"),
        ("/api/v1/auth/verify-email", "post"),
        ("/api/v1/auth/forgot-password", "post"),
        ("/api/v1/auth/reset-password", "post"),
        # Redeemed by someone who has no account and no tenant yet; the bearer
        # token is the authorization (migration 0011).
        ("/api/v1/invitations/accept", "post"),
        ("/api/v1/auth/mfa/challenge", "post"),
    }
    schema = app.openapi()
    offenders: list[str] = []
    with TestClient(app) as client:
        for path, path_item in schema["paths"].items():
            request_path = path.replace("{branch_id}", "00000000-0000-0000-0000-000000000001")
            request_path = request_path.replace(
                "{membership_id}", "00000000-0000-0000-0000-000000000001"
            ).replace("{role_id}", "00000000-0000-0000-0000-000000000001")
            request_path = request_path.replace(
                "{warehouse_id}", "00000000-0000-0000-0000-000000000001"
            )
            for method in {"get", "post", "patch", "put", "delete"} & path_item.keys():
                if (path, method) in public:
                    continue
                response = client.request(method, request_path)
                if response.status_code != 401:
                    offenders.append(f"{method.upper()} {path} -> {response.status_code}")
    assert not offenders, "Protected operations accepted anonymous requests: " + ", ".join(
        offenders
    )
