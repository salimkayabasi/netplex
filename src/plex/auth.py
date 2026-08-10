import json
import urllib.request
import urllib.error
from src.database import get_setting, set_setting

PLEX_TV_PINS_URL = "https://plex.tv/api/v2/pins"

def _get_plex_headers(client_id: str) -> dict[str, str]:
    return {
        "X-Plex-Product": "NetPlex",
        "X-Plex-Client-Identifier": client_id,
        "X-Plex-Version": "1.0.0",
        "X-Plex-Device": "Docker Container",
        "Accept": "application/json"
    }

def request_plex_pin(db_path: str) -> dict:
    """Generates a Plex PIN object from Plex.tv and returns ID, code, and auth URL."""
    client_id = get_setting(db_path, "plex_client_id")
    if not client_id:
        raise ValueError("plex_client_id setting is missing in database.")
        
    headers = _get_plex_headers(client_id)
    req = urllib.request.Request(PLEX_TV_PINS_URL, headers=headers, method="POST")
    
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode("utf-8"))
        
    pin_id = data.get("id")
    pin_code = data.get("code")
    auth_url = f"https://app.plex.tv/auth#?code={pin_code}&context[device][product]=NetPlex&clientID={client_id}"
    
    return {
        "id": pin_id,
        "code": pin_code,
        "auth_url": auth_url
    }

def poll_plex_pin(db_path: str, pin_id: int | str) -> str | None:
    """Polls Plex.tv for the authorization status of a PIN.
    
    If authorized, saves the authToken into settings and returns it.
    Returns None if not yet authorized or if an error occurs.
    """
    client_id = get_setting(db_path, "plex_client_id")
    if not client_id:
        return None
        
    headers = _get_plex_headers(client_id)
    url = f"{PLEX_TV_PINS_URL}/{pin_id}"
    req = urllib.request.Request(url, headers=headers, method="GET")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            auth_token = data.get("authToken")
            if auth_token:
                set_setting(db_path, "plex_token", auth_token)
                return auth_token
            return None
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, json.JSONDecodeError, Exception):
        return None

def verify_plex_connection(db_path: str) -> bool:
    """Verifies that the stored Plex API token and URL can establish a connection with the server."""
    token = get_setting(db_path, "plex_token")
    if not token:
        return False
        
    plex_url = get_setting(db_path, "plex_url", default="http://localhost:32400")
    client_id = get_setting(db_path, "plex_client_id", default="netplex-client")
    
    headers = _get_plex_headers(client_id)
    headers["X-Plex-Token"] = token
    
    base_url = plex_url.rstrip("/")
    identity_url = f"{base_url}/identity"
    
    req = urllib.request.Request(identity_url, headers=headers, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=5) as resp:
            if resp.status == 200:
                return True
            return False
    except Exception:
        return False
