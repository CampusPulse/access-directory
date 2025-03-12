


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
