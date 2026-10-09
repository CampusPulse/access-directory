import pytest
from datetime import datetime
from helpers import (
    floor_to_integer,
    integer_to_floor,
    RoomNumber,
    MapLocation,
    ServiceNowUpdateType,
    ServiceNowStatus,
    ANY_FLOOR_CHAR,
)
from pathlib import Path

# ==========================================
# 1. Floor Conversion Tests
# ==========================================

@pytest.mark.parametrize("floor_str, expected", [
    ("N", 0),
    ("_", 0),
    ("1", 1),
    ("12", 12),
    ("A", -1),  # Basement level A -> -1
    ("B", -2),  # Basement level B -> -2
])
def test_floor_to_integer_valid(floor_str, expected):
    assert floor_to_integer(floor_str) == expected


@pytest.mark.parametrize("invalid_input", ["1.5", "A1", "@", None])
def test_floor_to_integer_invalid(invalid_input):
    with pytest.raises(ValueError, match="Invalid floor value"):
        floor_to_integer(invalid_input)


@pytest.mark.parametrize("floor_int, expected", [
    (0, ANY_FLOOR_CHAR),
    (1, "1"),
    (5, "5"),
    (-1, "A"),
    (-2, "B"),
])
def test_integer_to_floor(floor_int, expected):
    assert integer_to_floor(floor_int) == expected


# ==========================================
# 2. RoomNumber Class Tests
# ==========================================

def test_room_number_from_string_valid():
    # 3-digit room (default ground/0 floor)
    room = RoomNumber.from_string("101")
    assert room.floor == 0
    assert room.room == 101

    # 4-digit room
    room = RoomNumber.from_string("2101")
    assert room.floor == 2
    assert room.room == 101

    # Basement room (e.g., A101)
    room = RoomNumber.from_string("A101")
    assert room.floor == -1
    assert room.room == 101


@pytest.mark.parametrize("bad_room", ["1", "12", "12345", ""])
def test_room_number_from_string_invalid_length(bad_room):
    with pytest.raises(ValueError, match="invalid length"):
        RoomNumber.from_string(bad_room)


def test_room_number_to_string():
    room = RoomNumber(floor=2, room=101)
    assert room.to_string() == "2101"

    room_basement = RoomNumber(floor=-1, room=50)
    assert room_basement.to_string() == "A050"


def test_room_number_to_string_floor_overflow():
    room = RoomNumber(floor=10, room=101)
    with pytest.raises(ValueError, match="greater than one digit"):
        room.to_string()


# ==========================================
# 3. MapLocation Tests
# ==========================================

def test_map_location_conversions():
    lat, long = 42.3601, -71.0589
    
    # Lat/Long to Int representation
    int_lat, int_long = MapLocation.from_lat_long(lat, long)
    assert int_lat == 4236010
    assert int_long == -7105890

    # Int back to Lat/Long
    res_lat, res_long = MapLocation.to_lat_long(int_lat, int_long)
    assert res_lat == pytest.approx(lat)
    assert res_long == pytest.approx(long)


def test_map_location_from_string():
    result = MapLocation.from_string("42.3601, -71.0589")
    assert result == (4236010, -7105890)

    assert MapLocation.from_string(None) is None
    assert MapLocation.from_string("") is None


def test_map_location_from_string_invalid():
    with pytest.raises(ValueError, match="invalid value for lat long"):
        MapLocation.from_string("not_a_latitude, not_a_longitude")


# ==========================================
# 4. ServiceNow Email Parsing Tests
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