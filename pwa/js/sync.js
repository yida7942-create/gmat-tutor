/**
 * GMAT Focus AI Tutor - Cloud Sync (GitHub Gist)
 * Port of gist_sync.py: backup/restore IndexedDB data via Gist.
 */

const GITHUB_API_URL = 'https://api.github.com';
const GIST_FILENAME = 'gmat_tutor_pwa.json';
const GIST_DESCRIPTION = 'GMAT Tutor PWA Sync Data (Do not delete)';

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

  async upload() {
    if (!navigator.onLine) return { success: false, message: 'No internet connection.' };

    try {
      const allData = await DB.exportAllData();
      const content = JSON.stringify(allData);

      const payload = {
        description: GIST_DESCRIPTION,
        public: false,
        files: {
          [GIST_FILENAME]: { content },
          'metadata.json': {
            content: JSON.stringify({
              updated_at: new Date().toISOString(),
              size: content.length,
              questions: allData.questions.length,
              logs: allData.study_logs.length,
            }),
          },
        },
      };

      const gistId = await this._findExistingGist();
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

      if (resp.ok) return { success: true, message: 'Upload successful' };
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

      const resp = await fetch(`${GITHUB_API_URL}/gists/${gistId}`, { headers: this.headers });
      if (!resp.ok) return { success: false, message: 'Failed to fetch Gist.' };

      const data = await resp.json();
      const files = data.files || {};

      if (!files[GIST_FILENAME]) return { success: false, message: 'Backup file missing.' };

      const fileInfo = files[GIST_FILENAME];
      let content;

      if (fileInfo.truncated) {
        const rawUrl = fileInfo.raw_url;
        if (!rawUrl) return { success: false, message: 'File truncated, no raw_url.' };
        const rawResp = await fetch(rawUrl, { headers: this.headers });
        if (!rawResp.ok) return { success: false, message: 'Failed to fetch raw content.' };
        content = await rawResp.text();
      } else {
        content = fileInfo.content;
      }

      if (!content || content.trim().length === 0) {
        return { success: false, message: 'Remote backup is empty.' };
      }

      const allData = JSON.parse(content);
      await DB.importAllData(allData);

      return { success: true, message: 'Download successful & data restored.' };
    } catch (e) {
      return { success: false, message: `Download failed: ${e.message}` };
    }
  }

  async getRemoteInfo() {
    if (!navigator.onLine) return null;
    try {
      const gistId = await this._findExistingGist();
      if (!gistId) return null;

      const resp = await fetch(`${GITHUB_API_URL}/gists/${gistId}`, { headers: this.headers });
      if (!resp.ok) return null;

      const data = await resp.json();
      const metaFile = data.files?.['metadata.json'];
      if (!metaFile) return { updatedAt: data.updated_at };

      const meta = JSON.parse(metaFile.content);
      return meta;
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
    await client.upload();
  } catch (e) { /* silent */ }
}

window.GistSync = GistSync;
window.getGistClient = getGistClient;
window.autoSyncToCloud = autoSyncToCloud;
