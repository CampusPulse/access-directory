from dataclasses import dataclass
import enum
from dateutil import parser
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from flask import session
import requests
import os

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
        

        return int(lat * (10 ** MapLocation.PRECISION)), int(long * (10 ** MapLocation.PRECISION))
    
    @staticmethod
    def to_lat_long(lat:int, long: int):

        return lat/(10 ** MapLocation.PRECISION), long/(10 ** MapLocation.PRECISION)

    @staticmethod
    def to_long_lat(lat:int, long: int):

        lat, long = MapLocation.to_lat_long(lat, long)

        return long, lat

class ServiceNowUpdateType(enum.Enum):
    UNKNOWN = 0
    NEW = 1
    IN_PROGRESS = 2
    RESOLVED = 3


@dataclass
class ServiceNowStatus:

	timestamp: datetime
	status_type: ServiceNowUpdateType
	ref: str
	comment: str

	@staticmethod
	def statusFromSubject(subject:str) -> (ServiceNowUpdateType, str, bool):
		"""get status and other meta information from subject

		Args:
			subject (str): the email subject line
		Returns:
			StatusType: the StatusType this email represents
			str: the ref/ticket number this email refers to
			bool: whether or not this ticket likely has a new comment
		"""
		new_comment = False
		status_type = None
		if "added to the watch list" in subject or "opened on your behalf" in subject:
			status_type = ServiceNowUpdateType.NEW
		elif "Completed" in subject:
			status_type = ServiceNowUpdateType.RESOLVED
		elif "comments added" in subject:
			new_comment = True
			status_type = ServiceNowUpdateType.IN_PROGRESS
		else:
			status_type = ServiceNowUpdateType.UNKNOWN

		ref = ""
		ref_idx = subject.find("WOT")
		if ref_idx > -1:
			ref = subject[ref_idx:(ref_idx+len("OT1234567")+1)]
		

		return status_type, ref, new_comment

	@staticmethod
	def commentFromBody(html_str) -> str:
		soup = BeautifulSoup(html_str, 'html.parser')
		comments_group = soup.find('strong', string="Comments").find_parent('div')
		timestamp_author = comments_group.find_all('table')[0].find('td').contents[0].string
		timestamp = timestamp_author.split(" - ")[0]
		author = timestamp_author.split(" - ")[1]
		comment = comments_group.find_all('table')[1].find('td')
		for e in soup.findAll('br'):
			e.decompose()
		comment = "".join(comment.contents)
		dtstamp = parser.parse(timestamp, tzinfos={"EDT": -4*3600})

		return (f"{author}: {comment}", dtstamp)

	@classmethod
	def from_email(cls, sender:str, subject:str, body:str) -> (datetime, ServiceNowUpdateType, str, str):
		"""parse email information to extract useful info for the database

		Args:
			sender (str): the email sender
			subject (str): the email subject line
			body (str): the html email body

		Returns:
			datetime: the datetime of this update
			StatusType: the StatusType this email represents
			str: the ref/ticket number this email refers to
			str: the comment (if any). Defaults to none.
		"""
		timestamp = datetime.now(timezone.utc).astimezone()
		comment = None
		status_type, ref, new_comment = cls.statusFromSubject(subject)
		if new_comment:
			comment, timestamp = cls.commentFromBody(body)
		return cls(timestamp, status_type, ref, comment)



def get_auth0_user_roles(user_id):

    auth0_domain = os.environ.get("AUTH0_DOMAIN")
    client_id = os.environ.get("AUTH0_CLIENT_ID")
    client_secret = os.environ.get("AUTH0_CLIENT_SECRET")
        
    # Step 1: Get Management API token
    token_url = f"https://{auth0_domain}/oauth/token"
    token_payload = {
        "client_id": client_id,
        "client_secret": client_secret,
        "audience": f"https://{auth0_domain}/api/v2/",
        "grant_type": "client_credentials"
    }
    
    token_response = requests.post(token_url, json=token_payload)
    if token_response.status_code != 200:
        raise Exception(f"Error fetching token: {token_response.text}")
    
    access_token = token_response.json()["access_token"]

    # Step 2: Query user roles
    roles_url = f"https://{auth0_domain}/api/v2/users/{user_id}/roles"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {access_token}"
    }
    
    roles_response = requests.get(roles_url, headers=headers)
    if roles_response.status_code != 200:
        raise Exception(f"Error fetching user roles: {roles_response.text}")

    roles = roles_response.json()
    return roles  # List of role objects


def check_for_admin_role(user_id):
    if user_id is None:
        return False
    
    roles_json = get_auth0_user_roles(user_id)
    # current_app.logger.info(roles_json)
    for r in roles_json:
        rolename = r["name"].lower()
        if 'admin' in rolename:
            return True
    return False

def get_logged_in_user():
    return session.get("user")

def get_logged_in_user_id():
    user = get_logged_in_user()
    userinfo = None
    if user is not None:
        userinfo = user.get("userinfo")
    if userinfo is not None:
        return userinfo.get("sub")

def save_user_details(token):
    # verify_token(token["id_token"], auth0_domain, api_identifier)
    session["user"] = token


