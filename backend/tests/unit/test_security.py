from uuid import uuid4

import jwt

from app.core.config import Settings
from app.core.security import SecurityService, generate_opaque_token, hash_opaque_token


def settings_fixture() -> Settings:
    from cryptography.fernet import Fernet

    return Settings(
        jwt_secret_key="x" * 32,
        field_encryption_key=Fernet.generate_key().decode(),
        database_url="postgresql+asyncpg://user:pass@localhost/nexora",
        database_url_sync="postgresql+psycopg://user:pass@localhost/nexora",
        database_owner_url="postgresql+psycopg://owner:pass@localhost/nexora",
        redis_url="redis://localhost/0",
        celery_broker_url="redis://localhost/1",
        celery_result_backend="redis://localhost/2",
    )


def test_argon2id_hashes_and_verifies_without_plaintext() -> None:
    service = SecurityService(settings_fixture())
    password = "correct horse battery staple"  # noqa: S105 -- test fixture
    password_hash = service.hash_password(password)

    assert password not in password_hash
    assert password_hash.startswith("$argon2id$")
    assert service.verify_password(password_hash, password)
    assert not service.verify_password(password_hash, "incorrect password")


def test_access_token_contains_only_identity_session_and_tenant_claims() -> None:
    service = SecurityService(settings_fixture())
    user_id, session_id, tenant_id = uuid4(), uuid4(), uuid4()
    token = service.create_access_token(user_id, session_id, tenant_id)
    payload = jwt.decode(token, "x" * 32, algorithms=["HS256"])

    assert payload["sub"] == str(user_id)
    assert payload["sid"] == str(session_id)
    assert payload["tid"] == str(tenant_id)
    assert set(payload) == {"sub", "sid", "tid", "iat", "exp"}


def test_opaque_tokens_are_random_and_only_hash_is_persistable() -> None:
    first, second = generate_opaque_token(), generate_opaque_token()
    assert first != second
    assert len(hash_opaque_token(first)) == 64
    assert first not in hash_opaque_token(first)
