/**
 * GMAT Focus AI Tutor - Main Application
 * Single-page app with tab navigation. Ports app.py UI to vanilla JS.
 */

// ============== Global State ==============

const AppState = {
  currentPage: 'dashboard',
  scheduler: null,
  tutor: null,
  // Practice state
  currentPlan: null,
  currentQuestionIdx: 0,
  sessionLogs: [],
  questionStartTime: null,
  showResult: false,
  lastAnswer: null,
  // AI cache
  aiCache: {},
};

// ============== Initialization ==============

async function initApp() {
  showLoading('Loading...');

  await DB.openDB();

  // Try auto-restore from cloud if local DB has no study history
  await tryRestoreFromCloud();

  // Load question bank if empty or missing question_stem (migration)
  const allQ = await DB.getAllQuestions();
  const needsReimport = allQ.length === 0 || (allQ.length > 0 && !allQ[0].question_stem);
  if (needsReimport) {
    showLoading('Importing questions...');
    try {
      if (allQ.length > 0) {
        // Clear old questions without question_stem
        await DB.clearQuestions();
      }
      const resp = await fetch('./data/og_questions.json');
      const data = await resp.json();
      await DB.importQuestionsFromJSON(data);
    } catch (e) {
      console.error('Failed to load questions:', e);
    }
  }

  // Init scheduler - load saved config
  const savedSchedulerConfig = await loadSchedulerConfig();
  AppState.scheduler = new Scheduler(savedSchedulerConfig);

  // Init AI tutor
  AppState.tutor = new AITutor();
  await AppState.tutor.loadFromDB();

  // Try restore practice state
  await restorePracticeState();

  // Setup event listeners
  setupTabNavigation();
  setupOnlineStatus();

  hideLoading();

  // Navigate to correct page
  if (AppState.currentPlan && AppState.currentPlan.questions.length) {
    navigateTo('practice');
  } else {
    navigateTo('dashboard');
  }
}

// ============== Auto-Restore from Cloud ==============

async function tryRestoreFromCloud() {
  try {
    const client = getGistClient();
    if (!client || !navigator.onLine) return;

    // Only restore if local DB has no study history
    const stats = await DB.getStats();
    if (stats.total_attempts > 0) return;

    showLoading('Restoring from cloud...');

    // Try Streamlit export first (preferred cross-sync source)
    let res = await client.downloadFromStreamlit();
    if (res.success && res.imported > 0) {
      showToast('☁️ Synced from Streamlit data', 3000);
      return;
    }

    // Fallback to PWA standalone backup
    res = await client.download();
    if (res.success) {
      showToast('☁️ Data restored from cloud backup', 3000);
    }
  } catch (e) {
    console.warn('Cloud restore failed:', e);
  }
}

// ============== Scheduler Config Persistence ==============

async function loadSchedulerConfig() {
  try {
    const raw = await DB.loadSession('scheduler_config');
    if (raw) return JSON.parse(raw);
  } catch (e) { /* ignore */ }
  return null;
}

async function saveSchedulerConfig(config) {
  await DB.saveSession('scheduler_config', JSON.stringify(config));
  AppState.scheduler = new Scheduler(config);
}

// ============== CSV Export ==============

