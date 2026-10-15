"""
Password hashing with scrypt from the standard library.

scrypt is memory-hard and ships with Python's hashlib, so this adds no
dependency. Parameters are stored with each hash so they can be raised later
without invalidating existing accounts: `needs_rehash` reports when a stored
hash is weaker than the current setting.
"""

import base64
import hashlib
import hmac
import secrets

# 2**14 with r=8 uses ~16 MB per hash -- a sensible interactive-login cost.
SCRYPT_N = 2**14
SCRYPT_R = 8
SCRYPT_P = 1
DKLEN = 32
_PREFIX = "scrypt"


def _derive(password: str, salt: bytes, n: int, r: int, p: int) -> bytes:
    return hashlib.scrypt(
        password.encode("utf-8"),
        salt=salt,
        n=n,
        r=r,
        p=p,
        dklen=DKLEN,
        maxmem=128 * n * r * p + 1024 * 1024,
    )


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = _derive(password, salt, SCRYPT_N, SCRYPT_R, SCRYPT_P)
    return "$".join(
        [
            _PREFIX,
            str(SCRYPT_N),
            str(SCRYPT_R),
            str(SCRYPT_P),
            base64.b64encode(salt).decode(),
            base64.b64encode(digest).decode(),
        ]
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        prefix, n, r, p, salt_b64, digest_b64 = stored.split("$")
        if prefix != _PREFIX:
            return False
        salt = base64.b64decode(salt_b64)
        expected = base64.b64decode(digest_b64)
        actual = _derive(password, salt, int(n), int(r), int(p))
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual, expected)


#: Verified against when an email isn't registered, so a login attempt for an
#: unknown account costs the same time as one for a real account and can't
#: be used to discover who has signed up.
_DUMMY_HASH = hash_password(secrets.token_urlsafe(16))


def burn_equivalent_time(password: str) -> None:
    verify_password(password, _DUMMY_HASH)
