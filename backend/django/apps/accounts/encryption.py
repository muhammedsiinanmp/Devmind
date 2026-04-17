import base64

from cryptography.fernet import Fernet
from cryptography.hazmat.primitives.hashes import SHA256
from cryptography.hazmat.primitives.kdf.hkdf import HKDF
from django.conf import settings
from django.db import models

# Fixed salt for key derivation. In production, store this in an env var.
# Changing this value will invalidate ALL previously encrypted data.

_HKDF_SALT = b"devmind-github-token-encryption-v1"


def _get_fernet():
    """
    Derive a Fernet key from Django's SECRET_KEY using HKDF.
    HKDF is the cryptographically correct way to derive an encryption
    key from a master secret. Unlike a raw SHA-256 hash, HKDF uses a
    salt and an info context string, making it resistant to related-key
    attacks and suitable for key derivation per NIST SP 800-56C.
    """
    hkdf = HKDF(
        algorithm=SHA256(),
        length=32,
        salt=_HKDF_SALT,
        info=b"fernet-encryption-key",
    )
    derived_key = hkdf.derive(settings.SECRET_KEY.encode())
    return Fernet(base64.urlsafe_b64encode(derived_key))


class EncryptedCharField(models.CharField):
    """
    CharField that encrypts values at rest using Fernet symmetric encryption.
    Usage:
        access_token = EncryptedCharField(max_length=500)
    The value is transparently encrypted on save and decrypted on read.
    Raw database value will be a Fernet token (base64), NOT the plaintext.
    """

    def get_prep_value(self, value):
        """Encrypt before saving to database."""
        if value is None or value == "":
            return value
        f = _get_fernet()
        return f.encrypt(value.encode()).decode()

    def from_db_value(self, value, expression, connection):
        """Decrypt after reading from database."""
        if value is None or value == "":
            return value
        f = _get_fernet()
        return f.decrypt(value.encode()).decode()
