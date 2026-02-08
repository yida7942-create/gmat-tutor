/**
 * GMAT Focus AI Tutor - Cloud Sync (GitHub Gist)
 *
 * Cross-sync with Streamlit version:
 * - Reads study data from Streamlit's JSON export (gmat_tutor_export.json)
 * - Writes new offline logs to pwa_pending_logs.json for Streamlit to import
 * - Uses the SAME Gist as Streamlit (shared GIST_DESCRIPTION)
 */

const GITHUB_API_URL = 'https://api.github.com';

// MUST match gist_sync.py exactly
const GIST_DESCRIPTION = 'GMAT Tutor Sync Data (Do not delete)';

// Cross-sync filenames (shared with gist_sync.py)
const JSON_EXPORT_FILENAME = 'gmat_tutor_export.json';  // Streamlit writes, PWA reads
const PWA_PENDING_FILENAME = 'pwa_pending_logs.json';    // PWA writes, Streamlit reads

// PWA-only full backup (for standalone use / PWA-to-PWA restore)
const PWA_BACKUP_FILENAME = 'gmat_tutor_pwa.json';

class GistSync {
  constructor(token) {
    this.token = token;
    this.headers = {
      'Authorization': `token ${token}`,
      'Accept': 'application/vnd.github.v3+json',
      'Content-Type': 'application/json',
    };
  }

  async _findExistingGist() {
    try {
      const resp = await fetch(`${GITHUB_API_URL}/gists`, { headers: this.headers });
      if (!resp.ok) return null;
      const gists = await resp.json();
      for (const gist of gists) {
        if (gist.description === GIST_DESCRIPTION) return gist.id;
      }
      return null;
    } catch (e) {
      console.error('Error finding gist:', e);
      return null;
    }
  }

  async _getGistFile(gistId, filename) {
    try {
      const resp = await fetch(`${GITHUB_API_URL}/gists/${gistId}`, { headers: this.headers });
      if (!resp.ok) return null;

      const data = await resp.json();
      const files = data.files || {};

      if (!files[filename]) return null;

      const fileInfo = files[filename];
      if (fileInfo.truncated) {
        const rawUrl = fileInfo.raw_url;
        if (!rawUrl) return null;
        const rawResp = await fetch(rawUrl, { headers: this.headers });
        if (!rawResp.ok) return null;
        return await rawResp.text();
      }
      return fileInfo.content || null;
    } catch (e) {
      return null;
    }
  }

  // =============================================================
  // CROSS-SYNC: Download study data from Streamlit's export
  // =============================================================

  async downloadFromStreamlit() {
    if (!navigator.onLine) return { success: false, message: 'No internet connection.' };

    try {
      const gistId = await this._findExistingGist();
      if (!gistId) return { success: false, message: 'No cloud data found. Upload from Streamlit first.' };

      const content = await this._getGistFile(gistId, JSON_EXPORT_FILENAME);
      if (!content) {
        return { success: false, message: 'No Streamlit export found. Please sync from Streamlit first.' };
      }

      const exported = JSON.parse(content);
      if (!exported.study_logs) {
        return { success: false, message: 'Export file is invalid.' };
      }

      // Import study logs (merge, not replace)
      const existingLogs = await DB.getAllStudyLogs();
      const existingKeys = new Set(
        existingLogs.map(l => `${l.question_id}_${l.timestamp}`)
      );

      let importedCount = 0;
      for (const log of exported.study_logs) {
        const key = `${log.question_id}_${log.timestamp}`;
        if (existingKeys.has(key)) continue; // skip duplicates

        await DB.addStudyLog({
          question_id: log.question_id,
          user_answer: log.user_answer,
          is_correct: log.is_correct,
          time_taken: log.time_taken || 0,
          error_category: log.error_category || null,
          error_detail: log.error_detail || null,
          timestamp: log.timestamp,
        });
        importedCount++;
      }

      // Save sync watermark
      await DB.saveSession('last_streamlit_sync', new Date().toISOString());

      return {
        success: true,
        message: `Synced ${importedCount} new records from Streamlit.`,
        imported: importedCount,
      };
    } catch (e) {
      return { success: false, message: `Sync failed: ${e.message}` };
    }
  }

  // =============================================================
  // CROSS-SYNC: Upload new offline logs to Streamlit's Gist
  // =============================================================

