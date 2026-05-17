from tools.state import can_transition


def test_valid_forward():
    assert can_transition("new", "triaged")
    assert can_transition("triaged", "enriched")
    assert can_transition("enriched", "mapped")
    assert can_transition("mapped", "contextualized")
    assert can_transition("contextualized", "mitigated")
    assert can_transition("mitigated", "composed")
    assert can_transition("composed", "briefed")
    assert can_transition("briefed", "archived")


def test_invalid():
    # v4: enriched → triaged removed (was pipeline-killing)
    assert not can_transition("enriched", "triaged")
    assert not can_transition("new", "briefed")
    assert not can_transition("archived", "new")
    assert not can_transition("superseded", "new")
    assert not can_transition("briefed", "new")


def test_failure_recovery():
    assert can_transition("failed", "new")
    assert can_transition("failed", "triaged")
    assert can_transition("failed", "enriched")
    assert can_transition("failed", "mapped")
    assert can_transition("failed", "contextualized")
    assert can_transition("failed", "mitigated")
    assert can_transition("failed", "composed")


def test_terminal_states():
    assert not can_transition("archived", "triaged")
    assert not can_transition("superseded", "triaged")


def test_archive_from_new():
    assert can_transition("new", "archived")


def test_supersede_from_new():
    assert can_transition("new", "superseded")
