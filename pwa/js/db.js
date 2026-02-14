/**
 * GMAT Focus AI Tutor - IndexedDB Data Layer
 * Port of database.py to browser IndexedDB.
 */

const DB_NAME = 'gmat_tutor';
const DB_VERSION = 1;

let _db = null;

function openDB() {
  if (_db) return Promise.resolve(_db);
  return new Promise((resolve, reject) => {
    const req = indexedDB.open(DB_NAME, DB_VERSION);
    req.onupgradeneeded = (e) => {
      const db = e.target.result;
      // questions
      if (!db.objectStoreNames.contains('questions')) {
        const qs = db.createObjectStore('questions', { keyPath: 'id', autoIncrement: true });
        qs.createIndex('subcategory', 'subcategory', { unique: false });
      }
      // study_logs
      if (!db.objectStoreNames.contains('study_logs')) {
        const sl = db.createObjectStore('study_logs', { keyPath: 'id', autoIncrement: true });
        sl.createIndex('question_id', 'question_id', { unique: false });
        sl.createIndex('timestamp', 'timestamp', { unique: false });
      }
      // user_weaknesses
      if (!db.objectStoreNames.contains('user_weaknesses')) {
        db.createObjectStore('user_weaknesses', { keyPath: 'tag' });
      }
      // session_store
      if (!db.objectStoreNames.contains('session_store')) {
        db.createObjectStore('session_store', { keyPath: 'key' });
      }
    };
    req.onsuccess = (e) => { _db = e.target.result; resolve(_db); };
    req.onerror = (e) => reject(e.target.error);
  });
}

// ============== Generic Helpers ==============

async function _tx(storeName, mode) {
  const db = await openDB();
  return db.transaction(storeName, mode).objectStore(storeName);
}

function _req(request) {
  return new Promise((resolve, reject) => {
    request.onsuccess = () => resolve(request.result);
    request.onerror = () => reject(request.error);
  });
}

function _getAll(store) {
  return _req(store.getAll());
}

// ============== Question CRUD ==============

async function addQuestion(q) {
  const store = await _tx('questions', 'readwrite');
  return _req(store.add(q));
}

async function addQuestionsBulk(questions) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('questions', 'readwrite');
    const store = tx.objectStore('questions');
    questions.forEach(q => store.add(q));
    tx.oncomplete = () => resolve(questions.length);
    tx.onerror = () => reject(tx.error);
  });
}

async function getQuestion(id) {
  const store = await _tx('questions', 'readonly');
  return _req(store.get(id));
}

async function getAllQuestions() {
  const store = await _tx('questions', 'readonly');
  return _getAll(store);
}

async function getQuestionsBySubcategory(subcategory, limit = 500) {
  const all = await getAllQuestions();
  const filtered = all.filter(q => q.subcategory === subcategory);
  return filtered.slice(0, limit);
}

async function getQuestionsBySkillTag(skillTag, subcategory = null, limit = 500) {
  const all = await getAllQuestions();
  let filtered = all.filter(q =>
    q.skill_tags && q.skill_tags.includes(skillTag)
  );
  if (subcategory) {
    filtered = filtered.filter(q => q.subcategory === subcategory);
  }
  return filtered.slice(0, limit);
}

async function getQuestionsByTags(tags, limit = 50) {
  const all = await getAllQuestions();
  const filtered = all.filter(q =>
    q.skill_tags && q.skill_tags.some(t => tags.includes(t))
  );
  return filtered.slice(0, limit);
}

async function getSkillTagsBySubcategory(subcategory) {
  const questions = await getQuestionsBySubcategory(subcategory, 9999);
  const tagsSet = new Set();
  questions.forEach(q => {
    if (q.skill_tags) q.skill_tags.forEach(t => tagsSet.add(t));
  });
  return Array.from(tagsSet).sort();
}

async function getUnansweredQuestions() {
  const allQ = await getAllQuestions();
  const allLogs = await getAllStudyLogs();
  const answeredIds = new Set(allLogs.map(l => l.question_id));
  return allQ.filter(q => !answeredIds.has(q.id));
}

async function getQuestionCountsByType() {
  const all = await getAllQuestions();
  const counts = {};
  all.forEach(q => {
    counts[q.subcategory] = (counts[q.subcategory] || 0) + 1;
  });
  return counts;
}

// ============== Study Log CRUD ==============

async function addStudyLog(log) {
  const store = await _tx('study_logs', 'readwrite');
  const id = await _req(store.add(log));

  // Update weakness weights
  const question = await getQuestion(log.question_id);
  if (question && question.skill_tags) {
    for (const tag of question.skill_tags) {
      await _updateWeakness(tag, !log.is_correct);
    }
  }
  return id;
}

async function getAllStudyLogs() {
  const store = await _tx('study_logs', 'readonly');
  return _getAll(store);
}

