"""The lockfile agrees with the requirements that produced it.

A product whose central claim is reproducibility cannot install from unbounded
ranges: two builds a week apart would contain different estimators and stamp the
same engine version on their results. ``requirements.lock`` is what the image and
CI install, with ``--require-hashes``.

What this asserts is narrow on purpose. It does **not** re-resolve, because a
re-resolution fails whenever anything upstream publishes a release, which would
turn a green build red for a reason that has nothing to do with the commit. It
asserts the drift that actually matters: every bound stated in
``requirements.txt`` is satisfied by the version pinned in the lock, and every
pin carries hashes. That is exactly the check that fails when someone raises a
bound and forgets to regenerate.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parent.parent
REQUIREMENTS = BACKEND / "requirements.txt"
LOCK = BACKEND / "requirements.lock"

_PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[^\s\\;]+)")


def _declared() -> list[Requirement]:
    out = []
    for raw in REQUIREMENTS.read_text(encoding="utf-8").splitlines():
        line = raw.split("#", 1)[0].strip()
        if line:
            out.append(Requirement(line))
    return out


def _pinned() -> dict[str, tuple[str, int]]:
    """Canonical name -> (version, number of hashes)."""

    pins: dict[str, tuple[str, int]] = {}
    current: str | None = None
    for raw in LOCK.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("#") or not line:
            continue
        match = _PIN.match(line)
        if match:
            current = canonicalize_name(match.group("name"))
            pins[current] = (match.group("version"), 0)
        elif line.startswith("--hash=") and current is not None:
            version, count = pins[current]
            pins[current] = (version, count + 1)
    return pins


def test_the_lockfile_exists_and_pins_versions():
    pins = _pinned()
    # A sanity floor rather than an exact count, which would need editing on
    # every transitive change without telling anyone anything.
    assert len(pins) > 40
    assert all("==" not in version for version, _ in pins.values())


def test_every_declared_requirement_is_pinned_and_satisfied():
    pins = _pinned()
    missing = []
    unsatisfied = []

    for requirement in _declared():
        name = canonicalize_name(requirement.name)
        if name not in pins:
            missing.append(requirement.name)
            continue
        version, _ = pins[name]
        if not requirement.specifier.contains(version, prereleases=True):
            unsatisfied.append(f"{requirement.name}: lock has {version}, wants {requirement.specifier}")

    assert not missing, (
        f"declared in requirements.txt but absent from requirements.lock: {missing}. "
        "Regenerate the lock — the command is in its header."
    )
    assert not unsatisfied, (
        "requirements.lock pins a version that does not satisfy requirements.txt: "
        f"{unsatisfied}. Regenerate the lock."
    )


def test_every_pin_carries_hashes():
    """``--require-hashes`` is only as good as the file's coverage.

    One unhashed line makes pip reject the whole install, so a lock missing
    hashes fails the build rather than weakening it — but it fails it in Docker,
    minutes later, with a message about a different package. Better here.
    """

    unhashed = [name for name, (_, count) in _pinned().items() if count == 0]
    assert not unhashed, f"pinned without hashes: {unhashed}"


@pytest.mark.parametrize(
    "package",
    ["fastapi", "sqlalchemy", "numpy", "scipy", "pandas", "boto3", "rq", "alembic"],
)
def test_the_load_bearing_dependencies_are_present(package):
    # Named individually because the resolver silently dropping one of these —
    # through an extra that stopped implying it, say — would leave a lock that
    # installs cleanly and cannot run the application.
    assert canonicalize_name(package) in _pinned()
