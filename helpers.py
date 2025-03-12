


def floor_to_integer(floor_val):

    if isinstance(floor_val, int):
        return floor_val  # Directly return integers

    if isinstance(floor_val, str):
        floor_val = floor_val.strip().upper()

        if floor_val.isalpha() and len(floor_val) == 1:  # Below ground levels (A, B, C -> -1, -2, -3)
            return - (ord(floor_val) - ord('A') + 1)

        if floor_val.isdigit():  # Regular positive floors
            return int(floor_val)

    return -99  # Default placeholder for unknown cases

def integer_to_floor(floor:int):
    if floor < 0:
        return chr(ord('A') + (-floor) -1 )
    elif floor == 0:
        return "N"
    else:
        return str(floor)


def room_to_integer(room_val):
    if isinstance(room_val, int):
        if room_val > 99 and room_val >= 999:
            return 0, room_val  # Directly return integers if three digits
        elif room_val > 999 and room_val <= 9999:
            return int(str(room_val)[0]), int(str(room_val)[1:])
        else:
            raise ValueError(f"Room number {room_val} is invalid")

    if isinstance(room_val, str):
        room_val = room_val.strip().upper()

        if room_val.startswith("N"):
            room_val = room_val.replace("N", "0")
        
        if len(room_val) == 3:
            return 0, int(room_val)  # Directly return integers if three digits
        elif len(room_val) == 4:
            return int(room_val[0]), int(room_val[1:])
        else:
            raise ValueError(f"Room number {room_val} is invalid")

    return 0, 0

def integer_to_room(floor:int, room:int):
    if room < -10:
        raise ValueError(f"default placeholder room value of {room} encountered")

    return integer_to_floor(floor) + str(room)