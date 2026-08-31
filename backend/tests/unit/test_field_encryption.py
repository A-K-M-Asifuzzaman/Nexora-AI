"""Field-level encryption at rest (SECURITY.md §12).

`EncryptedText` is a `TypeDecorator` — it only ever runs at the two edges
SQLAlchemy calls (`process_bind_param` on write, `process_result_value` on
read), so a unit test can drive it directly with no database at all.
"""

import pytest
from cryptography.fernet import Fernet, InvalidToken

from app.core import field_encryption
from tests.unit.test_security import settings_fixture


@pytest.fixture(autouse=True)
def _settings(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = settings_fixture()
    monkeypatch.setattr(field_encryption, "get_settings", lambda: settings)


def test_a_value_round_trips_through_encryption() -> None:
    column = field_encryption.EncryptedText()
    stored = column.process_bind_param("a-totp-secret", dialect=None)
    assert stored is not None
    assert "a-totp-secret" not in stored
    assert column.process_result_value(stored, dialect=None) == "a-totp-secret"


def test_none_passes_through_unchanged() -> None:
    column = field_encryption.EncryptedText()
    assert column.process_bind_param(None, dialect=None) is None
    assert column.process_result_value(None, dialect=None) is None


def test_the_same_plaintext_encrypts_differently_each_time() -> None:
    """Fernet includes a random nonce — two rows with the same secret must not
    be identifiable as such from ciphertext alone."""
    column = field_encryption.EncryptedText()
    first = column.process_bind_param("same-value", dialect=None)
    second = column.process_bind_param("same-value", dialect=None)
    assert first != second


def test_a_value_encrypted_under_a_different_key_cannot_be_decrypted() -> None:
    """The failure mode of a rotated key with no re-encryption pass, or of
    genuine tampering — both must raise, never silently return garbage or an
    empty secret that would make MFA quietly unverifiable."""
    other_key = Fernet.generate_key()
    foreign_ciphertext = Fernet(other_key).encrypt(b"a-totp-secret").decode()

    column = field_encryption.EncryptedText()
    with pytest.raises(ValueError, match="could not be decrypted"):
        column.process_result_value(foreign_ciphertext, dialect=None)


def test_tampered_ciphertext_is_rejected() -> None:
    column = field_encryption.EncryptedText()
    stored = column.process_bind_param("a-totp-secret", dialect=None)
    assert stored is not None
    tampered = stored[:-4] + ("aaaa" if stored[-4:] != "aaaa" else "bbbb")
    with pytest.raises(ValueError):
        column.process_result_value(tampered, dialect=None)


def test_invalid_token_is_the_underlying_cause() -> None:
    other_key = Fernet.generate_key()
    foreign_ciphertext = Fernet(other_key).encrypt(b"x").decode()
    column = field_encryption.EncryptedText()
    with pytest.raises(ValueError) as excinfo:
        column.process_result_value(foreign_ciphertext, dialect=None)
    assert isinstance(excinfo.value.__cause__, InvalidToken)
