"""Password hashing.

Argon2id, via argon2-cffi. The choice matters more than the parameters: it is
memory-hard, so an attacker with the dumped ``users`` table cannot trade GPUs for
speed the way they can against bcrypt-with-low-cost or any SHA family.

Two behaviours worth naming:

* ``verify_password`` returns ``False`` for a malformed or empty stored hash
  instead of raising, so a corrupt row is a failed login rather than a 500 that
  distinguishes it from a wrong password.
* ``needs_rehash`` exists so that raising the cost parameters later upgrades
  accounts on their next successful login, rather than requiring a reset email.

Nothing in this module logs its arguments, and callers must not either.
"""

from __future__ import annotations

from argon2 import PasswordHasher as _Argon2Hasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

# argon2-cffi's defaults track the RFC 9106 second recommended option
# (memory-heavy). Named explicitly so a future change is a visible diff.
PasswordHasher = _Argon2Hasher

_hasher = _Argon2Hasher(
    time_cost=3,
    memory_cost=64 * 1024,  # 64 MiB
    parallelism=4,
    hash_len=32,
    salt_len=16,
)

# A lower bound only. Composition rules push users toward predictable
# substitutions; length is the property that actually helps.
MIN_PASSWORD_LENGTH = 12
MAX_PASSWORD_LENGTH = 1024


def hash_password(password: str) -> str:
    if not MIN_PASSWORD_LENGTH <= len(password) <= MAX_PASSWORD_LENGTH:
        # The upper bound is a denial-of-service guard: hashing is deliberately
        # expensive, so an unbounded input is an unbounded amount of work.
        raise ValueError(
            f"password must be between {MIN_PASSWORD_LENGTH} and "
            f"{MAX_PASSWORD_LENGTH} characters"
        )
    return _hasher.hash(password)


def verify_password(password: str, stored_hash: str) -> bool:
    """Constant-time verification; ``False`` for any failure mode."""

    if not stored_hash or len(password) > MAX_PASSWORD_LENGTH:
        return False
    try:
        return _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return True