async function getStudyLogs(limit = 100) {
  const all = await getAllStudyLogs();
  all.sort((a, b) => b.timestamp.localeCompare(a.timestamp));
  return all.slice(0, limit);
}

async function getLogsForQuestion(questionId) {
  const all = await getAllStudyLogs();
  return all
    .filter(l => l.question_id === questionId)
    .sort((a, b) => b.timestamp.localeCompare(a.timestamp));
}

async function getRecentLogsByTag(tag, days = 7) {
  const cutoff = new Date(Date.now() - days * 86400000).toISOString();
  const allLogs = await getAllStudyLogs();
  const allQ = await getAllQuestions();
  const qMap = {};
  allQ.forEach(q => { qMap[q.id] = q; });

  return allLogs.filter(l => {
    if (l.timestamp <= cutoff) return false;
    const q = qMap[l.question_id];
    return q && q.skill_tags && q.skill_tags.includes(tag);
  }).sort((a, b) => b.timestamp.localeCompare(a.timestamp));
}

// ============== Weakness Management ==============

async function _updateWeakness(tag, isError) {
  const db = await openDB();
  return new Promise((resolve, reject) => {
    const tx = db.transaction('user_weaknesses', 'readwrite');
    const store = tx.objectStore('user_weaknesses');
    const getReq = store.get(tag);

    getReq.onsuccess = () => {
      const now = new Date().toISOString();
      const existing = getReq.result;

      if (existing) {
        existing.error_count += isError ? 1 : 0;
        existing.total_attempts += 1;
        existing.weight = _calculateWeight(existing.error_count, existing.total_attempts, now, existing.last_seen);
        existing.last_seen = now;
        store.put(existing);
      } else {
        store.add({
          tag,
          error_count: isError ? 1 : 0,
          total_attempts: 1,
          last_seen: now,
          weight: isError ? 2.0 : 1.0,
        });
      }
    };
    tx.oncomplete = () => resolve();
    tx.onerror = () => reject(tx.error);
  });
}

function _calculateWeight(errorCount, total, now, lastSeen) {
  const BASE = 1.0;
  const errorRate = total > 0 ? errorCount / total : 0.5;
  const errorFactor = 0.5 + errorRate * 1.5;

  let daysSince = 0;
  try {
    daysSince = Math.floor((new Date(now) - new Date(lastSeen)) / 86400000);
  } catch (e) { /* ignore */ }

  let timeFactor = Math.min(1.5, 0.8 + daysSince * 0.05);
  if (errorRate < 0.3 && daysSince > 7) {
    timeFactor = Math.max(timeFactor, 1.2);
  }

  return Math.round(BASE * errorFactor * timeFactor * 100) / 100;
}

async function getAllWeaknesses() {
  const store = await _tx('user_weaknesses', 'readonly');
  const all = await _getAll(store);
  all.sort((a, b) => b.weight - a.weight);
  return all;
}

async function getWeaknessByTag(tag) {
  const store = await _tx('user_weaknesses', 'readonly');
  return _req(store.get(tag));
}

// ============== Statistics ==============

async function getStats() {
  const allQ = await getAllQuestions();
  const allLogs = await getAllStudyLogs();

  const totalQuestions = allQ.length;
  const totalAttempts = allLogs.length;
  const correctAttempts = allLogs.filter(l => l.is_correct).length;
  const overallAccuracy = totalAttempts > 0
    ? Math.round(correctAttempts / totalAttempts * 1000) / 10 : 0;

  // Accuracy by subcategory
  const qMap = {};
  allQ.forEach(q => { qMap[q.id] = q; });

  const byType = {};
  allLogs.forEach(l => {
    const q = qMap[l.question_id];
    if (!q) return;
    const sub = q.subcategory;
    if (!byType[sub]) byType[sub] = { total: 0, correct: 0 };
    byType[sub].total++;
    if (l.is_correct) byType[sub].correct++;
  });

  const accuracyByType = {};
  for (const [sub, data] of Object.entries(byType)) {
    accuracyByType[sub] = {
      total: data.total,
      correct: data.correct,
      accuracy: data.total > 0 ? Math.round(data.correct / data.total * 1000) / 10 : 0,
    };
  }

  // Daily trend (last 7 days)
  const cutoff = new Date(Date.now() - 7 * 86400000).toISOString();
  const recentLogs = allLogs.filter(l => l.timestamp > cutoff);
  const dailyMap = {};
  recentLogs.forEach(l => {
    const date = l.timestamp.substring(0, 10);
    if (!dailyMap[date]) dailyMap[date] = { total: 0, correct: 0 };
    dailyMap[date].total++;
    if (l.is_correct) dailyMap[date].correct++;
  });

  const dailyTrend = Object.keys(dailyMap).sort().map(date => ({
    date,
    total: dailyMap[date].total,
    correct: dailyMap[date].correct,
    accuracy: Math.round(dailyMap[date].correct / dailyMap[date].total * 1000) / 10,
  }));

  return {
    total_questions: totalQuestions,
    total_attempts: totalAttempts,
    correct_attempts: correctAttempts,
    overall_accuracy: overallAccuracy,
    accuracy_by_type: accuracyByType,
    daily_trend: dailyTrend,
  };
}

