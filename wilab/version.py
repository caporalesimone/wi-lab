from pathlib import Path


def _read_version() -> str:
	root = Path(__file__).resolve().parent.parent
	version_file = root / "VERSION"
	if version_file.exists():
		return version_file.read_text(encoding="utf-8").strip()
	return "0.0.0-dev"


__version__ = _read_version()
