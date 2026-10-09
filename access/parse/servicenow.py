import enum
from datetime import datetime, timezone
from bs4 import BeautifulSoup
from dateutil import parser

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
		for e in soup.find_all('br'):
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

