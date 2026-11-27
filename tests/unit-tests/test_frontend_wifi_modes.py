"""The frontend offers what the antenna supports (HAP-10, HAP-11)."""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2] / "frontend/src/app"
DIALOG_TS = ROOT / "components/network-form-dialog/network-form-dialog.component.ts"
DIALOG_HTML = ROOT / "components/network-form-dialog/network-form-dialog.component.html"


def test_encryptions_come_only_from_the_antenna():
    dialog = DIALOG_TS.read_text()
    assert "BASE_ENCRYPTIONS" not in dialog and "'wpa'" not in dialog
    assert "this.data.antenna.encryptions.filter(" in dialog


def test_dialog_lists_come_from_the_antennas_api():
    """Band, generation, width and channel are dropdowns filled from GET /antennas/{interface}/capabilities."""
    dialog = DIALOG_TS.read_text()
    assert "channel_width: value.channel_width" in dialog
    assert "wifi_generation: value.wifi_generation" in dialog
    assert "this.bandOptions.wifi_generations.map(g => g.wifi_generation)" in dialog
    assert "this.bandOptions.channels.filter(c => c.channel_widths.includes(width))" in dialog
    html = DIALOG_HTML.read_text()
    for control in ("channel", "channel_width", "wifi_generation"):
        assert re.search(rf'<mat-select formControlName="{control}"', html), control
    assert 'type="number" formControlName="channel"' not in html


def test_card_reads_the_capabilities_before_opening_the_form():
    card_ts = (ROOT / "components/network-card/network-card.component.ts").read_text()
    assert "this.wilabApiService.getCapabilities(this.slot.interface)" in card_ts
    assert "data: { netId: reservationId, antenna }" in card_ts
    service = (ROOT / "services/wilab-api.service.ts").read_text()
    assert "/antennas/${encodeURIComponent(iface)}/capabilities" in service
    card_html = (ROOT / "components/network-card/network-card.component.html").read_text()
    assert "status?.radio?.channel_width as width" in card_html
    assert "width.reported !== width.requested" in card_html
    assert "capabilities" not in (ROOT / "app.component.ts").read_text()


def test_card_shows_fallback_and_ht_vht_capab_and_the_dialog_sets_them():
    card_html = (ROOT / "components/network-card/network-card.component.html").read_text()
    assert "status?.radio?.enable_generation_fallback" in card_html
    assert "status?.radio?.enable_ht_vht_capab" in card_html
    assert "short guard interval, LDPC, STBC" in card_html          # the hover explanation
    dialog_ts = DIALOG_TS.read_text()
    assert "enable_ht_vht_capab: [true]" in dialog_ts and "enable_ht_vht_capab: value.enable_ht_vht_capab" in dialog_ts
    assert 'formControlName="enable_ht_vht_capab"' in DIALOG_HTML.read_text()
