"""The frontend lets the user choose the captive portal and shows its state."""

from html.parser import HTMLParser
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "frontend/src/app/components"


class ToggleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.toggles: list[dict[str, str | None]] = []

    def handle_starttag(self, tag, attrs):
        if tag == "mat-slide-toggle":
            self.toggles.append(dict(attrs))


def _toggles(name: str) -> list[dict[str, str | None]]:
    parser = ToggleParser()
    parser.feed((ROOT / name).read_text())
    return parser.toggles


def test_start_dialog_has_the_captive_portal_toggle():
    toggles = _toggles("network-form-dialog/network-form-dialog.component.html")
    assert [t.get("formcontrolname") for t in toggles] == ["captive_portal"]
    dialog = (ROOT / "network-form-dialog/network-form-dialog.component.ts").read_text()
    assert "captive_portal: [false]" in dialog
    assert "captive_portal: { enabled: value.captive_portal }" in dialog


def test_card_only_shows_the_state_the_choice_is_in_the_dialog():
    """2026-11-27: the card had a second toggle; the start dialog is the only place to choose."""
    assert _toggles("network-card/network-card.component.html") == []
    card_html = (ROOT / "network-card/network-card.component.html").read_text()
    assert "status?.captive_portal?.enabled ? 'On' : 'Off'" in card_html
    assert "internet-status-badge captive" in card_html
    card_ts = (ROOT / "network-card/network-card.component.ts").read_text()
    assert "captivePortalChoice" not in card_ts