  async uploadToStreamlit() {
    if (!navigator.onLine) return { success: false, message: 'No internet connection.' };

    try {
      // Get watermark: only upload logs created AFTER last sync
      const watermark = await DB.loadSession('last_streamlit_sync');
      const allLogs = await DB.getAllStudyLogs();

      // Filter logs created after watermark (or all if no watermark)
      let newLogs;
      if (watermark) {
        newLogs = allLogs.filter(l => l.timestamp > watermark);
      } else {
        newLogs = allLogs;
      }

      if (newLogs.length === 0) {
        return { success: true, message: 'No new records to upload.' };
      }

      // Prepare pending logs JSON
      const pendingData = newLogs.map(l => ({
        question_id: l.question_id,
        user_answer: l.user_answer,
        is_correct: l.is_correct,
        time_taken: l.time_taken,
        error_category: l.error_category || null,
        error_detail: l.error_detail || null,
        timestamp: l.timestamp,
      }));

      // Find or create the shared Gist
      let gistId = await this._findExistingGist();

      const payload = {
        description: GIST_DESCRIPTION,
        public: false,
        files: {
          [PWA_PENDING_FILENAME]: {
            content: JSON.stringify(pendingData),
          },
          'metadata.json': {
            content: JSON.stringify({
              updated_at: new Date().toISOString(),
              source: 'pwa',
              pending_logs: pendingData.length,
            }),
          },
        },
      };

      let resp;
      if (gistId) {
        resp = await fetch(`${GITHUB_API_URL}/gists/${gistId}`, {
          method: 'PATCH', headers: this.headers, body: JSON.stringify(payload),
        });
      } else {
        resp = await fetch(`${GITHUB_API_URL}/gists`, {
          method: 'POST', headers: this.headers, body: JSON.stringify(payload),
        });
      }

      if (!resp.ok) {
        const errText = await resp.text();
        return { success: false, message: `GitHub API Error: ${resp.status} ${errText.substring(0, 200)}` };
      }

      // Update watermark
      await DB.saveSession('last_streamlit_sync', new Date().toISOString());

      return {
        success: true,
        message: `Uploaded ${pendingData.length} records to cloud for Streamlit.`,
        uploaded: pendingData.length,
      };
    } catch (e) {
      return { success: false, message: `Upload failed: ${e.message}` };
    }
  }

  // =============================================================
  // STANDALONE PWA SYNC (full backup/restore, PWA-to-PWA)
  // =============================================================

  async upload() {
    if (!navigator.onLine) return { success: false, message: 'No internet connection.' };

    try {
      const allData = await DB.exportAllData();
      const content = JSON.stringify(allData);

      let gistId = await this._findExistingGist();

      const payload = {
        description: GIST_DESCRIPTION,
        public: false,
        files: {
          [PWA_BACKUP_FILENAME]: { content },
          'metadata.json': {
            content: JSON.stringify({
              updated_at: new Date().toISOString(),
              source: 'pwa',
              questions: allData.questions.length,
              logs: allData.study_logs.length,
            }),
          },
        },
      };

      let resp;
      if (gistId) {
        resp = await fetch(`${GITHUB_API_URL}/gists/${gistId}`, {
          method: 'PATCH', headers: this.headers, body: JSON.stringify(payload),
        });
      } else {
        resp = await fetch(`${GITHUB_API_URL}/gists`, {
          method: 'POST', headers: this.headers, body: JSON.stringify(payload),
        });
      }

      if (resp.ok) return { success: true, message: 'PWA backup uploaded.' };
      const errText = await resp.text();
      return { success: false, message: `GitHub API Error: ${resp.status} ${errText.substring(0, 200)}` };
    } catch (e) {
      return { success: false, message: `Upload failed: ${e.message}` };
    }
  }

  async download() {
    if (!navigator.onLine) return { success: false, message: 'No internet connection.' };

    try {
      const gistId = await this._findExistingGist();
      if (!gistId) return { success: false, message: 'No remote backup found.' };

      const content = await this._getGistFile(gistId, PWA_BACKUP_FILENAME);
      if (!content) return { success: false, message: 'PWA backup not found in cloud.' };

      const allData = JSON.parse(content);
      await DB.importAllData(allData);

      return { success: true, message: 'PWA data restored from cloud.' };
    } catch (e) {
      return { success: false, message: `Download failed: ${e.message}` };
    }
  }

  async getRemoteInfo() {
    if (!navigator.onLine) return null;
    try {
      const gistId = await this._findExistingGist();
      if (!gistId) return null;

      const content = await this._getGistFile(gistId, 'metadata.json');
      if (!content) return null;
      return JSON.parse(content);
    } catch (e) {
      return null;
    }
  }
}

function getGistClient() {
  const token = localStorage.getItem('github_token');
  if (token) return new GistSync(token);
  return null;
}

async function autoSyncToCloud() {
  try {
    const client = getGistClient();
    if (!client || !navigator.onLine) return;
    // Upload pending logs to Streamlit's Gist
    await client.uploadToStreamlit();
  } catch (e) { /* silent */ }
}

window.GistSync = GistSync;
window.getGistClient = getGistClient;
window.autoSyncToCloud = autoSyncToCloud;
