from dataclasses import dataclass
import enum
from dateutil import parser
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from typing import Optional

from flask import session
import requests
import os

from access.parse.servicenow import ServiceNowStatus, ServiceNowUpdateType

ANY_FLOOR_CHAR = "_"


def floor_to_integer(floor_str:str):
    if floor_str is None:
        raise ValueError(f"Invalid floor value {floor_str}")
    floor_str = str(floor_str)

    if floor_str in ("N", "_"):
        return 0
    elif floor_str.isalpha():
        return - (ord(floor_str) - ord('A') + 1)
    elif floor_str.isnumeric():
        return int(floor_str)
    else:
        raise ValueError(f"Invalid floor value {floor_str}")

def integer_to_floor(floor_int:int):

    if floor_int < 0:
        return chr(ord('A') + (-floor_int) -1 ) 
    elif floor_int == 0:
        return ANY_FLOOR_CHAR
    else:
        return str(floor_int)

@dataclass
class RoomNumber():
    """A helper class to enable conversion from human readable room numbers to a neat integer system for database storage
    """
    floor: int
    room: int

    @classmethod
    def from_string(cls, room_val:str):
        room_val = room_val.strip().upper()

        if len(room_val) < 3 or len(room_val) > 4:
            raise ValueError(f"Room number {room_val} is of invalid length. Expecting either 3 or 4 character string")
        
        floor_str = room_val[0] if len(room_val) == 4 else "0"
        room_str = room_val[-3:]     
        
        return cls(floor_to_integer(floor_str), int(room_str))
            
    
    def integers(self):
        return (self.floor, self.room)

    def to_string(self):
        if self.floor >= 10:
            raise ValueError(f"Floor value {self.floor} is greater than one digit")
        return integer_to_floor(self.floor) + str(self.room).zfill(3)

class MapLocation():

    PRECISION = 5

    @staticmethod
    def from_string(lat_long: str, delimiter=","):
        if lat_long is None or lat_long == "":
            return None
        ll = lat_long.split(delimiter)
        try:
            lat = float(ll[0].strip())
            long = float(ll[1].strip())
            return MapLocation.from_lat_long(lat, long)
        except Exception as e:
            raise ValueError("invalid value for lat long from string") from e

    @staticmethod
    def to_string(lat:int, long:int, delimiter=", "):
        lat, long = MapLocation.to_lat_long(lat, long)
        return f"{lat}{delimiter}{long}"

    @staticmethod
    def from_lat_long(lat:float, long:float):
        return int(round(lat * (10 ** MapLocation.PRECISION),0)), int(round(long * (10 ** MapLocation.PRECISION),0))
    
    @staticmethod
    def to_lat_long(lat:int, long: int):

        return lat/(10 ** MapLocation.PRECISION), long/(10 ** MapLocation.PRECISION)

    @staticmethod
    def to_long_lat(lat:int, long: int):

        lat, long = MapLocation.to_lat_long(lat, long)

        return long, lat


class SpreadsheetUpdateType(enum.Enum, str):
    IN_SERVICE = "In service"
    INVESTIGATING = "Investigating"
    OUT_OF_SERVICE = "Out of Service"
    PARTS_WAITING = "Parts on Order"
    VENDOR_WAITING = "Pending Vendor"

@dataclass
class DiffEntry:
    building: Optional[str]
    id_number: str
    discriminator: str
    floors: str
    status: str
    notes: Optional[str] = None
    ticket: Optional[str] = None

    @staticmethod
    def is_status_value(value:str):
        options = [
            "In service",
            "Investigating",
            "Out of Service",
            "Parts on Order",
            "Pending Vendor"
        ]
        return value in options


    @classmethod
    def from_diff_list(cls, diff_list:list):
        if len(diff_list) < 4:
            raise ValueError(f"diff list too short: {diff_list}")
        
        status_index = [cls.is_status_value(v) for v in diff_list].index(True)

        if status_index == 4:
            return cls(*diff_list)
        elif status_index == 3:
            diff_list.insert(0, None)
            return cls(*diff_list)
        else:
            raise ValueError(f"encountered unforeseen index of status value: {status_index}")


def split_on_gaps(value:str, gap_size=3) -> list:
    """Split a string on gaps larger than a certain size

    Args:
        input (str): the input string to split
        gap_size (int, optional): the size of the gap, in spaces/chars, to count for a split. Defaults to 3.

    Returns:
        list: the elements in the list split by the desired delimiter
    """
    roughsplit = value.split(" " * gap_size)
    return [i.strip() for i in roughsplit if i.strip() != '']