"""Field-level encryption at rest (SECURITY.md §12 evaluation).

A DB compromise (a stolen backup, a leaked credential for `nexora_owner`)
should not hand over every secret in the database in plaintext — RLS and
`app`'s non-owner role protect against the application misbehaving, not
against someone reading the table directly. This wraps a column so its
on-disk value is Fernet-encrypted and only ever plaintext in process memory,
transparently to every query that touches it.

Scope, deliberately narrow: applied to `MfaCredential.secret_encrypted` (a
TOTP seed is a bearer secret — anyone who reads it can generate valid codes
forever) and nowhere else yet. Extending it to other columns is a per-field
decision, not a blanket policy; most of this schema's sensitive data
(passwords, refresh tokens) is already one-way hashed, which encryption
would not improve on since nothing ever needs it back in plaintext.
"""

from cryptography.fernet import Fernet, InvalidToken
from sqlalchemy.types import Text, TypeDecorator

from app.core.config import get_settings


def _fernet() -> Fernet:
    return Fernet(get_settings().field_encryption_key.get_secret_value().encode())


class EncryptedText(TypeDecorator[str]):
    """A `Text` column, encrypted at rest. Never queryable/filterable by value —
    the same ciphertext for the same plaintext only if Fernet's own nonce
    happens to collide, which by design it does not."""

    impl = Text
    cache_ok = True

    def process_bind_param(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        return _fernet().encrypt(value.encode()).decode()

    def process_result_value(self, value: str | None, dialect: object) -> str | None:
        if value is None:
            return None
        try:
            return _fernet().decrypt(value.encode()).decode()
        except InvalidToken as error:
            # A key rotation with no re-encryption pass, or genuine tampering.
            # Either way the caller must not silently treat this as "no secret".
            raise ValueError(
                "Encrypted field could not be decrypted with the current key"
            ) from error
