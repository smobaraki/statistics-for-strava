"""Generate Garmin session token for the Docker bridge.

Run this ONCE on your Mac (not in Docker) to authenticate with Garmin Connect.
After entering your credentials and MFA code, the session token is saved so the
Docker bridge can use it without further interaction.
"""

import json
import os
import sys

CONFIG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config")
CONFIG_FILE = os.path.join(CONFIG_DIR, "GarminConnectConfig.json")
TOKEN_FILE = os.path.join(CONFIG_DIR, "garmin_token.json")


def main():
    try:
        from garminconnect import Garmin
    except ImportError:
        print("Installing garminconnect...")
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "garminconnect"])
        from garminconnect import Garmin

    if not os.path.isfile(CONFIG_FILE):
        print(f"ERROR: {CONFIG_FILE} not found.")
        print("Copy the example and fill in your Garmin credentials:")
        print(f"  cp {CONFIG_FILE}.example {CONFIG_FILE}")
        sys.exit(1)

    with open(CONFIG_FILE) as f:
        config = json.load(f)

    email = config.get("user")
    password = config.get("password")

    if not email or not password:
        print("ERROR: Missing 'user' and 'password' in GarminConnectConfig.json")
        sys.exit(1)

    print(f"Logging in to Garmin Connect as {email}...")
    print("You will be prompted for your MFA code if required.\n")

    try:
        garmin = Garmin(email=email, password=password, prompt_mfa=lambda: input("MFA code: ").strip())
        garmin.login(TOKEN_FILE)
        print(f"\nSUCCESS: Token saved to {TOKEN_FILE}")
        print(f"Display name: {garmin.display_name}")
    except Exception as e:
        print(f"\nERROR: Login failed: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
