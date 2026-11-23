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


def test_start_dialog_has_a_captive_portal_toggle_preset_by_the_card():
    toggles = _toggles("network-form-dialog/network-form-dialog.component.html")
    assert [t.get("formcontrolname") for t in toggles] == ["captive_portal"]
    dialog = (ROOT / "network-form-dialog/network-form-dialog.component.ts").read_text()
    assert "captive_portal: [this.data.captivePortal ?? false]" in dialog
    assert "captive_portal: value.captive_portal" in dialog


def test_card_chooses_before_start_and_shows_the_state_when_running():
    toggles = _toggles("network-card/network-card.component.html")
    assert len(toggles) == 1 and toggles[0].get("[checked]") == "captivePortalChoice"
    card_html = (ROOT / "network-card/network-card.component.html").read_text()
    assert "status?.captive_portal ? 'On' : 'Off'" in card_html
    assert "internet-status-badge captive" in card_html
    card_ts = (ROOT / "network-card/network-card.component.ts").read_text()
    assert "captivePortal: this.captivePortalChoice" in card_ts
