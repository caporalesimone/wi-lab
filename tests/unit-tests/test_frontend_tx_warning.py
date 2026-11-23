from html.parser import HTMLParser
from pathlib import Path


class WarningParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_note = False
        self.note = ""
        self.tooltip = ""

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "p" and attrs.get("class") == "tx-power-note":
            self.in_note = True
        if tag == "div" and "tx_power?.requested_level" in attrs.get("*ngif", ""):
            self.tooltip = attrs.get("mattooltip", "")

    def handle_endtag(self, tag):
        if tag == "p":
            self.in_note = False

    def handle_data(self, data):
        if self.in_note:
            self.note += data


def test_tx_power_warnings_describe_hardware_and_reported_values():
    root = Path(__file__).resolve().parents[2] / "frontend/src/app/components"
    parser = WarningParser()
    parser.feed((root / "network-form-dialog/network-form-dialog.component.html").read_text())
    parser.feed((root / "network-card/network-card.component.html").read_text())
    assert "depends on the adapter" in parser.note
    assert "does not guarantee the actual transmitted power" in parser.note
    assert "driver" in parser.tooltip
    assert "does not guarantee actual transmitted power" in parser.tooltip
