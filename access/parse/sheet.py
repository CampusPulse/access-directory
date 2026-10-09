import enum
from dataclasses import dataclass, field
from typing import Optional

class SpreadsheetUpdateType(str, enum.Enum):
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

@dataclass
class SpreadsheetDiff:
	# this is a dict storing the from/to change entries, keyed by line number
	diff_by_line:dict = field(default_factory=dict)

	@classmethod
	def from_lines(cls, lines: list):
		spreadsheet = {}
		for line in lines:
			info = split_on_gaps(line, gap_size=2)

			change = info[0].replace("(", "").replace(")", "")
			if change == "changed":
				change = "from"
			line_num = info[1]   
			diffentry = DiffEntry.from_diff_list(info[2:])
			if spreadsheet.get(str(line_num)) is None:
				spreadsheet[str(line_num)] = {
					change: diffentry
				}
			else:
				spreadsheet[str(line_num)][change] = diffentry

		return cls(spreadsheet)


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