// ============== Session Store ==============

async function saveSession(key, value) {
  const store = await _tx('session_store', 'readwrite');
  return _req(store.put({ key, value, updated_at: new Date().toISOString() }));
}

async function loadSession(key) {
  const store = await _tx('session_store', 'readonly');
  const row = await _req(store.get(key));
  return row ? row.value : null;
}

async function deleteSession(key) {
  const store = await _tx('session_store', 'readwrite');
  return _req(store.delete(key));
}

async function clearSession() {
  const store = await _tx('session_store', 'readwrite');
  return _req(store.clear());
}

// ============== Data Import / Export ==============

async function importQuestionsFromJSON(jsonData) {
  const existing = await getAllQuestions();
  if (existing.length > 0) return 0;

  const questions = jsonData.map(q => ({
    passage_id: null,
    category: q.category || 'Verbal',
    subcategory: q.subcategory || 'CR',
    content: q.content,
    question_stem: q.question_stem || '',
    options: q.options,
    correct_answer: q.correct_answer,
    skill_tags: q.skill_tags,
    difficulty: q.difficulty || 3,
    explanation: q.explanation || '',
  }));

  return addQuestionsBulk(questions);
}

async function exportAllData() {
  const questions = await getAllQuestions();
  const logs = await getAllStudyLogs();
  const weaknesses = await getAllWeaknesses();
  const settings = {};

  // Gather all session store entries
  const store = await _tx('session_store', 'readonly');
  const sessions = await _getAll(store);
  sessions.forEach(s => { settings[s.key] = s.value; });

  return { questions, study_logs: logs, user_weaknesses: weaknesses, settings };
}

async function importAllData(data) {
  const db = await openDB();

  // Clear all stores
  const storeNames = ['questions', 'study_logs', 'user_weaknesses', 'session_store'];
  for (const name of storeNames) {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(name, 'readwrite');
      tx.objectStore(name).clear();
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  // Import questions
  if (data.questions && data.questions.length) {
    await new Promise((resolve, reject) => {
      const tx = db.transaction('questions', 'readwrite');
      const store = tx.objectStore('questions');
      data.questions.forEach(q => store.add(q));
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  // Import logs
  if (data.study_logs && data.study_logs.length) {
    await new Promise((resolve, reject) => {
      const tx = db.transaction('study_logs', 'readwrite');
      const store = tx.objectStore('study_logs');
      data.study_logs.forEach(l => store.add(l));
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  // Import weaknesses
  if (data.user_weaknesses && data.user_weaknesses.length) {
    await new Promise((resolve, reject) => {
      const tx = db.transaction('user_weaknesses', 'readwrite');
      const store = tx.objectStore('user_weaknesses');
      data.user_weaknesses.forEach(w => store.add(w));
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }

  // Import settings
  if (data.settings) {
    await new Promise((resolve, reject) => {
      const tx = db.transaction('session_store', 'readwrite');
      const store = tx.objectStore('session_store');
      for (const [key, value] of Object.entries(data.settings)) {
        store.put({ key, value, updated_at: new Date().toISOString() });
      }
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }
}

async function clearQuestions() {
  const db = await openDB();
  await new Promise((resolve, reject) => {
    const tx = db.transaction('questions', 'readwrite');
    tx.objectStore('questions').clear();
    tx.oncomplete = resolve;
    tx.onerror = () => reject(tx.error);
  });
}

async function resetDatabase() {
  const db = await openDB();
  const storeNames = ['study_logs', 'user_weaknesses', 'session_store'];
  for (const name of storeNames) {
    await new Promise((resolve, reject) => {
      const tx = db.transaction(name, 'readwrite');
      tx.objectStore(name).clear();
      tx.oncomplete = resolve;
      tx.onerror = () => reject(tx.error);
    });
  }
}

// ============== Exports ==============

window.DB = {
  openDB,
  addQuestion,
  addQuestionsBulk,
  getQuestion,
  getAllQuestions,
  getQuestionsBySubcategory,
  getQuestionsBySkillTag,
  getQuestionsByTags,
  getSkillTagsBySubcategory,
  getUnansweredQuestions,
  getQuestionCountsByType,
  addStudyLog,
  getAllStudyLogs,
  getStudyLogs,
  getLogsForQuestion,
  getRecentLogsByTag,
  getAllWeaknesses,
  getWeaknessByTag,
  getStats,
  saveSession,
  loadSession,
  deleteSession,
  clearSession,
  clearQuestions,
  importQuestionsFromJSON,
  exportAllData,
  importAllData,
  resetDatabase,
};
