"""STAB-7: requirements.lock pins every dependency of requirements.txt to one exact version."""

from pathlib import Path

from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

ROOT = Path(__file__).resolve().parents[2]


def _lines(name: str) -> list[str]:
    text = (ROOT / name).read_text()
    return [line.strip() for line in text.splitlines() if line.strip() and not line.startswith("#")]


def _locked() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _lines("requirements.lock"):
        name, sep, version = line.partition("==")
        assert sep and version, f"not an exact pin: {line}"
        pins[canonicalize_name(name)] = version
    return pins


def test_every_direct_dependency_is_pinned_within_its_range():
    pins = _locked()
    for line in _lines("requirements.txt"):
        req = Requirement(line)
        name = canonicalize_name(req.name)
        assert name in pins, f"{req.name} missing from requirements.lock"
        assert req.specifier.contains(pins[name], prereleases=True), f"{req.name}=={pins[name]} outside {req.specifier}"


def test_installers_use_the_lock():
    assert "requirements.lock" in (ROOT / "install/02-install-stages/01-venv.sh").read_text()
    assert "-r requirements.lock" in (ROOT / "requirements-dev.txt").read_text()
    assert "install -r requirements.lock" in (ROOT / "Makefile").read_text()
