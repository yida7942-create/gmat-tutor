/**
 * GMAT Focus AI Tutor - Scheduler
 * Port of scheduler.py: weighted random sampling + spaced repetition.
 */

const SchedulerConfig = {
  defaultQuestionCount: 20,
  maxConsecutiveSameTag: 3,
  keepAliveQuota: 0.10,
  consecutiveErrorThreshold: 3,
};

// ============== Scheduler ==============

class Scheduler {
  constructor(config) {
    this.config = Object.assign({}, SchedulerConfig, config);
    this._sessionErrors = {}; // tag -> consecutive errors
  }

  async generateDailyPlan(questionCount, subcategory, skillTag) {
    const targetCount = questionCount || this.config.defaultQuestionCount;

    let allQuestions;
    if (skillTag) {
      allQuestions = await DB.getQuestionsBySkillTag(skillTag, subcategory, 500);
    } else if (subcategory) {
      allQuestions = await DB.getQuestionsBySubcategory(subcategory, 500);
    } else {
      allQuestions = await DB.getAllQuestions();
    }

    const weaknessesArr = await DB.getAllWeaknesses();
    const weaknesses = {};
    weaknessesArr.forEach(w => { weaknesses[w.tag] = w; });

    if (!allQuestions.length) {
      return { questions: [], estimatedTime: 0, focusTags: [], createdAt: new Date().toISOString() };
    }

    const attemptedIds = await this._getAttemptedIds();

    // Separate RC and non-RC questions
    const rcQuestions = allQuestions.filter(q => q.subcategory === 'RC');
    const nonRcQuestions = allQuestions.filter(q => q.subcategory !== 'RC');

    let selected = [];
    const selectedIds = new Set();

    if (rcQuestions.length > 0 && nonRcQuestions.length === 0) {
      // Pure RC mode: select by passage groups
      selected = this._selectRCByPassage(rcQuestions, weaknesses, targetCount, attemptedIds);
    } else if (rcQuestions.length > 0) {
      // Mixed mode: select non-RC individually, then add RC passages
      const unseenNonRc = nonRcQuestions.filter(q => !attemptedIds.has(q.id));
      const seenNonRc = nonRcQuestions.filter(q => attemptedIds.has(q.id));

      // Fill most of the plan with non-RC
      const nonRcCount = Math.min(targetCount, nonRcQuestions.length);
      if (unseenNonRc.length >= nonRcCount) {
        selected = this._weightedSample(unseenNonRc, weaknesses, nonRcCount, selectedIds);
      } else {
        selected = selected.concat(unseenNonRc);
        unseenNonRc.forEach(q => selectedIds.add(q.id));
        const remaining = nonRcCount - selected.length;
        if (remaining > 0) {
          selected = selected.concat(this._weightedSample(seenNonRc, weaknesses, remaining, selectedIds));
        }
      }

      // Add RC passage groups for remaining
      const rcRemaining = targetCount - selected.length;
      if (rcRemaining > 0) {
        const rcSelected = this._selectRCByPassage(rcQuestions, weaknesses, rcRemaining, attemptedIds);
        selected = selected.concat(rcSelected);
      }
    } else {
      // No RC: original logic
      const unseen = allQuestions.filter(q => !attemptedIds.has(q.id));
      const seen = allQuestions.filter(q => attemptedIds.has(q.id));

      if (unseen.length >= targetCount) {
        selected = this._weightedSample(unseen, weaknesses, targetCount, selectedIds);
      } else {
        selected = selected.concat(unseen);
        unseen.forEach(q => selectedIds.add(q.id));
        const remaining = targetCount - selected.length;
        if (remaining > 0) {
          selected = selected.concat(this._weightedSample(seen, weaknesses, remaining, selectedIds));
        }
      }
    }

    // Shuffle non-RC questions but keep RC passage groups together
    selected = this._shuffleKeepingRCGroups(selected);

    const focusTags = this._getTopWeaknessTags(weaknesses, 3);

    return {
      questions: selected,
      estimatedTime: selected.length * 2,
      focusTags,
      createdAt: new Date().toISOString(),
    };
  }

  _getPassageKey(question) {
    if (question.subcategory !== 'RC') return null;
    const stem = question.question_stem || '';
    const content = question.content || '';
    if (stem && content.includes(stem)) {
      return content.substring(0, content.indexOf(stem)).trim().substring(0, 100);
    }
    return content.substring(0, 100);
  }

