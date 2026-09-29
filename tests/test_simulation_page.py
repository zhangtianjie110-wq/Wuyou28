from app.ui.simulation_page import _selection_text


def test_selection_text_preserves_backtest_string():
    assert _selection_text("大单、大双") == "大单、大双"


def test_selection_text_formats_sequence_for_compatibility():
    assert _selection_text(("大单", "大双")) == "大单、大双"
