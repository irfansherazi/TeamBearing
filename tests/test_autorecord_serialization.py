from backend.engine.autorecord import _maybe_portal_serialize, _normalize_portal_class, autorecord_serializer


def test_serialize_keyup_merge():
    """Verify multiple keyup events on same field are merged into one fill."""
    raw = [
        {"event_type": "keyup", "best_selector": "input#name", "strategy": "css", "value": "J", "inner_text": ""},
        {"event_type": "keyup", "best_selector": "input#name", "strategy": "css", "value": "Jo", "inner_text": ""},
        {"event_type": "keyup", "best_selector": "input#name", "strategy": "css", "value": "Joe", "inner_text": ""},
    ]

    clean = autorecord_serializer.serialize(raw)

    assert len(clean) == 1
    assert clean[0]["action"] == "fill"
    assert clean[0]["name"] == "input#name"
    assert clean[0]["value"] == "Joe"


def test_serialize_click_fill_dedup():
    """Verify click immediately followed by fill on same selector is removed."""
    raw = [
        {"event_type": "click", "best_selector": "input#name", "strategy": "css", "inner_text": ""},
        {"event_type": "keyup", "best_selector": "input#name", "strategy": "css", "value": "Joe", "inner_text": ""},
    ]

    clean = autorecord_serializer.serialize(raw)

    assert len(clean) == 1
    assert clean[0]["action"] == "fill"
    assert clean[0]["name"] == "input#name"


def test_serialize_mixed_events():
    """Verify complex sequence of clicks, scrolls, and typing."""
    raw = [
        {"event_type": "scroll", "value": "0,100"},
        {"event_type": "click", "best_selector": "Button 1", "strategy": "get_by_text", "inner_text": "Button 1"},
        {"event_type": "keyup", "best_selector": "input#name", "strategy": "css", "value": "Joe", "inner_text": ""},
        {
            "event_type": "change",
            "best_selector": "input#name",
            "strategy": "css",
            "value": "Joe Smith",
            "inner_text": "",
        },
        {"event_type": "click", "best_selector": "Submit", "strategy": "get_by_text", "inner_text": "Submit"},
    ]

    clean = autorecord_serializer.serialize(raw)

    # Expected: scroll, click(Button 1), fill(Joe Smith), click(Submit)
    assert len(clean) == 4
    assert clean[0]["action"] == "scroll"
    assert clean[1]["action"] == "click"
    assert clean[1]["name"] == "Button 1"
    assert clean[2]["action"] == "fill"
    assert clean[2]["name"] == "input#name"
    assert clean[2]["value"] == "Joe Smith"
    assert clean[3]["action"] == "click"
    assert clean[3]["name"] == "Submit"


def test_serialize_empty():
    assert autorecord_serializer.serialize([]) == []
    assert autorecord_serializer.serialize(None) == []


# ---------------------------------------------------------------------------
# Phase 1 portal-field tests (hitl-portal-aware-click-capture)
# ---------------------------------------------------------------------------

def _portal_click_rec(**overrides):
    """Build a portal click record with sensible defaults."""
    base = {
        "event_type": "click",
        "best_selector": "Option A",
        "strategy": "get_by_role:option",
        "inner_text": "Option A",
        "css_path": "html > body > div.p-select-overlay > ul > li",
        "aria_label": "",
        "portal_class": ".p-select-overlay",
        "trigger_selector": "th.col p-select",
        "target_text": "Option A",
        "trigger_resolution_confidence": "aria",
        "is_anonymous_portal": False,
        "capture_confidence": "full",
    }
    base.update(overrides)
    return base


def test_normalize_portal_class_prepends_dot():
    """_normalize_portal_class adds missing leading dot."""
    assert _normalize_portal_class("p-select-overlay") == ".p-select-overlay"
    assert _normalize_portal_class(".p-select-overlay") == ".p-select-overlay"
    assert _normalize_portal_class("po-sorting-dropdown-panel") == ".po-sorting-dropdown-panel"
    assert _normalize_portal_class("") == ""


def test_unrecognized_portal_class_prefix_falls_through():
    """portal_class with unrecognized prefix → _maybe_portal_serialize returns None."""
    rec = _portal_click_rec(portal_class=".custom-overlay", capture_confidence="full")
    assert _maybe_portal_serialize(rec) is None


def test_serialize_non_portal_click_byte_identical():
    """Non-portal click → byte-identical to pre-feature output (AC-VERIFY-5)."""
    raw = [{"event_type": "click", "best_selector": "Submit", "strategy": "get_by_text", "inner_text": "Submit"}]
    result = autorecord_serializer.serialize(raw)
    assert result == [{"action": "click", "strategy": "get_by_text", "name": "Submit", "inner_text": "Submit"}]
    assert "_capture_confidence" not in result[0]


def test_serialize_full_portal_capture_emits_primeng_dropdown():
    """Full portal capture → primeng_dropdown action with all portal fields."""
    raw = [_portal_click_rec(
        portal_class=".p-select-overlay",
        trigger_selector="th.col p-select",
        target_text="Due Date A-Z",
        capture_confidence="full",
    )]
    result = autorecord_serializer.serialize(raw)
    assert len(result) == 1
    assert result[0]["action"] == "primeng_dropdown"
    assert result[0]["trigger_selector"] == "th.col p-select"
    assert result[0]["target_text"] == "Due Date A-Z"
    assert result[0]["portal_class"] == ".p-select-overlay"
    assert result[0]["_capture_confidence"] == "full"
    assert "inner_text" in result[0]


def test_serialize_portal_only_uses_container_selector():
    """portal_only → action=click with container_selector."""
    raw = [_portal_click_rec(
        trigger_selector="",
        capture_confidence="portal_only",
        target_text="Option A",
    )]
    result = autorecord_serializer.serialize(raw)
    assert result[0]["action"] == "click"
    assert result[0]["container_selector"] == ".p-select-overlay"
    assert result[0]["strategy"] == "get_by_text"
    assert result[0]["_capture_confidence"] == "portal_only"


def test_serialize_portal_only_empty_target_falls_back_to_css_path():
    """portal_only with no text → css_selector with css_path as name."""
    raw = [_portal_click_rec(
        target_text="",
        inner_text="",
        aria_label="",
        css_path="html > body > div.p-select-overlay > ul > li:nth-child(1)",
        capture_confidence="portal_only",
    )]
    result = autorecord_serializer.serialize(raw)
    assert result[0]["_capture_confidence"] == "portal_only_degraded"
    assert result[0]["strategy"] == "css_selector"
    assert "p-select-overlay" in result[0]["name"]