  _selectRCByPassage(rcQuestions, weaknesses, targetCount, attemptedIds) {
    // Group by passage
    const passageGroups = {};
    for (const q of rcQuestions) {
      const key = this._getPassageKey(q);
      if (!passageGroups[key]) passageGroups[key] = [];
      passageGroups[key].push(q);
    }

    // For each passage group, check if any questions are unseen
    const passageList = Object.values(passageGroups);
    const unseenPassages = passageList.filter(group =>
      group.some(q => !attemptedIds.has(q.id))
    );
    const seenPassages = passageList.filter(group =>
      group.every(q => attemptedIds.has(q.id))
    );

    // Select passages, prefer ones with unseen questions
    let selected = [];
    const pool = unseenPassages.concat(seenPassages);

    for (const group of pool) {
      if (selected.length >= targetCount) break;
      // Add all questions from this passage group
      selected = selected.concat(group);
    }

    return selected;
  }

  _shuffleKeepingRCGroups(questions) {
    // Separate into RC passage groups and non-RC individual questions
    const rcGroups = [];
    const nonRc = [];
    const seenPassages = new Set();

    for (const q of questions) {
      if (q.subcategory === 'RC') {
        const key = this._getPassageKey(q);
        if (!seenPassages.has(key)) {
          seenPassages.add(key);
          // Collect all questions from this passage in order
          const group = questions.filter(qq => qq.subcategory === 'RC' && this._getPassageKey(qq) === key);
          rcGroups.push(group);
        }
      } else {
        nonRc.push(q);
      }
    }

    // Shuffle non-RC
    for (let i = nonRc.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [nonRc[i], nonRc[j]] = [nonRc[j], nonRc[i]];
    }

    // Shuffle passage group order (but keep questions within a group in order)
    for (let i = rcGroups.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [rcGroups[i], rcGroups[j]] = [rcGroups[j], rcGroups[i]];
    }

    // Interleave: put RC groups between non-RC questions
    const result = [];
    let rcIdx = 0;
    const insertInterval = nonRc.length > 0 ? Math.max(1, Math.floor(nonRc.length / (rcGroups.length + 1))) : 0;

    for (let i = 0; i < nonRc.length; i++) {
      result.push(nonRc[i]);
      if (insertInterval > 0 && (i + 1) % insertInterval === 0 && rcIdx < rcGroups.length) {
        result.push(...rcGroups[rcIdx]);
        rcIdx++;
      }
    }
    // Append remaining RC groups
    while (rcIdx < rcGroups.length) {
      result.push(...rcGroups[rcIdx]);
      rcIdx++;
    }

    return result;
  }

  async _getAttemptedIds() {
    const allLogs = await DB.getAllStudyLogs();
    const ids = new Set();
    for (const log of allLogs) {
      ids.add(log.question_id);
    }
    return ids;
  }

  _weightedSample(questions, weaknesses, count, excludeIds) {
    let available = questions.filter(q => !excludeIds.has(q.id));
    if (!available.length) return [];

    const weights = available.map(q => {
      if (!q.skill_tags || !q.skill_tags.length) return 1.0;
      return Math.max(...q.skill_tags.map(t => (weaknesses[t] ? weaknesses[t].weight : 1.0)));
    });

    const totalWeight = weights.reduce((s, w) => s + w, 0) || available.length;
    const probs = weights.map(w => w / totalWeight);

    const selected = [];
    const indices = available.map((_, i) => i);

    for (let i = 0; i < Math.min(count, available.length); i++) {
      if (!indices.length) break;
      const currentProbs = indices.map(idx => probs[idx]);
      const totalP = currentProbs.reduce((s, p) => s + p, 0);
      const normalized = currentProbs.map(p => p / totalP);

      let r = Math.random();
      let chosenLocal = 0;
      for (let j = 0; j < normalized.length; j++) {
        r -= normalized[j];
        if (r <= 0) { chosenLocal = j; break; }
      }

      const chosenIdx = indices[chosenLocal];
      selected.push(available[chosenIdx]);
      indices.splice(chosenLocal, 1);
    }

    return selected;
  }

  _sampleFromTags(questions, tags, count, excludeIds) {
    const matching = questions.filter(q =>
      !excludeIds.has(q.id) && q.skill_tags && q.skill_tags.some(t => tags.includes(t))
    );
    return this._randomSample(matching, count);
  }

  _randomSample(arr, n) {
    const shuffled = arr.slice().sort(() => Math.random() - 0.5);
    return shuffled.slice(0, n);
  }

