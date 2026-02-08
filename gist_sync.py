
"""
GMAT Tutor - GitHub Gist Sync Module
Handles independent syncing of the SQLite database to a private GitHub Gist.
Supports cross-sync with PWA version via JSON exchange files.
"""

import os
import json
import base64
import requests
from typing import Optional, Dict, Tuple, List
from datetime import datetime
import streamlit as st

GITHUB_API_URL = "https://api.github.com"
GIST_FILENAME = "gmat_tutor_db.b64"  # We'll store the DB as a base64 string
GIST_DESCRIPTION = "GMAT Tutor Sync Data (Do not delete)"

# Cross-sync filenames (shared with PWA)
JSON_EXPORT_FILENAME = "gmat_tutor_export.json"  # Streamlit writes, PWA reads
PWA_PENDING_FILENAME = "pwa_pending_logs.json"    # PWA writes, Streamlit reads


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

    def _build_json_export(self, db) -> str:
        """Build a JSON export of study data for PWA to read."""
        try:
            from database import Question, StudyLog, UserWeakness

            # Export study logs
            logs = db.get_study_logs(limit=10000)
            logs_data = []
            for log in logs:
                logs_data.append({
                    "question_id": log.question_id,
                    "user_answer": log.user_answer,
                    "is_correct": log.is_correct,
                    "time_taken": log.time_taken,
                    "error_category": log.error_category,
                    "error_detail": log.error_detail,
                    "timestamp": log.timestamp,
                })

            # Export weaknesses
            weaknesses = db.get_all_weaknesses()
            weaknesses_data = []
            for w in weaknesses:
                weaknesses_data.append({
                    "tag": w.tag,
                    "error_count": w.error_count,
                    "total_attempts": w.total_attempts,
                    "last_seen": w.last_seen,
                    "weight": w.weight,
                })

            export = {
                "source": "streamlit",
                "exported_at": datetime.now().isoformat(),
                "study_logs": logs_data,
                "user_weaknesses": weaknesses_data,
            }
            return json.dumps(export)
        except Exception as e:
            print(f"JSON export build failed: {e}")
            return ""

    def upload_db(self, db_path: str, db=None) -> Tuple[bool, str]:
        """Upload current DB to Gist, with JSON export for PWA cross-sync."""
        try:
            # 1. Read and encode DB
            with open(db_path, "rb") as f:
                db_content = f.read()
            b64_content = base64.b64encode(db_content).decode('utf-8')

            # 2. Prepare payload
            files = {
                GIST_FILENAME: {
                    "content": b64_content
                },
                "metadata.json": {
                    "content": json.dumps({
                        "updated_at": datetime.now().isoformat(),
                        "size": len(db_content),
                        "source": "streamlit",
                    })
                }
            }

            # 3. Add JSON export for PWA cross-sync
            if db:
                json_export = self._build_json_export(db)
                if json_export:
                    files[JSON_EXPORT_FILENAME] = {"content": json_export}

            payload = {
                "description": GIST_DESCRIPTION,
                "public": False,
                "files": files,
            }

            # 4. Create or Update
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

            file_info = files[GIST_FILENAME]

            # 3. Get content - handle truncated files (GitHub truncates large Gist files)
            if file_info.get('truncated', False):
                # Content was truncated by API; fetch full content via raw_url
                raw_url = file_info.get('raw_url')
                if not raw_url:
                    return False, "File truncated and no raw_url available."
                raw_resp = requests.get(raw_url, headers=self.headers)
                if raw_resp.status_code != 200:
                    return False, f"Failed to fetch raw content: {raw_resp.status_code}"
                b64_content = raw_resp.text
            else:
                b64_content = file_info['content']

            if not b64_content or len(b64_content.strip()) == 0:
                return False, "Remote backup is empty."

            db_content = base64.b64decode(b64_content)

            if len(db_content) < 100:
                return False, "Remote backup appears corrupted (too small)."

            # Backup current just in case
            if os.path.exists(db_path):
                try:
                    os.rename(db_path, f"{db_path}.bak")
                except OSError:
                    pass

            with open(db_path, "wb") as f:
                f.write(db_content)

            # Also clean up WAL/SHM files from previous connection
            for suffix in ['-wal', '-shm']:
                wal_path = db_path + suffix
                if os.path.exists(wal_path):
                    try:
                        os.remove(wal_path)
                    except OSError:
                        pass

            return True, "Download successful & DB restored."

        except Exception as e:
            return False, f"Download failed: {str(e)}"

    # ============== PWA Cross-Sync ==============

    def check_pwa_pending_logs(self) -> Optional[List[Dict]]:
        """Check if there are pending logs from PWA that need to be imported."""
        try:
            gist_id = self._find_existing_gist()
            if not gist_id:
                return None

            resp = requests.get(f"{GITHUB_API_URL}/gists/{gist_id}", headers=self.headers)
            if resp.status_code != 200:
                return None

            data = resp.json()
            files = data.get('files', {})

            if PWA_PENDING_FILENAME not in files:
                return None

            file_info = files[PWA_PENDING_FILENAME]

            # Get content (handle truncation)
            if file_info.get('truncated', False):
                raw_url = file_info.get('raw_url')
                if not raw_url:
                    return None
                raw_resp = requests.get(raw_url, headers=self.headers)
                if raw_resp.status_code != 200:
                    return None
                content = raw_resp.text
            else:
                content = file_info.get('content', '')

            if not content or content.strip() == '' or content.strip() == '[]':
                return None

            pending = json.loads(content)
            if isinstance(pending, list) and len(pending) > 0:
                return pending
            return None

        except Exception as e:
            print(f"Error checking PWA pending logs: {e}")
            return None

    def clear_pwa_pending_logs(self) -> bool:
        """Clear the pending logs file after successful import."""
        try:
            gist_id = self._find_existing_gist()
            if not gist_id:
                return False

            payload = {
                "files": {
                    PWA_PENDING_FILENAME: {
                        "content": "[]"
                    }
                }
            }
            resp = requests.patch(
                f"{GITHUB_API_URL}/gists/{gist_id}",
                headers=self.headers,
                json=payload
            )
            return resp.status_code == 200

        except Exception as e:
            print(f"Error clearing PWA pending logs: {e}")
            return False

    def import_pwa_logs(self, db) -> Tuple[int, str]:
        """
        Check for pending PWA logs and import them into the local database.
        Returns (count_imported, message).
        """
        try:
            pending = self.check_pwa_pending_logs()
            if not pending:
                return 0, "No pending PWA logs."

            from database import StudyLog

            # Get existing log timestamps to avoid duplicates
            existing_logs = db.get_study_logs(limit=10000)
            existing_keys = set()
            for log in existing_logs:
                # Use (question_id, timestamp) as dedup key
                existing_keys.add((log.question_id, log.timestamp))

            imported = 0
            for log_data in pending:
                key = (log_data.get('question_id'), log_data.get('timestamp'))
                if key in existing_keys:
                    continue  # Skip duplicate

                log = StudyLog(
                    id=None,
                    question_id=log_data['question_id'],
                    user_answer=log_data['user_answer'],
                    is_correct=log_data['is_correct'],
                    time_taken=log_data.get('time_taken', 0),
                    error_category=log_data.get('error_category'),
                    error_detail=log_data.get('error_detail'),
                    timestamp=log_data['timestamp'],
                )
                db.add_study_log(log)
                imported += 1

            # Clear pending logs after import
            if imported > 0:
                self.clear_pwa_pending_logs()

            return imported, f"Imported {imported} logs from PWA."

        except Exception as e:
            return 0, f"PWA import failed: {str(e)}"


# Helper for Streamlit integration
def get_gist_client():
    token = st.secrets.get("github_token") or st.session_state.get("github_token")
    # Also support getting from env for local dev
    if not token:
        token = os.environ.get("GITHUB_TOKEN")

    if token:
        return GistSync(token)
    return None
