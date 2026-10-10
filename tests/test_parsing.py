import pytest
from access.parse.sheet import split_on_gaps
from access.parse.servicenow import ServiceNowUpdateType, ServiceNowStatus
from pathlib import Path
from datetime import datetime


# ==========================================
# Spreadsheet Parsing Tests
# ==========================================

@pytest.mark.parametrize("subject, expected", [
    ("a            b           c         d", ["a", "b", "c", "d"]),
    ("a            b           c    d", ["a", "b", "c", "d"]),
])
def test_split_on_gaps(subject, expected):
    assert split_on_gaps(subject) == expected





# ==========================================
# ServiceNow Email Parsing Tests
# ==========================================

@pytest.mark.parametrize("subject, expected_type, expected_ref, expected_comment_flag", [
    ("Ticket opened on your behalf WOT1234567", ServiceNowUpdateType.NEW, "WOT1234567", False),
    ("Completed: WOT9999999", ServiceNowUpdateType.RESOLVED, "WOT9999999", False),
    ("New comments added to WOT0000000", ServiceNowUpdateType.IN_PROGRESS, "WOT0000000", True),
    ("Random email title", ServiceNowUpdateType.UNKNOWN, "", False),
])
def test_service_now_status_from_subject(subject, expected_type, expected_ref, expected_comment_flag):
    status_type, ref, new_comment = ServiceNowStatus.statusFromSubject(subject)
    assert status_type == expected_type
    assert ref == expected_ref
    assert new_comment is expected_comment_flag


def test_service_now_comment_from_body():
    sample_html = Path("tests/comments_added.html").read_text()
    comment_str, dt = ServiceNowStatus.commentFromBody(sample_html)
    assert comment_str == "Michael Bay: Button box has been repaired.....ABC"
    assert isinstance(dt, datetime)


