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

    // Get all attempted question IDs to exclude them
    const attemptedIds = await this._getAttemptedIds();

    // Split into unseen and seen questions
    const unseenQuestions = allQuestions.filter(q => !attemptedIds.has(q.id));
    const seenQuestions = allQuestions.filter(q => attemptedIds.has(q.id));

    const selectedIds = new Set();
    let selected = [];

    if (unseenQuestions.length >= targetCount) {
      // Enough unseen questions: use only unseen, weighted by weakness
      const weakQ = this._weightedSample(unseenQuestions, weaknesses, targetCount, selectedIds);
      selected = selected.concat(weakQ);
    } else {
      // Not enough unseen: use all unseen + fill from seen (prioritize incorrect)
      selected = selected.concat(unseenQuestions);
      unseenQuestions.forEach(q => selectedIds.add(q.id));

      const remaining = targetCount - selected.length;
      if (remaining > 0) {
        // Fill from seen questions, weighted by weakness (incorrect ones have higher weight)
        const fill = this._weightedSample(seenQuestions, weaknesses, remaining, selectedIds);
        selected = selected.concat(fill);
      }
    }

    // Step 4: Shuffle with constraints
    selected = this._shuffleWithConstraints(selected);

    const focusTags = this._getTopWeaknessTags(weaknesses, 3);

    return {
      questions: selected,
      estimatedTime: selected.length * 2,
      focusTags,
      createdAt: new Date().toISOString(),
    };
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