async function exportCSV() {
  try {
    const logs = await DB.getStudyLogs(10000);
    const allQ = await DB.getAllQuestions();
    const qMap = {};
    allQ.forEach(q => { qMap[q.id] = q; });

    const header = 'id,question_id,subcategory,skill_tags,user_answer,is_correct,time_taken,error_category,error_detail,timestamp';
    const rows = logs.map((l, i) => {
      const q = qMap[l.question_id];
      const sub = q ? q.subcategory : '';
      const tags = q ? (q.skill_tags || []).join(';') : '';
      return [
        i + 1, l.question_id, sub, '"' + tags + '"',
        l.user_answer, l.is_correct ? 1 : 0, l.time_taken,
        l.error_category || '', l.error_detail || '', l.timestamp
      ].join(',');
    });

    const csv = header + '\n' + rows.join('\n');
    const blob = new Blob(['\uFEFF' + csv], { type: 'text/csv;charset=utf-8' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `gmat_study_logs_${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('CSV exported');
  } catch (e) {
    showToast('Export failed: ' + e.message);
  }
}

// ============== Navigation ==============

function setupTabNavigation() {
  document.querySelectorAll('.tab-item').forEach(tab => {
    tab.addEventListener('click', () => {
      navigateTo(tab.dataset.page);
    });
  });
}

function navigateTo(page) {
  AppState.currentPage = page;

  // Update tabs
  document.querySelectorAll('.tab-item').forEach(t => {
    t.classList.toggle('active', t.dataset.page === page);
  });

  // Update pages
  document.querySelectorAll('.page').forEach(p => {
    p.classList.toggle('active', p.id === `page-${page}`);
  });

  // Render page content
  switch (page) {
    case 'dashboard': renderDashboard(); break;
    case 'practice': renderPractice(); break;
    case 'progress': renderProgress(); break;
    case 'settings': renderSettings(); break;
  }

  // Scroll to top
  window.scrollTo(0, 0);
}

// ============== Online Status ==============

function setupOnlineStatus() {
  updateStatusIndicators();
  window.addEventListener('online', updateStatusIndicators);
  window.addEventListener('offline', updateStatusIndicators);
}

function updateStatusIndicators() {
  const online = navigator.onLine;
  const netDot = document.getElementById('net-status');
  const aiDot = document.getElementById('ai-status');
  const netLabel = document.getElementById('net-label');
  const aiLabel = document.getElementById('ai-label');

  if (netDot) {
    netDot.className = 'status-dot ' + (online ? 'online' : 'offline');
    netLabel.textContent = online ? 'Online' : 'Offline';
  }
  if (aiDot) {
    const aiReady = AppState.tutor && AppState.tutor.isAvailable();
    aiDot.className = 'status-dot ' + (aiReady ? 'ai-on' : 'ai-off');
    aiLabel.textContent = aiReady ? 'AI' : 'AI Off';
  }
}

// ============== Toast ==============

let _toastTimer = null;
function showToast(msg, duration = 2500) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.classList.add('show');
  clearTimeout(_toastTimer);
  _toastTimer = setTimeout(() => el.classList.remove('show'), duration);
}

// ============== Loading Overlay ==============

function showLoading(msg) {
  const el = document.getElementById('loading-overlay');
  el.querySelector('p').textContent = msg || 'Loading...';
  el.style.display = 'flex';
}

function hideLoading() {
  document.getElementById('loading-overlay').style.display = 'none';
}

// ============== Simple Markdown Renderer ==============

function renderMarkdown(text) {
  if (!text) return '';
  let html = text
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    // Headers
    .replace(/^### (.+)$/gm, '<h3>$1</h3>')
    .replace(/^## (.+)$/gm, '<h2>$1</h2>')
    .replace(/^# (.+)$/gm, '<h1>$1</h1>')
    // Bold + italic
    .replace(/\*\*\*(.+?)\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.+?)\*/g, '<em>$1</em>')
    // Inline code
    .replace(/`(.+?)`/g, '<code>$1</code>')
    // Blockquotes
    .replace(/^&gt; (.+)$/gm, '<blockquote>$1</blockquote>')
    // Unordered lists
    .replace(/^- (.+)$/gm, '<li>$1</li>')
    // Line breaks
    .replace(/\n\n/g, '</p><p>')
    .replace(/\n/g, '<br>');

  // Wrap consecutive <li> in <ul>
  html = html.replace(/((?:<li>.*?<\/li>\s*)+)/g, '<ul>$1</ul>');

  return `<p>${html}</p>`;
}

// ============== Practice State Persistence ==============

async function savePracticeState() {
  if (!AppState.currentPlan) return;
  const state = {
    questionIds: AppState.currentPlan.questions.map(q => q.id),
    questionIdx: AppState.currentQuestionIdx,
    showResult: AppState.showResult,
    lastAnswer: AppState.lastAnswer ? {
      user_answer: AppState.lastAnswer.user_answer,
      is_correct: AppState.lastAnswer.is_correct,
      time_taken: AppState.lastAnswer.time_taken,
      question_id: AppState.lastAnswer.question.id,
    } : null,
    sessionLogs: AppState.sessionLogs,
  };
  await DB.saveSession('practice_state', JSON.stringify(state));
}

async function restorePracticeState() {
  try {
    const raw = await DB.loadSession('practice_state');
    if (!raw) return;
    const state = JSON.parse(raw);
    const questions = [];
    for (const id of state.questionIds) {
      const q = await DB.getQuestion(id);
      if (q) questions.push(q);
    }
    if (!questions.length) { await clearPracticeState(); return; }

    AppState.currentPlan = { questions, estimatedTime: questions.length * 2, focusTags: [], createdAt: '' };
    AppState.currentQuestionIdx = state.questionIdx || 0;
    AppState.showResult = state.showResult || false;
    AppState.sessionLogs = state.sessionLogs || [];

    if (state.lastAnswer) {
      const q = questions.find(q => q.id === state.lastAnswer.question_id);
      AppState.lastAnswer = { ...state.lastAnswer, question: q };
    }
  } catch (e) {
    await clearPracticeState();
  }
}

async function clearPracticeState() {
  await DB.deleteSession('practice_state');
  AppState.currentPlan = null;
  AppState.currentQuestionIdx = 0;
  AppState.sessionLogs = [];
  AppState.showResult = false;
  AppState.lastAnswer = null;
  AppState.questionStartTime = null;
}

// ============== Dashboard Page ==============

async function renderDashboard() {
  const container = document.getElementById('page-dashboard');
  const stats = await DB.getStats();
  const typeCounts = await DB.getQuestionCountsByType();

  if (stats.total_questions === 0) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📚</div>
        <p>Question bank is empty. Reload the page to import questions.</p>
        <button class="btn btn-primary" onclick="location.reload()">Reload</button>
      </div>`;
    return;
  }

  const recs = await AppState.scheduler.getRecommendedFocus();
  const progress = await AppState.scheduler.getProgressSummary();

  // Build type options
  const typeOptions = [];
  if (typeCounts.CR > 0) typeOptions.push({ label: 'CR Logic', value: 'CR' });
  if (typeCounts.RC > 0) typeOptions.push({ label: 'RC Reading', value: 'RC' });
  if (typeOptions.length > 1) typeOptions.push({ label: 'Mix', value: '' });

  let html = '';

  // Quick stats
  html += `<div class="metrics-row">
    <div class="metric"><div class="metric-value">${stats.total_attempts}</div><div class="metric-label">Practiced</div></div>
    <div class="metric"><div class="metric-value">${stats.overall_accuracy}%</div><div class="metric-label">Accuracy</div></div>
    <div class="metric"><div class="metric-value">${stats.total_questions}</div><div class="metric-label">Questions</div></div>
  </div>`;

  // Recommendation
  html += `<div class="card"><div class="alert alert-info">${escapeHtml(recs.message)}</div>`;
  if (recs.primaryFocus) {
    const pf = recs.primaryFocus;
    html += `<p style="font-size:0.85rem"><strong>Focus:</strong> <code>${pf.tag}</code> &mdash; ${pf.accuracy ? pf.accuracy.toFixed(1) : 0}% accuracy (${pf.attempts} attempts)</p>`;
  }
  html += `</div>`;

  // Practice setup
  html += `<div class="card">
    <div class="card-title">Start Practice</div>
    <div class="pill-group" id="dash-type-pills">`;
  typeOptions.forEach((opt, i) => {
    html += `<div class="pill ${i === 0 ? 'active' : ''}" data-value="${opt.value}" onclick="selectDashType(this)">${opt.label}</div>`;
  });
  html += `</div>
    <div id="dash-skill-tag-area"></div>
    <div class="form-group">
      <label>Number of questions</label>
      <div class="number-stepper">
        <button onclick="stepNum('dash-q-count',-5)">-</button>
        <div class="num-value" id="dash-q-count">10</div>
        <button onclick="stepNum('dash-q-count',5)">+</button>
      </div>
    </div>
    <button class="btn btn-primary" onclick="startPractice()">Start Practice</button>
  </div>`;

  // Accuracy by type
  if (Object.keys(stats.accuracy_by_type).length) {
    html += `<div class="section-title">Category Accuracy</div><div class="metrics-row">`;
    for (const [sub, data] of Object.entries(stats.accuracy_by_type).sort()) {
      const label = sub === 'RC' ? 'RC Reading' : 'CR Logic';
      html += `<div class="metric"><div class="metric-value">${data.accuracy}%</div><div class="metric-label">${label} (${data.correct}/${data.total})</div></div>`;
    }
    html += `</div>`;
  }

  // Tag performance grid
  if (progress.tagPerformance.length) {
    html += `<div class="section-title">Skill Overview</div><div class="tag-grid">`;
    progress.tagPerformance.slice(0, 8).forEach(tp => {
      html += `<div class="tag-card ${tp.status}">
        <div class="tag-name">${tp.tag}</div>
        <div class="tag-accuracy">${tp.accuracy}%</div>
        <div class="tag-attempts">${tp.attempts} attempts</div>
      </div>`;
    });
    html += `</div>`;
  }

  // Daily trend
  if (progress.dailyTrend.length) {
    html += `<div class="section-title">Last 7 Days</div>
      <div class="chart-container"><canvas id="dash-trend-chart"></canvas></div>`;
  }

  container.innerHTML = html;

  // Load skill tags for default type
  if (typeOptions.length) {
    await loadDashSkillTags(typeOptions[0].value);
  }

  // Draw trend chart
  if (progress.dailyTrend.length) {
    drawTrendChart('dash-trend-chart', progress.dailyTrend);
  }
}

let _dashSelectedType = '';
let _dashSelectedSkillTag = null;

async function selectDashType(el) {
  el.parentElement.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  _dashSelectedType = el.dataset.value;
  _dashSelectedSkillTag = null;
  await loadDashSkillTags(_dashSelectedType);
}

async function loadDashSkillTags(subcategory) {
  _dashSelectedType = subcategory;
  const area = document.getElementById('dash-skill-tag-area');
  if (!subcategory) { area.innerHTML = ''; return; }

  const tags = await DB.getSkillTagsBySubcategory(subcategory);
  if (!tags.length) { area.innerHTML = ''; return; }

  let html = `<div class="form-group"><label>Skill type</label><div class="pill-group">`;
  html += `<div class="pill active" data-value="" onclick="selectDashSkillTag(this)">All</div>`;
  tags.forEach(t => {
    html += `<div class="pill" data-value="${t}" onclick="selectDashSkillTag(this)">${t}</div>`;
  });
  html += `</div></div>`;
  area.innerHTML = html;
}

function selectDashSkillTag(el) {
  el.parentElement.querySelectorAll('.pill').forEach(p => p.classList.remove('active'));
  el.classList.add('active');
  _dashSelectedSkillTag = el.dataset.value || null;
}

function stepNum(id, delta) {
  const el = document.getElementById(id);
  let val = parseInt(el.textContent) + delta;
  val = Math.max(5, Math.min(50, val));
  el.textContent = val;
}

async function startPractice() {
  const count = parseInt(document.getElementById('dash-q-count').textContent);
  const subcategory = _dashSelectedType || null;
  const skillTag = _dashSelectedSkillTag || null;

  showLoading('Generating plan...');
  const plan = await AppState.scheduler.generateDailyPlan(count, subcategory, skillTag);
  hideLoading();

  if (!plan.questions.length) {
    showToast('No questions available for this selection.');
    return;
  }

  AppState.currentPlan = plan;
  AppState.currentQuestionIdx = 0;
  AppState.sessionLogs = [];
  AppState.showResult = false;
  AppState.lastAnswer = null;
  AppState.questionStartTime = null;
  AppState.scheduler.resetSession();
  AppState.aiCache = {};

  await savePracticeState();
  navigateTo('practice');
}

// ============== Practice Page ==============

async function renderPractice() {
  const container = document.getElementById('page-practice');
  const plan = AppState.currentPlan;

  // No active plan
  if (!plan || !plan.questions.length) {
    container.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">📝</div>
        <p>No active practice session.</p>
        <button class="btn btn-primary" onclick="navigateTo('dashboard')">Go to Dashboard</button>
      </div>`;
    return;
  }

  // Session complete
  if (AppState.currentQuestionIdx >= plan.questions.length) {
    await renderSessionSummary(container);
    return;
  }

  const q = plan.questions[AppState.currentQuestionIdx];
  const idx = AppState.currentQuestionIdx;
  const total = plan.questions.length;

  // Start timer
  if (!AppState.questionStartTime && !AppState.showResult) {
    AppState.questionStartTime = Date.now();
  }

  let html = '';

  // Progress bar
  const progressPct = (idx / total * 100).toFixed(0);
  html += `<div class="progress-container">
    <div class="progress-bar"><div class="progress-fill" style="width:${progressPct}%"></div></div>
    <div class="progress-text">Question ${idx + 1} / ${total}</div>
  </div>`;

  // Question metadata
  const typeLabel = q.subcategory === 'RC' ? 'RC Reading' : 'CR Logic';
  html += `<div class="question-meta">
    <span class="tag tag-type">${typeLabel}</span>`;
  (q.skill_tags || []).forEach(t => { html += `<span class="tag tag-skill">${t}</span>`; });
  html += `<span class="tag tag-diff">${'★'.repeat(q.difficulty || 3)}</span></div>`;

  // Question content - handle RC passage separately
  if (q.subcategory === 'RC' && q.question_stem && q.content.includes(q.question_stem)) {
    const passageText = q.content.substring(0, q.content.indexOf(q.question_stem)).trim();
    if (passageText) {
      html += `<div class="rc-passage">
        <div class="rc-passage-header">📖 Passage</div>
        <div class="rc-passage-body">${escapeHtml(passageText)}</div>
      </div>`;
    }
    html += `<div class="question-stem">${escapeHtml(q.question_stem)}</div>`;
  } else {
    html += `<div class="question-content">${escapeHtml(q.content)}</div>`;
  }

  if (!AppState.showResult) {
    // Show options
    const letters = ['A', 'B', 'C', 'D', 'E'];
    q.options.forEach((opt, i) => {
      html += `<button class="option-btn" onclick="submitAnswer(${i})">
        <span class="option-letter">${letters[i]}.</span>${escapeHtml(opt)}
      </button>`;
    });
  } else {
    // Show result
    html += renderResultView(q);
  }

  container.innerHTML = html;
}

function submitAnswer(answerIdx) {
  const q = AppState.currentPlan.questions[AppState.currentQuestionIdx];
  const timeTaken = Math.round((Date.now() - AppState.questionStartTime) / 1000);
  const isCorrect = answerIdx === q.correct_answer;

  AppState.lastAnswer = {
    user_answer: answerIdx,
    is_correct: isCorrect,
    time_taken: timeTaken,
    question: q,
  };
  AppState.showResult = true;
  AppState.questionStartTime = null;

  savePracticeState();
  renderPractice();
}

function renderResultView(q) {
  const result = AppState.lastAnswer;
  const letters = ['A', 'B', 'C', 'D', 'E'];
  let html = '';

  // Result banner
  if (result.is_correct) {
    html += `<div class="result-banner correct">✅ Correct! (${result.time_taken}s)</div>`;
  } else {
    html += `<div class="result-banner wrong">❌ Wrong! Answer: <strong>${letters[q.correct_answer]}</strong>, you chose: <strong>${letters[result.user_answer]}</strong></div>`;
  }

  // Options with highlights
  q.options.forEach((opt, i) => {
    let cls = 'option-btn ';
    let prefix = '';
    if (i === q.correct_answer) { cls += 'correct'; prefix = '✅ '; }
    else if (i === result.user_answer && !result.is_correct) { cls += 'wrong'; prefix = '❌ '; }
    else { cls += 'neutral'; }
    html += `<div class="${cls}"><span class="option-letter">${prefix}${letters[i]}.</span>${escapeHtml(opt)}</div>`;
  });

  // OG Explanation
  const ogExp = q.explanation || '';
  const hasOgExp = ogExp.trim() && !ogExp.trim().startsWith('OG Type:');
  if (hasOgExp) {
    html += `<div class="expandable" id="exp-og">
      <div class="expandable-header" onclick="toggleExpandable('exp-og')">📖 OG Explanation <span class="arrow">▶</span></div>
      <div class="expandable-body ai-content">${renderMarkdown(ogExp)}</div>
    </div>`;
  }

  // AI Explanation
  const aiCacheKey = `exp_${q.id}_${result.user_answer}`;
  html += `<div class="expandable open" id="exp-ai">
    <div class="expandable-header" onclick="toggleExpandable('exp-ai')">🤖 AI Explanation <span class="arrow">▶</span></div>
    <div class="expandable-body ai-content" id="ai-exp-content">`;
  if (AppState.aiCache[aiCacheKey]) {
    html += renderMarkdown(AppState.aiCache[aiCacheKey]);
  } else {
    html += `<div><span class="spinner"></span>Loading...</div>`;
  }
  html += `</div></div>`;

  // Translation
  const transCacheKey = `trans_${q.id}`;
  html += `<div class="expandable" id="exp-trans">
    <div class="expandable-header" onclick="toggleExpandable('exp-trans')">🌐 Translation <span class="arrow">▶</span></div>
    <div class="expandable-body ai-content" id="ai-trans-content">`;
  if (AppState.aiCache[transCacheKey]) {
    html += renderMarkdown(AppState.aiCache[transCacheKey]);
  } else {
    html += `<button class="btn btn-secondary btn-small" onclick="loadTranslation(${q.id})">Load Translation</button>`;
  }
  html += `</div></div>`;

  // Error tagging (only for wrong answers)
  if (!result.is_correct) {
    html += renderErrorTagging();
  }

  // Next button
  html += `<div style="margin-top:16px">
    <button class="btn btn-primary" onclick="nextQuestion()">Next Question →</button>
  </div>`;

  // Trigger AI explanation loading (async)
  if (!AppState.aiCache[aiCacheKey]) {
    setTimeout(() => loadAIExplanation(q, result.user_answer, result.is_correct), 100);
  }

  return html;
}

function toggleExpandable(id) {
  document.getElementById(id).classList.toggle('open');
}

async function loadAIExplanation(question, userAnswer, isCorrect) {
  const cacheKey = `exp_${question.id}_${userAnswer}`;
  const el = document.getElementById('ai-exp-content');
  if (!el || AppState.aiCache[cacheKey]) return;

  if (!AppState.tutor.isAvailable()) {
    // Fallback
    const text = AppState.tutor._fallbackExplanation(question, userAnswer);
    AppState.aiCache[cacheKey] = text;
    el.innerHTML = renderMarkdown(text);
    return;
  }

  // Stream
  let fullText = '';
  try {
    el.innerHTML = '<span class="streaming-cursor"></span>';
    for await (const chunk of AppState.tutor.explainQuestionStream(question, userAnswer, isCorrect)) {
      fullText += chunk;
      el.innerHTML = renderMarkdown(fullText) + '<span class="streaming-cursor"></span>';
    }
    el.innerHTML = renderMarkdown(fullText);
    AppState.aiCache[cacheKey] = fullText;
  } catch (e) {
    const fallback = AppState.tutor._fallbackExplanation(question, userAnswer);
    el.innerHTML = renderMarkdown(fallback + `\n\n> ⚠️ AI Error: ${e.message}`);
    AppState.aiCache[cacheKey] = fallback;
  }
}

async function loadTranslation(questionId) {
  const cacheKey = `trans_${questionId}`;
  const el = document.getElementById('ai-trans-content');
  if (!el) return;

  const question = await DB.getQuestion(questionId);
  if (!question) return;

  if (!AppState.tutor.isAvailable()) {
    el.innerHTML = `<div class="alert alert-warning">⚠️ Translation requires internet and API Key.</div>`;
    return;
  }

  let fullText = '';
  try {
    el.innerHTML = '<span class="spinner"></span>Translating...';
    for await (const chunk of AppState.tutor.translateQuestionStream(question)) {
      fullText += chunk;
      el.innerHTML = renderMarkdown(fullText) + '<span class="streaming-cursor"></span>';
    }
    el.innerHTML = renderMarkdown(fullText);
    AppState.aiCache[cacheKey] = fullText;
  } catch (e) {
    el.innerHTML = `<div class="alert alert-danger">Translation failed: ${e.message}</div>`;
  }
}

function renderErrorTagging() {
  const tax = ERROR_TAXONOMY;
  const cats = Object.keys(tax);

  let html = `<div class="error-tag-section">
    <h3>📝 Error Attribution</h3>
    <p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:10px">Why did you get this wrong?</p>
    <div class="select-group">
      <label>Error Category</label>
      <select id="error-category" onchange="updateErrorDetails()">`;
  cats.forEach(c => {
    html += `<option value="${c}">${c} - ${tax[c].description.substring(0, 20)}...</option>`;
  });
  html += `</select></div>
    <div class="select-group">
      <label>Specific Reason</label>
      <select id="error-detail">`;
  Object.keys(tax[cats[0]].types).forEach(t => {
    html += `<option value="${t}">${t}</option>`;
  });
  html += `</select></div>
    <div class="remedy-tip" id="remedy-tip">💡 ${tax[cats[0]].remedy}</div>
  </div>`;
  return html;
}

function updateErrorDetails() {
  const cat = document.getElementById('error-category').value;
  const detailSelect = document.getElementById('error-detail');
  const tax = ERROR_TAXONOMY[cat];

  detailSelect.innerHTML = '';
  Object.keys(tax.types).forEach(t => {
    detailSelect.innerHTML += `<option value="${t}">${t}</option>`;
  });
  document.getElementById('remedy-tip').textContent = '💡 ' + tax.remedy;
}

async function nextQuestion() {
  const q = AppState.currentPlan.questions[AppState.currentQuestionIdx];
  const result = AppState.lastAnswer;

  let errorCategory = null;
  let errorDetail = null;
  if (!result.is_correct) {
    const catEl = document.getElementById('error-category');
    const detEl = document.getElementById('error-detail');
    if (catEl) errorCategory = catEl.value;
    if (detEl) errorDetail = detEl.value;
  }

  // Save study log
  const log = {
    question_id: q.id,
    user_answer: result.user_answer,
    is_correct: result.is_correct,
    time_taken: result.time_taken,
    error_category: errorCategory,
    error_detail: errorDetail,
    timestamp: new Date().toISOString(),
  };
  await DB.addStudyLog(log);
  AppState.sessionLogs.push(log);

  // Auto-sync (non-blocking)
  autoSyncToCloud();

  // Check emergency drill
  const drill = AppState.scheduler.recordAnswer(q, result.is_correct);
  if (drill) {
    showToast(`⚠️ Consecutive errors in '${drill.tag}'`, 3000);
  }

  // Advance
  AppState.currentQuestionIdx++;
  AppState.showResult = false;
  AppState.lastAnswer = null;
  AppState.questionStartTime = null;

  if (AppState.currentQuestionIdx < AppState.currentPlan.questions.length) {
    await savePracticeState();
  } else {
    await clearPracticeState();
  }

  renderPractice();
  window.scrollTo(0, 0);
}

// ============== Session Summary ==============

async function renderSessionSummary(container) {
  const logs = AppState.sessionLogs;
  if (!logs.length) {
    container.innerHTML = `<div class="empty-state"><p>No records.</p>
      <button class="btn btn-primary" onclick="goToDashboard()">Back to Dashboard</button></div>`;
    return;
  }

  const total = logs.length;
  const correct = logs.filter(l => l.is_correct).length;
  const accuracy = total > 0 ? (correct / total * 100).toFixed(1) : 0;
  const avgTime = total > 0 ? Math.round(logs.reduce((s, l) => s + l.time_taken, 0) / total) : 0;

  let html = `<div class="section-title">🎉 Practice Complete!</div>`;

  html += `<div class="metrics-row">
    <div class="metric"><div class="metric-value">${total}</div><div class="metric-label">Total</div></div>
    <div class="metric"><div class="metric-value">${correct}</div><div class="metric-label">Correct</div></div>
    <div class="metric"><div class="metric-value">${accuracy}%</div><div class="metric-label">Accuracy</div></div>
    <div class="metric"><div class="metric-value">${avgTime}s</div><div class="metric-label">Avg Time</div></div>
  </div>`;

  // AI Summary
  html += `<div class="card"><div class="card-title">🤖 AI Summary</div>
    <div class="ai-content" id="session-summary-content"><span class="spinner"></span>Generating...</div></div>`;

  html += `<div class="btn-row">
    <button class="btn btn-secondary" onclick="navigateTo('progress')">📊 Progress</button>
    <button class="btn btn-primary" onclick="goToDashboard()">🔄 New Session</button>
  </div>`;

  container.innerHTML = html;

  // Generate summary
  const questionsMap = {};
  AppState.currentPlan.questions.forEach(q => { questionsMap[q.id] = q; });
  const summaryEl = document.getElementById('session-summary-content');
  try {
    const summary = await AppState.tutor.generateSessionSummary(logs, questionsMap);
    summaryEl.innerHTML = renderMarkdown(summary);
  } catch (e) {
    summaryEl.innerHTML = renderMarkdown(AppState.tutor._fallbackSummary(
      total, correct, parseFloat(accuracy), avgTime, []
    ));
  }
}

async function goToDashboard() {
  await clearPracticeState();
  navigateTo('dashboard');
}

// ============== Progress Page ==============

async function renderProgress() {
  const container = document.getElementById('page-progress');
  const progress = await AppState.scheduler.getProgressSummary();

  let html = `<div class="section-title">📊 Progress Tracking</div>`;

  html += `<div class="metrics-row">
    <div class="metric"><div class="metric-value">${progress.totalAttempts}</div><div class="metric-label">Total Practice</div></div>
    <div class="metric"><div class="metric-value">${progress.overallAccuracy}%</div><div class="metric-label">Accuracy</div></div>
  </div>`;

  // Accuracy by type
  if (Object.keys(progress.accuracyByType).length) {
    html += `<div class="metrics-row">`;
    for (const [sub, data] of Object.entries(progress.accuracyByType).sort()) {
      const label = sub === 'RC' ? 'RC Reading' : 'CR Logic';
      html += `<div class="metric"><div class="metric-value">${data.accuracy}%</div><div class="metric-label">${label} (${data.correct}/${data.total})</div></div>`;
    }
    html += `</div>`;
  }

  // Tag performance table
  html += `<div class="section-title">📈 Skill Performance</div>`;
  if (progress.tagPerformance.length) {
    html += `<div class="overflow-scroll"><table class="data-table">
      <thead><tr><th>Skill</th><th>Accuracy</th><th>Attempts</th><th>Weight</th><th>Status</th></tr></thead><tbody>`;
    progress.tagPerformance.forEach(tp => {
      const statusEmoji = tp.status === 'weak' ? '🔴' : tp.status === 'improving' ? '🟡' : '🟢';
      html += `<tr class="${tp.status}"><td>${tp.tag}</td><td>${tp.accuracy}%</td><td>${tp.attempts}</td><td>${tp.weight}</td><td>${statusEmoji} ${tp.status}</td></tr>`;
    });
    html += `</tbody></table></div>`;
  } else {
    html += `<div class="alert alert-info">No practice data yet.</div>`;
  }

  // Error analysis
  html += `<div class="section-title">🔍 Error Analysis</div>`;
  const logs = await DB.getStudyLogs(200);
  const errorLogs = logs.filter(l => !l.is_correct && l.error_category);

  if (errorLogs.length) {
    const errorCounts = {};
    errorLogs.forEach(l => {
      errorCounts[l.error_category] = (errorCounts[l.error_category] || 0) + 1;
    });

    html += `<div class="chart-container"><canvas id="error-chart"></canvas></div>`;
    // Also show as list
    html += `<div class="card">`;
    Object.entries(errorCounts).sort((a, b) => b[1] - a[1]).forEach(([cat, count]) => {
      const pct = (count / errorLogs.length * 100).toFixed(0);
      html += `<div style="display:flex;justify-content:space-between;padding:6px 0;border-bottom:1px solid var(--border)">
        <span>${cat}</span><strong>${count} (${pct}%)</strong></div>`;
    });
    html += `</div>`;

    container.innerHTML = html;
    drawBarChart('error-chart', errorCounts);
  } else {
    html += `<div class="alert alert-info">No error attribution data yet. Tag your errors after answering to see analysis.</div>`;
    container.innerHTML = html;
  }

  // Daily trend
  if (progress.dailyTrend.length) {
    const trendHtml = `<div class="section-title">📈 Last 7 Days</div>
      <div class="chart-container"><canvas id="progress-trend-chart"></canvas></div>`;
    container.innerHTML += trendHtml;
    drawTrendChart('progress-trend-chart', progress.dailyTrend);
  }

  // Export button
  if (progress.totalAttempts > 0) {
    container.innerHTML += `<div style="margin-top:16px">
      <button class="btn btn-secondary btn-small" onclick="exportCSV()">📊 Export Study Logs (CSV)</button>
    </div>`;
  }
}

// ============== Settings Page ==============

async function renderSettings() {
  const container = document.getElementById('page-settings');
  const stats = await DB.getStats();

  const providerPresets = {
    'volc-coding': { label: 'Volcano Coding Plan', base_url: 'https://ark.cn-beijing.volces.com/api/coding/v3', model: 'ark-code-latest' },
    'volc-std': { label: 'Volcano Standard', base_url: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seed-1-6-251015' },
    'deepseek': { label: 'DeepSeek', base_url: 'https://api.deepseek.com', model: 'deepseek-chat' },
    'moonshot': { label: 'Moonshot', base_url: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-8k' },
    'openai': { label: 'OpenAI', base_url: '', model: 'gpt-4o-mini' },
    'custom': { label: 'Custom', base_url: '', model: '' },
  };

  let html = '';

  // AI Config
  html += `<div class="settings-section">
    <h2>🤖 AI Configuration</h2>
    <div class="form-group">
      <label>AI Provider</label>
      <select id="set-provider" onchange="onProviderChange()">`;
  // Detect current provider from saved base_url
  const savedUrl = AppState.tutor.baseUrl || '';
  let currentProvider = 'custom';
  for (const [key, p] of Object.entries(providerPresets)) {
    if (p.base_url && savedUrl.includes(p.base_url.replace(/\/v\d+$/, ''))) {
      currentProvider = key;
      break;
    }
  }
  for (const [key, p] of Object.entries(providerPresets)) {
    const sel = key === currentProvider ? ' selected' : '';
    html += `<option value="${key}"${sel}>${p.label}</option>`;
  }
  html += `</select></div>
    <div class="form-group">
      <label>API Key</label>
      <input type="password" id="set-api-key" value="${escapeHtml(AppState.tutor.apiKey || '')}" placeholder="Enter your API Key">
    </div>
    <div class="form-group">
      <label>Model Name</label>
      <input type="text" id="set-model" value="${escapeHtml(AppState.tutor.model || '')}" placeholder="e.g. gpt-4o-mini">
    </div>
    <div class="form-group" id="set-base-url-group">
      <label>API Base URL</label>
      <input type="text" id="set-base-url" value="${escapeHtml(AppState.tutor.baseUrl || '')}" placeholder="e.g. https://api.deepseek.com">
    </div>
    <div class="form-group">
      <label>CORS Proxy URL</label>
      <input type="text" id="set-proxy-url" value="${escapeHtml(AppState.tutor.proxyUrl || '')}" placeholder="e.g. https://your-worker.workers.dev">
      <div class="hint">Required for Volcano/DeepSeek etc. Deploy Cloudflare Worker as proxy. Leave empty for OpenAI.</div>
    </div>
    <button class="btn btn-primary" onclick="saveAndTestAI()">Save & Test Connection</button>
    <div id="ai-test-result" style="margin-top:10px"></div>
  </div>`;

  html += `<div class="divider"></div>`;

  // Cloud Sync
  html += `<div class="settings-section">
    <h2>☁️ Cloud Sync</h2>
    <p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:10px">
      Sync with Streamlit version via GitHub Gist. Use the same token as Streamlit.
    </p>
    <div class="form-group">
      <label>GitHub Token</label>
      <input type="password" id="set-github-token" value="${escapeHtml(localStorage.getItem('github_token') || '')}" placeholder="ghp_xxxxx">
      <div class="hint">Create at GitHub Settings → Developer settings → Personal access tokens (gist scope)</div>
    </div>
    <button class="btn btn-secondary btn-small" onclick="saveGitHubToken()" style="margin-bottom:10px">Save Token</button>

    <h3 style="margin:16px 0 8px;font-size:0.95rem">🔄 Streamlit Cross-Sync</h3>
    <p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:8px">
      Download study data from Streamlit, or upload offline records back to Streamlit.
    </p>
    <div class="btn-row">
      <button class="btn btn-primary btn-small" onclick="syncToStreamlit()">📤 Upload to Streamlit</button>
      <button class="btn btn-secondary btn-small" onclick="syncFromStreamlit()">📥 Sync from Streamlit</button>
    </div>
    <div id="cross-sync-result" style="margin-top:10px"></div>

    <h3 style="margin:16px 0 8px;font-size:0.95rem">💾 PWA Full Backup</h3>
    <p style="font-size:0.8rem;color:var(--text-secondary);margin-bottom:8px">
      Full backup/restore for PWA standalone use.
    </p>
    <div class="btn-row">
      <button class="btn btn-primary btn-small" onclick="uploadToCloud()">📤 Backup</button>
      <button class="btn btn-secondary btn-small" onclick="downloadFromCloud()">📥 Restore</button>
    </div>
    <div id="sync-result" style="margin-top:10px"></div>
  </div>`;

  html += `<div class="divider"></div>`;

  // Scheduler Config
  const schCfg = AppState.scheduler.config;
  html += `<div class="settings-section">
    <h2>📅 Scheduler Configuration</h2>
    <div class="form-group">
      <label>Default daily questions</label>
      <div class="number-stepper">
        <button onclick="stepNum('sch-daily',-5)">-</button>
        <div class="num-value" id="sch-daily">${schCfg.defaultQuestionCount}</div>
        <button onclick="stepNum('sch-daily',5)">+</button>
      </div>
    </div>
    <div class="form-group">
      <label>Max consecutive same-tag questions</label>
      <div class="number-stepper">
        <button onclick="stepNum('sch-consec',-1)">-</button>
        <div class="num-value" id="sch-consec">${schCfg.maxConsecutiveSameTag}</div>
        <button onclick="stepNum('sch-consec',1)">+</button>
      </div>
    </div>
    <div class="form-group">
      <label>Keep-alive quota: <strong id="sch-keep-label">${Math.round(schCfg.keepAliveQuota * 100)}%</strong></label>
      <input type="range" id="sch-keep" min="5" max="30" value="${Math.round(schCfg.keepAliveQuota * 100)}"
        oninput="document.getElementById('sch-keep-label').textContent=this.value+'%'"
        style="width:100%">
      <div class="hint">Percentage of questions from mastered topics to keep them fresh</div>
    </div>
    <button class="btn btn-primary btn-small" onclick="saveSchedulerSettings()">Save Scheduler Config</button>
  </div>`;

  html += `<div class="divider"></div>`;

  // Data Management
  html += `<div class="settings-section">
    <h2>🗃️ Data Management</h2>
    <div class="alert alert-info">
      Questions: ${stats.total_questions} | Practice records: ${stats.total_attempts}
    </div>
    <div class="btn-row" style="margin-bottom:8px">
      <button class="btn btn-secondary btn-small" onclick="exportCSV()">📊 Export CSV</button>
      <button class="btn btn-secondary btn-small" onclick="exportData()">📥 Export JSON</button>
    </div>
    <button class="btn btn-danger btn-small" onclick="resetData()" style="width:100%">🗑️ Reset All Practice Data</button>
  </div>`;

  // Version info
  html += `<div style="text-align:center;padding:20px;color:var(--text-secondary);font-size:0.75rem">
    GMAT Focus AI Tutor PWA v1.0<br>Offline-capable
  </div>`;

  container.innerHTML = html;
}

function onProviderChange() {
  const presets = {
    'volc-coding': { base_url: 'https://ark.cn-beijing.volces.com/api/coding/v3', model: 'ark-code-latest' },
    'volc-std': { base_url: 'https://ark.cn-beijing.volces.com/api/v3', model: 'doubao-seed-1-6-251015' },
    'deepseek': { base_url: 'https://api.deepseek.com', model: 'deepseek-chat' },
    'moonshot': { base_url: 'https://api.moonshot.cn/v1', model: 'moonshot-v1-8k' },
    'openai': { base_url: '', model: 'gpt-4o-mini' },
    'custom': { base_url: '', model: '' },
  };

  const sel = document.getElementById('set-provider').value;
  const p = presets[sel];
  document.getElementById('set-model').value = p.model;
  document.getElementById('set-base-url').value = p.base_url;
}

async function saveSchedulerSettings() {
  const daily = parseInt(document.getElementById('sch-daily').textContent);
  const consec = parseInt(document.getElementById('sch-consec').textContent);
  const keep = parseInt(document.getElementById('sch-keep').value);
  const config = {
    defaultQuestionCount: Math.max(5, Math.min(50, daily)),
    maxConsecutiveSameTag: Math.max(1, Math.min(10, consec)),
    keepAliveQuota: keep / 100,
  };
  await saveSchedulerConfig(config);
  showToast('Scheduler config saved');
}

async function saveAndTestAI() {
  const apiKey = document.getElementById('set-api-key').value.trim();
  const model = document.getElementById('set-model').value.trim();
  const baseUrl = document.getElementById('set-base-url').value.trim();
  const proxyUrl = document.getElementById('set-proxy-url').value.trim();
  const resultEl = document.getElementById('ai-test-result');

  // Auto-correct Volcano Coding Plan URL
  let correctedBaseUrl = baseUrl;
  if (model === 'ark-code-latest' && baseUrl && !baseUrl.includes('/coding')) {
    correctedBaseUrl = 'https://ark.cn-beijing.volces.com/api/coding/v3';
    document.getElementById('set-base-url').value = correctedBaseUrl;
  }

  AppState.tutor.configure(apiKey, model, correctedBaseUrl, proxyUrl);
  await AppState.tutor.saveToDB();
  updateStatusIndicators();

  if (!apiKey) {
    resultEl.innerHTML = `<div class="alert alert-warning">Settings saved. No API Key - AI features will use built-in explanations.</div>`;
    return;
  }

  if (!navigator.onLine) {
    resultEl.innerHTML = `<div class="alert alert-warning">Settings saved. Cannot test - you are offline.</div>`;
    return;
  }

  resultEl.innerHTML = `<div><span class="spinner"></span>Testing connection...</div>`;
  const result = await AppState.tutor.testConnection();
  if (result.success) {
    resultEl.innerHTML = `<div class="alert alert-success">✅ Connected! Reply: ${escapeHtml(result.reply)}</div>`;
  } else {
    resultEl.innerHTML = `<div class="alert alert-danger">❌ Failed: ${escapeHtml(result.error)}</div>`;
  }
}

function saveGitHubToken() {
  const token = document.getElementById('set-github-token').value.trim();
  if (token) {
    localStorage.setItem('github_token', token);
    showToast('GitHub Token saved');
  } else {
    localStorage.removeItem('github_token');
    showToast('GitHub Token removed');
  }
}

// ---- Streamlit Cross-Sync ----

async function syncToStreamlit() {
  const resultEl = document.getElementById('cross-sync-result');
  const client = getGistClient();
  if (!client) {
    resultEl.innerHTML = `<div class="alert alert-warning">Please save GitHub Token first.</div>`;
    return;
  }
  if (!navigator.onLine) {
    resultEl.innerHTML = `<div class="alert alert-warning">No internet connection.</div>`;
    return;
  }

  resultEl.innerHTML = `<div><span class="spinner"></span>Uploading to Streamlit...</div>`;
  const res = await client.uploadToStreamlit();
  resultEl.innerHTML = `<div class="alert ${res.success ? 'alert-success' : 'alert-danger'}">${res.success ? '✅' : '❌'} ${escapeHtml(res.message)}</div>`;
}

async function syncFromStreamlit() {
  const resultEl = document.getElementById('cross-sync-result');
  const client = getGistClient();
  if (!client) {
    resultEl.innerHTML = `<div class="alert alert-warning">Please save GitHub Token first.</div>`;
    return;
  }
  if (!navigator.onLine) {
    resultEl.innerHTML = `<div class="alert alert-warning">No internet connection.</div>`;
    return;
  }

  resultEl.innerHTML = `<div><span class="spinner"></span>Syncing from Streamlit...</div>`;
  const res = await client.downloadFromStreamlit();
  resultEl.innerHTML = `<div class="alert ${res.success ? 'alert-success' : 'alert-danger'}">${res.success ? '✅' : '❌'} ${escapeHtml(res.message)}</div>`;
  if (res.success && res.imported > 0) {
    showToast('Data synced! Refreshing...');
    setTimeout(() => location.reload(), 1500);
  }
}

// ---- PWA Full Backup ----

async function uploadToCloud() {
  const resultEl = document.getElementById('sync-result');
  const client = getGistClient();
  if (!client) {
    resultEl.innerHTML = `<div class="alert alert-warning">Please save GitHub Token first.</div>`;
    return;
  }
  if (!navigator.onLine) {
    resultEl.innerHTML = `<div class="alert alert-warning">No internet connection.</div>`;
    return;
  }

  resultEl.innerHTML = `<div><span class="spinner"></span>Uploading...</div>`;
  const res = await client.upload();
  resultEl.innerHTML = `<div class="alert ${res.success ? 'alert-success' : 'alert-danger'}">${res.success ? '✅' : '❌'} ${escapeHtml(res.message)}</div>`;
}

async function downloadFromCloud() {
  const resultEl = document.getElementById('sync-result');
  const client = getGistClient();
  if (!client) {
    resultEl.innerHTML = `<div class="alert alert-warning">Please save GitHub Token first.</div>`;
    return;
  }
  if (!navigator.onLine) {
    resultEl.innerHTML = `<div class="alert alert-warning">No internet connection.</div>`;
    return;
  }

  resultEl.innerHTML = `<div><span class="spinner"></span>Downloading...</div>`;
  const res = await client.download();
  resultEl.innerHTML = `<div class="alert ${res.success ? 'alert-success' : 'alert-danger'}">${res.success ? '✅' : '❌'} ${escapeHtml(res.message)}</div>`;
  if (res.success) {
    showToast('Data restored! Reloading...');
    setTimeout(() => location.reload(), 1500);
  }
}

async function exportData() {
  try {
    const data = await DB.exportAllData();
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `gmat_tutor_backup_${new Date().toISOString().slice(0, 10)}.json`;
    a.click();
    URL.revokeObjectURL(url);
    showToast('Data exported');
  } catch (e) {
    showToast('Export failed: ' + e.message);
  }
}

async function resetData() {
  if (!confirm('Are you sure you want to reset all practice data? This cannot be undone.')) return;
  await DB.resetDatabase();
  showToast('Data reset');
  location.reload();
}

// ============== Simple Charts ==============

function drawTrendChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 180 * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = '180px';
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = 180;
  const padding = { top: 20, right: 20, bottom: 40, left: 40 };
  const chartW = w - padding.left - padding.right;
  const chartH = h - padding.top - padding.bottom;

  ctx.clearRect(0, 0, w, h);

  if (!data.length) return;

  const maxAcc = 100;
  const xStep = data.length > 1 ? chartW / (data.length - 1) : chartW;

  // Grid lines
  ctx.strokeStyle = '#E5E7EB';
  ctx.lineWidth = 0.5;
  for (let i = 0; i <= 4; i++) {
    const y = padding.top + (chartH / 4) * i;
    ctx.beginPath();
    ctx.moveTo(padding.left, y);
    ctx.lineTo(w - padding.right, y);
    ctx.stroke();
    ctx.fillStyle = '#9CA3AF';
    ctx.font = '10px sans-serif';
    ctx.textAlign = 'right';
    ctx.fillText((100 - 25 * i) + '%', padding.left - 5, y + 4);
  }

  // Line
  ctx.strokeStyle = '#4A90D9';
  ctx.lineWidth = 2;
  ctx.beginPath();
  data.forEach((d, i) => {
    const x = padding.left + (data.length > 1 ? i * xStep : chartW / 2);
    const y = padding.top + chartH - (d.accuracy / maxAcc) * chartH;
    if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
  });
  ctx.stroke();

  // Points
  data.forEach((d, i) => {
    const x = padding.left + (data.length > 1 ? i * xStep : chartW / 2);
    const y = padding.top + chartH - (d.accuracy / maxAcc) * chartH;
    ctx.fillStyle = '#4A90D9';
    ctx.beginPath();
    ctx.arc(x, y, 4, 0, Math.PI * 2);
    ctx.fill();

    // Date label
    ctx.fillStyle = '#9CA3AF';
    ctx.font = '9px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(d.date.slice(5), x, h - padding.bottom + 15);

    // Value label
    ctx.fillStyle = '#4A90D9';
    ctx.font = '10px sans-serif';
    ctx.fillText(d.accuracy + '%', x, y - 8);
  });
}

function drawBarChart(canvasId, data) {
  const canvas = document.getElementById(canvasId);
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const dpr = window.devicePixelRatio || 1;
  const rect = canvas.parentElement.getBoundingClientRect();
  canvas.width = rect.width * dpr;
  canvas.height = 180 * dpr;
  canvas.style.width = rect.width + 'px';
  canvas.style.height = '180px';
  ctx.scale(dpr, dpr);

  const w = rect.width;
  const h = 180;
  const padding = { top: 20, right: 20, bottom: 50, left: 10 };
  const chartW = w - padding.left - padding.right;
  const chartH = h - padding.top - padding.bottom;

  ctx.clearRect(0, 0, w, h);

  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  if (!entries.length) return;

  const maxVal = Math.max(...entries.map(e => e[1]));
  const barWidth = Math.min(60, (chartW / entries.length) * 0.7);
  const gap = (chartW - barWidth * entries.length) / (entries.length + 1);

  const colors = ['#E74C3C', '#F39C12', '#3498DB', '#27AE60', '#9B59B6'];

  entries.forEach(([label, val], i) => {
    const x = padding.left + gap + i * (barWidth + gap);
    const barH = (val / maxVal) * chartH;
    const y = padding.top + chartH - barH;

    ctx.fillStyle = colors[i % colors.length];
    ctx.beginPath();
    ctx.roundRect(x, y, barWidth, barH, 4);
    ctx.fill();

    // Value label
    ctx.fillStyle = '#333';
    ctx.font = 'bold 11px sans-serif';
    ctx.textAlign = 'center';
    ctx.fillText(val, x + barWidth / 2, y - 5);

    // Category label
    ctx.fillStyle = '#6B7280';
    ctx.font = '9px sans-serif';
    ctx.save();
    ctx.translate(x + barWidth / 2, h - padding.bottom + 10);
    ctx.rotate(-0.3);
    ctx.fillText(label.length > 12 ? label.slice(0, 12) + '...' : label, 0, 0);
    ctx.restore();
  });
}

// ============== Utilities ==============

function escapeHtml(text) {
  if (!text) return '';
  const div = document.createElement('div');
  div.textContent = text;
  return div.innerHTML;
}

// ============== Boot ==============

document.addEventListener('DOMContentLoaded', initApp);

// Register service worker
if ('serviceWorker' in navigator) {
  navigator.serviceWorker.register('./sw.js').then(() => {
    console.log('Service Worker registered');
  }).catch(err => {
    console.warn('SW registration failed:', err);
  });
}
