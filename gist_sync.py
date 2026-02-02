
"""
GMAT Tutor - GitHub Gist Sync Module
Handles independent syncing of the SQLite database to a private GitHub Gist.
"""

import os
import json
import base64
import requests
from typing import Optional, Dict, Tuple
from datetime import datetime
import streamlit as st

GITHUB_API_URL = "https://api.github.com"
GIST_FILENAME = "gmat_tutor_db.b64"  # We'll store the DB as a base64 string
GIST_DESCRIPTION = "GMAT Tutor Sync Data (Do not delete)"

class GistSync:
    def __init__(self, token: str):
        self.token = token
        self.headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json",
        }

    def _find_existing_gist(self) -> Optional[str]:
        """Find the Gist ID if it already exists."""
        try:
            # List user's gists
            resp = requests.get(f"{GITHUB_API_URL}/gists", headers=self.headers)
            if resp.status_code != 200:
                return None
            
            gists = resp.json()
            for gist in gists:
                if gist.get('description') == GIST_DESCRIPTION:
                    return gist['id']
            return None
        except Exception as e:
            print(f"Error finding gist: {e}")
            return None

    def upload_db(self, db_path: str) -> Tuple[bool, str]:
        """Upload current DB to Gist."""
        try:
            # 1. Read and encode DB
            with open(db_path, "rb") as f:
                db_content = f.read()
            b64_content = base64.b64encode(db_content).decode('utf-8')

            # 2. Prepare payload
            payload = {
                "description": GIST_DESCRIPTION,
                "public": False,
                "files": {
                    GIST_FILENAME: {
                        "content": b64_content
                    },
                    "metadata.json": {
                        "content": json.dumps({
                            "updated_at": datetime.now().isoformat(),
                            "size": len(db_content)
                        })
                    }
                }
            }

            # 3. Create or Update
            gist_id = self._find_existing_gist()
            if gist_id:
                # Update
                resp = requests.patch(f"{GITHUB_API_URL}/gists/{gist_id}", headers=self.headers, json=payload)
            else:
                # Create
                resp = requests.post(f"{GITHUB_API_URL}/gists", headers=self.headers, json=payload)

            if resp.status_code in [200, 201]:
                return True, "Upload successful"
            else:
                return False, f"GitHub API Error: {resp.status_code} {resp.text}"

        except Exception as e:
            return False, f"Upload failed: {str(e)}"

    def download_db(self, db_path: str) -> Tuple[bool, str]:
        """Download DB from Gist and replace local file."""
        try:
            # 1. Find Gist
            gist_id = self._find_existing_gist()
            if not gist_id:
                return False, "No remote backup found."

            # 2. Get Gist content
            resp = requests.get(f"{GITHUB_API_URL}/gists/{gist_id}", headers=self.headers)
            if resp.status_code != 200:
                return False, "Failed to fetch Gist."
            
            data = resp.json()
            files = data.get('files', {})
            
            if GIST_FILENAME not in files:
                return False, "Backup file corrupted or missing."

            # 3. Decode and Write
            b64_content = files[GIST_FILENAME]['content']
            db_content = base64.b64decode(b64_content)

            # Backup current just in case
            if os.path.exists(db_path):
                os.rename(db_path, f"{db_path}.bak")

            with open(db_path, "wb") as f:
                f.write(db_content)
            
            return True, "Download successful & DB restored."

        except Exception as e:
            return False, f"Download failed: {str(e)}"

# Helper for Streamlit integration
def get_gist_client():
    token = st.secrets.get("github_token") or st.session_state.get("github_token")
    # Also support getting from env for local dev
    if not token:
        token = os.environ.get("GITHUB_TOKEN")
        
    if token:
        return GistSync(token)
    return None
