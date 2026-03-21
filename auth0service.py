import os 
import requests

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

    # this function is always passed the result of get_logged_in_user_id()
    # (yeah theyre badly structured i know)
    # and that function gets given a dev mode value, so it wouldnt make sense to have to pass it in here too. Therefore we basically check whether the user id matches
    # the hardcoded developer user id
    if (not is_auth_configured()) and user_id == DEBUG_MODE_USERINFO.get("sub"):
        return True

    roles_json = get_auth0_user_roles(user_id)
    # current_app.logger.info(roles_json)
    for r in roles_json:
        rolename = r["name"].lower()
        if 'admin' in rolename:
            return True
    return False

def get_logged_in_user(debug_mode=False):
    if is_auth_configured():
        return session.get("user")
    elif debug_mode:
        return {
            "userinfo": DEBUG_MODE_USERINFO
        }

def get_logged_in_user_info(debug_mode=False):
    user = get_logged_in_user(debug_mode=debug_mode)
    userinfo = None
    if user is not None:
        userinfo = user.get("userinfo")
    return userinfo

def get_logged_in_user_id(debug_mode=False):
    userinfo = get_logged_in_user_info(debug_mode=debug_mode)
    if userinfo is not None:
        return userinfo.get("sub")

def save_user_details(token):
    # verify_token(token["id_token"], auth0_domain, api_identifier)
    session["user"] = token


