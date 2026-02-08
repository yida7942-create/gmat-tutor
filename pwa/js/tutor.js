/**
 * GMAT Focus AI Tutor - AI Tutor Layer
 * Port of tutor.py: LLM interactions with online/offline handling.
 */

// ============== Prompt Templates ==============

const SYSTEM_PROMPT = `You are a GMAT expert tutor who has helped thousands of students achieve 99th percentile scores.

Your teaching style:
- Patient and encouraging, but rigorous
- Focus on building fundamental reasoning skills
- Use clear, structured explanations
- Help students recognize patterns and traps

Language: Always respond in the same language as the user's question or the language they prefer. If the question is in Chinese, respond in Chinese. If in English, respond in English.`;

function explanationPrompt(question, userAnswer, isCorrect) {
  const letters = ['A', 'B', 'C', 'D', 'E'];
  const qType = question.subcategory === 'RC' ? 'RC' : 'CR';
  const resultHeader = isCorrect
    ? '✅ 答对了，注意干扰项'
    : `❌ 为什么${letters[userAnswer]}错`;

  return `GMAT ${qType} 题目分析。

**题目:** ${question.content}

**选项:** A.${question.options[0]} B.${question.options[1]} C.${question.options[2]} D.${question.options[3]} E.${question.options[4]}

**正确答案:** ${letters[question.correct_answer]} | **学生选择:** ${letters[userAnswer]} | **答对:** ${isCorrect ? '是' : '否'}

请用中文简洁回答（约300字）：

## ${resultHeader}
- 指出${letters[userAnswer]}选项的具体错误（引用关键词）
- 解释学生可能的错误思路

## ✅ 正确答案逻辑
2-3句话说明${letters[question.correct_answer]}为什么对

## 📝 关键词（3个）
- **英文词** — 中文意思 — 本题作用

## 🔑 一句话
"遇到...注意...关键是..."

直接具体，不要泛泛而谈。`;
}

function translationPrompt(question) {
  return `翻译这道GMAT题目。

**题目:** ${question.content}

**选项:** A.${question.options[0]} B.${question.options[1]} C.${question.options[2]} D.${question.options[3]} E.${question.options[4]}

请按以下格式输出：

## 🌐 题目翻译
（按句翻译，先英文后中文）

## 📋 选项翻译
A. [中文]
B. [中文]
C. [中文]
D. [中文]
E. [中文]

## 🧬 长难句（1句）
**原句**: ...
**结构**: ...
**精译**: ...

保持简洁。`;
}

function summaryPrompt(total, correct, accuracy, avgTime, errorBreakdown, weakTags) {
  return `基于今天的学习记录，请生成一份简要的中文学习总结和建议。

**学习数据:**
- 完成题目: ${total}
- 正确数量: ${correct}
- 正确率: ${accuracy}%
- 平均用时: ${avgTime} 秒/题

**错误类型分布:**
${errorBreakdown}

**薄弱考点:**
${weakTags}

请输出以下内容（全部用中文）:
1. **今日点评**: 对今天表现的简要评估 (2-3句话)
2. **亮点**: 表现好的地方
3. **提升空间**: 需要重点改进的领域
4. **明日建议**: 对接下来练习的具体建议

语气要积极鼓励但实事求是。保持简洁扼要。`;
}

// ============== Error Taxonomy ==============

const ERROR_TAXONOMY = {
  Understanding: {
    description: '理解层面的错误 - 没有正确理解题目或选项的含义',
    types: {
      'Text Misinterpretation': '误解题干中的关键信息或论证结构',
      'Option Misinterpretation': '误解选项的实际含义',
    },
    remedy: '放慢阅读速度，用自己的话复述论证',
  },
  Reasoning: {
    description: '推理层面的错误 - 理解了但推理过程出错',
    types: {
      'Confusion (Suff/Nec)': '混淆充分条件和必要条件',
      'Reverse Causality': '颠倒因果关系',
      'Scope Shift': '范围转移 - 选项讨论的范围与题干不一致',
      'Trap Answer': '掉入常见陷阱选项',
    },
    remedy: '练习识别论证模式，学习常见陷阱类型',
  },
  Execution: {
    description: '执行层面的错误 - 会做但做错了',
    types: {
      'Time Pressure': '时间压力导致仓促答题',
      'Careless': '粗心大意，漏看关键词',
    },
    remedy: '练习时间管理，建立检查习惯',
  },
};

