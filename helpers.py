from dataclasses import dataclass

ANY_FLOOR_CHAR = "_"


def floor_to_integer(floor_str:str):
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

    @staticmethod
    def from_lat_long(lat:float, long:float):
        PRECISION = 5

        return int(lat * (10 ** PRECISION)), int(long * (10 ** PRECISION))
    
    @staticmethod
    def to_lat_long(lat:int, long: int):
        PRECISION = 5

        return lat/(10 ** PRECISION), long/(10 ** PRECISION)