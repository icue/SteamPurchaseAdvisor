import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
VERSION_PATH = REPO_ROOT / "VERSION"
REMOTE_VERSION_URL = (
    "https://raw.githubusercontent.com/"
    "icue/SteamPurchaseAdvisor/main/VERSION"
)

def parse_version(version_str):
    version_str = version_str.strip()
    match = re.fullmatch(r"(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)", version_str)
    if not match:
        return None
    return tuple(int(x) for x in match.groups())

def get_local_version():
    try:
        content = VERSION_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None, "version_missing"
    except Exception:
        return None, "version_unreadable"
    
    if not content.strip():
        return None, "version_invalid"
        
    parsed = parse_version(content)
    if not parsed:
        return None, "version_invalid"
        
    return (content.strip(), parsed), None

def get_remote_version():
    req = urllib.request.Request(
        REMOTE_VERSION_URL,
        headers={"User-Agent": "SteamPurchaseAdvisor-update-check"}
    )
    try:
        with urllib.request.urlopen(req, timeout=3.0) as response:
            content = response.read().decode("utf-8")
    except (urllib.error.URLError, ValueError, Exception):
        return None
        
    if not content.strip():
        return None
        
    parsed = parse_version(content)
    if not parsed:
        return None
        
    return (content.strip(), parsed)

def main():
    local_data, error_reason = get_local_version()
    if error_reason:
        print(json.dumps({"status": "local_error", "reason": error_reason}))
        sys.exit(2)
        
    local_str, local_parsed = local_data
    
    remote_data = get_remote_version()
    if not remote_data:
        print(json.dumps({"status": "unavailable"}))
        sys.exit(0)
        
    remote_str, remote_parsed = remote_data
    
    if local_parsed == remote_parsed:
        print(json.dumps({
            "status": "up_to_date",
            "installed_version": local_str,
            "latest_version": remote_str
        }))
        sys.exit(0)
    elif local_parsed < remote_parsed:
        print(json.dumps({
            "status": "update_available",
            "installed_version": local_str,
            "latest_version": remote_str
        }))
        sys.exit(0)
    else:
        print(json.dumps({
            "status": "ahead",
            "installed_version": local_str,
            "latest_version": remote_str
        }))
        sys.exit(0)

if __name__ == "__main__":
    main()