const FALLBACK_TIPS = {
  Assumption: '找假设题的关键：正确答案是论证成立的必要条件。用"否定测试"——如果否定某个选项后论证崩塌，那就是正确答案。',
  Strengthen: '加强题要找能填补论证缺口的选项。注意：好的加强选项不需要"证明"结论，只需要让结论"更可能"成立。',
  Weaken: '削弱题要攻击"前提到结论"的推理过程，而不是攻击前提本身。寻找替代解释或破坏因果链的选项。',
  Inference: '推断题要求"必然为真"。小心"大多数"≠"所有"，"有些"≠"必然"。正确选项通常比你预期的更保守。',
  Evaluate: '评估题要找能决定论证强弱的关键信息。问自己："如果知道这个信息，结论会更强还是更弱？"',
  Boldface: '粗体题先判断每个粗体部分的角色（结论？前提？反驳？），再看它们之间的逻辑关系。',
};

// ============== AI Tutor ==============

class AITutor {
  constructor() {
    this.apiKey = null;
    this.baseUrl = null;
    this.model = null;
    this.maxTokens = 800;
    this.temperature = 0.7;
  }

  configure(apiKey, model, baseUrl) {
    this.apiKey = apiKey || null;
    this.model = model || 'gpt-4o-mini';
    this.baseUrl = baseUrl || null;
  }

  async loadFromDB() {
    try {
      this.apiKey = await DB.loadSession('api_key');
      this.model = (await DB.loadSession('model_name')) || 'doubao-seed-1-6-251015';
      this.baseUrl = await DB.loadSession('base_url');
    } catch (e) { /* ignore */ }
  }

  async saveToDB() {
    if (this.apiKey) await DB.saveSession('api_key', this.apiKey);
    if (this.model) await DB.saveSession('model_name', this.model);
    if (this.baseUrl) await DB.saveSession('base_url', this.baseUrl);
  }

  isAvailable() {
    return !!(this.apiKey && navigator.onLine);
  }

  isConfigured() {
    return !!this.apiKey;
  }

  _getEndpoint() {
    const base = this.baseUrl || 'https://api.openai.com/v1';
    return base.replace(/\/+$/, '') + '/chat/completions';
  }

  async _callAPI(messages, maxTokens, temperature) {
    const resp = await fetch(this._getEndpoint(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: this.model,
        messages,
        max_tokens: maxTokens || this.maxTokens,
        temperature: temperature !== undefined ? temperature : this.temperature,
      }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`API Error ${resp.status}: ${errText.substring(0, 200)}`);
    }

