"""Deep-research plan + status extractors."""

from __future__ import annotations

from aitunnel._protocol.research import (
    extract_deep_research_plan,
    extract_deep_research_status,
)


def test_plan_extraction() -> None:
    candidate = {
        "57": [
            "Investigate widgets",
            [
                ["_", "Step 1", "do thing one"],
                ["_", "Step 2", "do thing two"],
            ],
            "~5 minutes",
            ["Start it"],
            ["https://confirm.example/abc"],
            ["modify like so"],
        ],
        "70": 2,
        "99": "abc-12345678-1234-1234-1234-123456789012-trailing",
    }
    plan = extract_deep_research_plan(candidate)
    assert plan is not None
    assert plan.title == "Investigate widgets"
    assert plan.query == "do thing one"
    assert len(plan.steps) == 2
    assert "Step 1" in plan.steps[0]
    assert plan.eta_text == "~5 minutes"
    assert plan.confirm_prompt == "Start it"
    assert plan.confirmation_url == "https://confirm.example/abc"
    assert plan.modify_prompt == "modify like so"
    assert plan.raw_state == 2
    assert "12345678-1234-1234-1234-123456789012" in plan.research_id


def test_plan_extraction_no_data() -> None:
    assert extract_deep_research_plan({"foo": "bar"}) is None
    assert extract_deep_research_plan({"57": []}) is None


def test_status_completed() -> None:
    inner = [
        None,
        [
            None, None, None,
            ["c_abc123"],
            ["Investigate widgets", "Find the best ones"],
        ],
        "some marker",
        "immersive_entry_chip something",
        "abc 12345678-1234-1234-1234-123456789012 def",
    ]
    body = [inner]
    st = extract_deep_research_status(body)
    assert st is not None
    assert st.state == "completed"
    assert st.done is True
    assert st.title == "Investigate widgets"
    assert st.query == "Find the best ones"
    assert st.cid == "c_abc123"


def test_status_awaiting() -> None:
    body = [
        None, None, None, None,
        "deep_research_confirmation_content here",
        "77777777-1234-1234-1234-123456789012",
    ]
    st = extract_deep_research_status(body)
    assert st is not None
    assert st.state == "awaiting_confirmation"
    assert st.done is False


def test_status_no_research_id() -> None:
    assert extract_deep_research_status([None, "no uuid here"]) is None