  _shuffleWithConstraints(questions) {
    if (questions.length <= 1) return questions;

    // Fisher-Yates shuffle
    for (let i = questions.length - 1; i > 0; i--) {
      const j = Math.floor(Math.random() * (i + 1));
      [questions[i], questions[j]] = [questions[j], questions[i]];
    }

    const max = this.config.maxConsecutiveSameTag;
    for (let i = 0; i < questions.length - max; i++) {
      const window = questions.slice(i, i + max + 1);
      let common = new Set(window[0].skill_tags || []);
      for (let k = 1; k < window.length; k++) {
        const tags = new Set(window[k].skill_tags || []);
        common = new Set([...common].filter(t => tags.has(t)));
      }

      if (common.size > 0) {
        for (let j = i + max + 1; j < questions.length; j++) {
          const candidate = questions[j];
          const candidateTags = new Set(candidate.skill_tags || []);
          if (![...common].some(t => candidateTags.has(t))) {
            [questions[i + max], questions[j]] = [questions[j], questions[i + max]];
            break;
          }
        }
      }
    }
    return questions;
  }

  _getTopWeaknessTags(weaknesses, n) {
    return Object.entries(weaknesses)
      .sort((a, b) => b[1].weight - a[1].weight)
      .slice(0, n)
      .map(([tag]) => tag);
  }

  // ============== Emergency Drill ==============

  recordAnswer(question, isCorrect) {
    if (!question.skill_tags) return null;
    for (const tag of question.skill_tags) {
      if (isCorrect) {
        this._sessionErrors[tag] = 0;
      } else {
        this._sessionErrors[tag] = (this._sessionErrors[tag] || 0) + 1;
        if (this._sessionErrors[tag] >= this.config.consecutiveErrorThreshold) {
          this._sessionErrors[tag] = 0;
          return { tag, reason: `Consecutive errors detected in '${tag}' questions` };
        }
      }
    }
    return null;
  }

  resetSession() {
    this._sessionErrors = {};
  }

  // ============== Analytics ==============

  async getRecommendedFocus() {
    const weaknesses = await DB.getAllWeaknesses();
    const stats = await DB.getStats();

    if (!weaknesses.length) {
      return {
        primaryFocus: null,
        secondaryFocus: null,
        message: 'No study history yet. Start practicing to get personalized recommendations!',
      };
    }

    const sorted = weaknesses.slice().sort((a, b) => b.weight - a.weight);
    const primary = sorted[0] || null;
    const secondary = sorted[1] || null;

    let primaryAccuracy = null;
    if (primary && primary.total_attempts > 0) {
      primaryAccuracy = (primary.total_attempts - primary.error_count) / primary.total_attempts * 100;
    }

    let message;
    if (primary && primary.weight > 2.0) {
      message = `Focus on '${primary.tag}' - your accuracy is ${primaryAccuracy.toFixed(0)}% and needs improvement.`;
    } else if (primary && primary.weight > 1.5) {
      message = `'${primary.tag}' is your weakest area at ${primaryAccuracy.toFixed(0)}% accuracy. Keep practicing!`;
    } else {
      message = 'Your skills are well-balanced. Continue with mixed practice.';
    }

    return {
      primaryFocus: primary ? {
        tag: primary.tag,
        weight: primary.weight,
        accuracy: primaryAccuracy,
        attempts: primary.total_attempts,
      } : null,
      secondaryFocus: secondary ? { tag: secondary.tag, weight: secondary.weight } : null,
      message,
      overallAccuracy: stats.overall_accuracy,
    };
  }

  async getProgressSummary() {
    const stats = await DB.getStats();
    const weaknesses = await DB.getAllWeaknesses();

    const tagPerformance = weaknesses.map(w => {
      const accuracy = w.total_attempts > 0
        ? Math.round((w.total_attempts - w.error_count) / w.total_attempts * 1000) / 10
        : 0;
      return {
        tag: w.tag,
        accuracy,
        attempts: w.total_attempts,
        weight: w.weight,
        status: w.weight > 1.5 ? 'weak' : w.weight > 1.0 ? 'improving' : 'strong',
      };
    });

    tagPerformance.sort((a, b) => b.weight - a.weight);

    return {
      totalAttempts: stats.total_attempts,
      overallAccuracy: stats.overall_accuracy,
      dailyTrend: stats.daily_trend,
      tagPerformance,
      accuracyByType: stats.accuracy_by_type,
    };
  }
}

window.Scheduler = Scheduler;