    const data = await resp.json();
    return data.choices[0].message.content;
  }

  // Streaming version
  async *_callAPIStream(messages, maxTokens, temperature) {
    const resp = await fetch(this._getEndpoint(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${this.apiKey}`,
      },
      body: JSON.stringify({
        model: this.model,
        messages,
        max_tokens: maxTokens || this.maxTokens,
        temperature: temperature !== undefined ? temperature : this.temperature,
        stream: true,
      }),
    });

    if (!resp.ok) {
      const errText = await resp.text();
      throw new Error(`API Error ${resp.status}: ${errText.substring(0, 200)}`);
    }

    const reader = resp.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop();

      for (const line of lines) {
        const trimmed = line.trim();
        if (!trimmed || !trimmed.startsWith('data: ')) continue;
        const data = trimmed.slice(6);
        if (data === '[DONE]') return;
        try {
          const parsed = JSON.parse(data);
          const content = parsed.choices?.[0]?.delta?.content;
          if (content) yield content;
        } catch (e) { /* skip malformed */ }
      }
    }
  }

  // ============== Public Methods ==============

  async explainQuestion(question, userAnswer, isCorrect) {
    if (!this.isAvailable()) {
      return this._fallbackExplanation(question, userAnswer);
    }

    try {
      return await this._callAPI([
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: explanationPrompt(question, userAnswer, isCorrect) },
      ]);
    } catch (e) {
      return this._fallbackExplanation(question, userAnswer)
        + `\n\n> ⚠️ **API 调用错误**: ${e.message}\n> 请检查 Settings 页面中的 API Key 和配置是否正确。`;
    }
  }

  async *explainQuestionStream(question, userAnswer, isCorrect) {
    if (!this.isAvailable()) {
      yield this._fallbackExplanation(question, userAnswer);
      return;
    }

    try {
      yield* this._callAPIStream([
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: explanationPrompt(question, userAnswer, isCorrect) },
      ]);
    } catch (e) {
      yield `\n\n> ⚠️ **API 错误**: ${e.message}`;
    }
  }

  async translateQuestion(question) {
    if (!this.isAvailable()) {
      return '⚠️ 需要联网并配置 API Key 才能使用翻译功能。';
    }

    try {
      return await this._callAPI([
        { role: 'system', content: 'You are a GMAT translator. Be concise.' },
        { role: 'user', content: translationPrompt(question) },
      ], 1000, 0.3);
    } catch (e) {
      return `翻译生成失败: ${e.message}`;
    }
  }

  async *translateQuestionStream(question) {
    if (!this.isAvailable()) {
      yield '⚠️ 需要联网并配置 API Key 才能使用翻译功能。';
      return;
    }

    try {
      yield* this._callAPIStream([
        { role: 'system', content: 'You are a GMAT translator. Be concise.' },
        { role: 'user', content: translationPrompt(question) },
      ], 1000, 0.3);
    } catch (e) {
      yield `翻译生成失败: ${e.message}`;
    }
  }

  async generateSessionSummary(logs, questionsMap) {
    if (!logs.length) return '没有学习记录可供总结。';

    const total = logs.length;
    const correct = logs.filter(l => l.is_correct).length;
    const accuracy = total > 0 ? (correct / total * 100).toFixed(1) : '0';
    const avgTime = total > 0 ? Math.round(logs.reduce((s, l) => s + l.time_taken, 0) / total) : 0;

    const errorCounts = {};
    const tagErrors = {};
    logs.forEach(l => {
      if (!l.is_correct) {
        const cat = l.error_category || 'Unspecified';
        errorCounts[cat] = (errorCounts[cat] || 0) + 1;
        const q = questionsMap[l.question_id];
        if (q && q.skill_tags) {
          q.skill_tags.forEach(t => { tagErrors[t] = (tagErrors[t] || 0) + 1; });
        }
      }
    });

    const errorBreakdown = Object.entries(errorCounts).map(([k, v]) => `- ${k}: ${v}`).join('\n') || '- None';
    const weakTags = Object.entries(tagErrors)
      .sort((a, b) => b[1] - a[1]).slice(0, 3)
      .map(([t, c]) => `- ${t}: ${c} errors`).join('\n') || '- None';

    if (!this.isAvailable()) {
      return this._fallbackSummary(total, correct, parseFloat(accuracy), avgTime, Object.entries(tagErrors).sort((a, b) => b[1] - a[1]).slice(0, 3));
    }

    try {
      return await this._callAPI([
        { role: 'system', content: SYSTEM_PROMPT },
        { role: 'user', content: summaryPrompt(total, correct, accuracy, avgTime, errorBreakdown, weakTags) },
      ], 800, 0.7);
    } catch (e) {
      return this._fallbackSummary(total, correct, parseFloat(accuracy), avgTime, Object.entries(tagErrors).sort((a, b) => b[1] - a[1]).slice(0, 3));
    }
  }

  async testConnection() {
    try {
      const result = await this._callAPI([
        { role: 'user', content: 'Say OK' },
      ], 10, 0);
      return { success: true, reply: result.substring(0, 50) };
    } catch (e) {
      return { success: false, error: e.message.substring(0, 300) };
    }
  }

  // ============== Fallbacks ==============

  _fallbackExplanation(question, userAnswer) {
    const letters = ['A', 'B', 'C', 'D', 'E'];
    let text = `## 答案解析\n\n**正确答案：** ${letters[question.correct_answer]}\n**你的选择：** ${letters[userAnswer]}\n\n`;
    if (question.explanation) {
      text += `**解析：** ${question.explanation}\n\n`;
    }
    text += `**考点标签：** ${(question.skill_tags || []).join(', ')}\n\n`;
    text += '_提示：配置 API Key 并联网后可获得更详细的 AI 讲解。_';
    return text;
  }

  _fallbackSummary(total, correct, accuracy, avgTime, weakTags) {
    let text = `## 今日学习总结\n\n**练习数据：**\n- 完成题目：${total} 题\n- 正确数量：${correct} 题\n- 正确率：${accuracy.toFixed(1)}%\n- 平均用时：${avgTime} 秒/题\n\n`;
    if (weakTags && weakTags.length) {
      text += '**薄弱环节：**\n';
      weakTags.forEach(([tag, count]) => { text += `- ${tag}: ${count} 道题做错\n`; });
      text += '\n';
    }
    if (accuracy >= 80) text += '✅ **整体表现良好！** 继续保持当前的学习节奏。\n';
    else if (accuracy >= 60) text += '📈 **表现中等。** 建议针对薄弱环节进行专项训练。\n';
    else text += '⚠️ **需要加强基础。** 建议放慢速度，仔细分析每道错题。\n';
    text += '\n_提示：配置 API Key 并联网后可获得更详细的 AI 分析和个性化建议。_';
    return text;
  }

  getFallbackTip(skillTag) {
    return FALLBACK_TIPS[skillTag] || '仔细阅读题干，识别论证结构，注意题目问的是什么。';
  }
}

window.AITutor = AITutor;
window.ERROR_TAXONOMY = ERROR_TAXONOMY;
