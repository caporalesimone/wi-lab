"""The frontend offers what the antenna supports (HAP-10, HAP-11)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "frontend/src/app"
DIALOG_TS = ROOT / "components/network-form-dialog/network-form-dialog.component.ts"
DIALOG_HTML = ROOT / "components/network-form-dialog/network-form-dialog.component.html"


def test_wpa_is_gone_and_wpa1_comes_only_from_the_antenna():
    dialog = DIALOG_TS.read_text()
    base = re.search(r"const BASE_ENCRYPTIONS = \[(.*?)\];", dialog)
    assert base is not None
    assert "'wpa'" not in base[1] and "'wpa1'" not in base[1]
    assert "this.data.capabilities?.encryptions ?? BASE_ENCRYPTIONS" in dialog


def test_dialog_sends_width_and_generation_from_the_antenna_lists():
    dialog = DIALOG_TS.read_text()
    assert "channel_width: value.channel_width" in dialog
    assert "wifi_generation: value.wifi_generation" in dialog
    assert "this.data.capabilities?.channel_widths[band] ?? [20]" in dialog
    assert "this.data.capabilities?.wifi_generations[band] ?? [4]" in dialog
    html = DIALOG_HTML.read_text()
    assert 'formControlName="channel_width"' in html
    assert 'formControlName="wifi_generation"' in html


def test_card_passes_capabilities_and_shows_the_reported_width():
    card_ts = (ROOT / "components/network-card/network-card.component.ts").read_text()
    assert "capabilities: this.slot.capabilities" in card_ts
    card_html = (ROOT / "components/network-card/network-card.component.html").read_text()
    assert "status?.radio?.channel_width as width" in card_html
    assert "width.reported !== width.requested" in card_html
    assert "capabilities: n.capabilities" in (ROOT / "app.component.ts").read_text()
