import os 

DEBUG_MODE_USERINFO = {
	"name": "DEVELOPER",
	"sub": "debug:1234567890"
}

def is_auth_configured() -> bool:
	"""Whether auth is configured to run in production mode
	"""
	return not None in [
		os.environ.get("AUTH0_DOMAIN"),
		os.environ.get("CPACCESS_SECRET_KEY"),
		os.environ.get("AUTH0_CLIENT_ID"),
		os.environ.get("AUTH0_CLIENT_SECRET")
	]

