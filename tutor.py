"""
GMAT Focus AI Tutor - AI Tutor Layer
Handles LLM interactions for explanations and summaries.
"""

import os
from typing import Optional, Dict, List
from dataclasses import dataclass
from database import Question, StudyLog

# ============== Configuration ==============

@dataclass
class TutorConfig:
    """Configuration for AI tutor.
    
    Supports OpenAI-compatible APIs (火山方舟, DeepSeek, Moonshot, etc.)
    by setting base_url to the provider's endpoint.
    
    Examples:
        火山方舟: base_url="https://ark.cn-beijing.volces.com/api/v3"
        DeepSeek: base_url="https://api.deepseek.com"
        Moonshot: base_url="https://api.moonshot.cn/v1"
        OpenAI:   base_url=None (uses default)
    """
    model: str = "gpt-4o-mini"  # Default model; set to your endpoint ID for 火山方舟
    base_url: str = None  # Set to provider's API endpoint URL
    max_tokens: int = 1500
    temperature: float = 0.7


# ============== Prompt Templates ==============

SYSTEM_PROMPT = """You are a GMAT expert tutor who has helped thousands of students achieve 99th percentile scores. 

Your teaching style:
- Patient and encouraging, but rigorous
- Focus on building fundamental reasoning skills
- Use clear, structured explanations
- Help students recognize patterns and traps

Language: Always respond in the same language as the user's question or the language they prefer. If the question is in Chinese, respond in Chinese. If in English, respond in English."""


EXPLANATION_PROMPT_TEMPLATE = """A student answered a GMAT {question_type} question. Analyze their specific mistake.

**Question Type:** {question_type}
**Question:**
{question_content}

**Options:**
A. {option_a}
B. {option_b}
C. {option_c}
D. {option_d}
E. {option_e}

**Correct Answer:** {correct_answer}
**Student Selected:** {student_answer}
**Student was correct:** {is_correct}
**Question Tags:** {skill_tags}

Please structure your explanation as follows. Adapt emphasis based on whether the student was correct or not.

## ❌ 你选的 {student_answer} 为什么不对？（如果答对则改为"✅ 你选对了，注意这些干扰项"）
This is the MOST IMPORTANT section. Be specific and detailed:
- Quote the key phrase(s) in option {student_answer} that make it wrong
- For CR: Explain the logical trap (too extreme? irrelevant comparison? necessary vs. sufficient? correlation vs. causation? out of scope?)
- For RC: Explain what the passage actually says vs. what this option distorts (over-generalization? opposite meaning? not stated? wrong detail?)
- Explain what the student was probably thinking and why that reasoning is flawed
- If the student answered correctly, briefly note the most tempting wrong answer and why it's a trap

## ✅ 正确答案 {correct_answer} 的逻辑链
- In 2-3 sentences, show the direct logical connection
- For CR: premise → gap → how this option fills/addresses it
- For RC: passage evidence (cite specific phrases) → how this option matches

## 📝 关键词汇
List 3-5 KEY English words/phrases from the question and options that are critical for understanding this question. Focus on:
- Words that change the logical direction (e.g. "nevertheless", "notwithstanding", "ostensibly")
- GMAT-specific formal vocabulary that Chinese students often misread
- Phrases that create the trap in wrong answers (e.g. "some" vs "all", "correlation" vs "causation")

Format each as a bullet point:
- **English word/phrase** — 中文释义 — 在本题中的作用（一句话）

## 🔑 一句话记住
One actionable takeaway sentence. Format: "遇到[题型/情境]，注意[具体陷阱]，关键是[正确思路]"

Keep the total response under 500 words. Be direct and specific — avoid generic advice. Use the student's actual wrong choice as the teaching anchor. 请用中文回答（词汇翻译部分保留英文原词）。"""


SUMMARY_PROMPT_TEMPLATE = """Based on today's study session, provide a brief summary and recommendations.

**Session Statistics:**
- Questions attempted: {total_questions}
- Correct answers: {correct_count}
- Accuracy: {accuracy}%
- Average time per question: {avg_time} seconds

**Errors by Category:**
{error_breakdown}

**Weakest Tags:**
{weak_tags}

Please provide:
1. A brief assessment of today's performance (2-3 sentences)
2. What went well
3. Key areas needing improvement
4. Specific recommendation for tomorrow's practice

Keep it encouraging but honest. Be concise."""


QUICK_TIP_PROMPT_TEMPLATE = """For a GMAT {question_type} question testing "{skill_tag}", give ONE quick tip (2-3 sentences max) that helps identify the correct answer pattern."""

TRANSLATION_PROMPT_TEMPLATE = """Provide a bilingual translation and analysis for this GMAT question.

**Context/Argument:**
{question_content}

**Options:**
A. {option_a}
B. {option_b}
C. {option_c}
D. {option_d}
E. {option_e}

Please follow this output format:

## 🌐 中英对照翻译
(Break down the argument/passage by sentence or logical chunk. Quote the English first, then translate.)

> **[English text chunk 1]**
> [Chinese translation]

> **[English text chunk 2]**
> [Chinese translation]

**选项翻译**:
- **A**: [Chinese Translation]
- **B**: [Chinese Translation]
- **C**: [Chinese Translation]
- **D**: [Chinese Translation]
- **E**: [Chinese Translation]

## 🧬 长难句精讲 (Sentence Analysis)
Select the 1-2 most grammatically complex or critical sentences from the text.
1. **原句**: [English Sentence]
   - **结构**: [Analyze the sentence structure]
   - **点拨**: [Key difficulty: e.g., Inversion, Modifier, Idiom]
   - **精译**: [Polished Translation]
"""


# ============== AI Tutor ==============

class AITutor:
    """AI-powered tutor using LLM for explanations."""
    
    def __init__(self, config: TutorConfig = None, api_key: str = None, base_url: str = None):
        self.config = config or TutorConfig()
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY") or os.environ.get("ARK_API_KEY")
        # Allow base_url from parameter, config, or env
        self.base_url = base_url or self.config.base_url or os.environ.get("OPENAI_BASE_URL")
        self._client = None
    
    def _get_client(self):
        """Lazy initialization of OpenAI-compatible client."""
        if self._client is None:
            if not self.api_key:
                return None
            try:
                from openai import OpenAI
                kwargs = {"api_key": self.api_key}
                if self.base_url:
                    kwargs["base_url"] = self.base_url
                self._client = OpenAI(**kwargs)
            except ImportError:
                print("Warning: openai package not installed. AI features disabled.")
                return None
        return self._client
    
    def is_available(self) -> bool:
        """Check if AI features are available."""
        return self._get_client() is not None
    
    def explain_failure(self, 
                       question: Question, 
                       user_answer: int,
                       is_correct: bool = False,
                       language: str = "zh") -> str:
        """
        Generate a detailed explanation focusing on why the user's choice was wrong.
        
        Args:
            question: The question object
            user_answer: Index of the user's selected answer (0-4)
            is_correct: Whether the user answered correctly
            language: "zh" for Chinese, "en" for English
        
        Returns:
            Explanation text
        """
        client = self._get_client()
        
        # Format the prompt
        option_letters = ['A', 'B', 'C', 'D', 'E']
        question_type = "Reading Comprehension (RC)" if question.subcategory == "RC" else "Critical Reasoning (CR)"
        prompt = EXPLANATION_PROMPT_TEMPLATE.format(
            question_type=question_type,
            question_content=question.content,
            option_a=question.options[0],
            option_b=question.options[1],
            option_c=question.options[2],
            option_d=question.options[3],
            option_e=question.options[4],
            correct_answer=option_letters[question.correct_answer],
            student_answer=option_letters[user_answer],
            is_correct="Yes" if is_correct else "No",
            skill_tags=", ".join(question.skill_tags)
        )
        
        if not client:
            # Fallback to stored explanation if available
            return self._fallback_explanation(question, user_answer)
        
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=self.config.max_tokens,
                temperature=self.config.temperature
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"AI explanation error: {e}")
            error_msg = f"\n\n> ⚠️ **API 调用错误**: {str(e)}\n> 请检查 Settings 页面中的 API Key 和配置是否正确。"
            return self._fallback_explanation(question, user_answer) + error_msg
    
    def _fallback_explanation(self, question: Question, user_answer: int) -> str:
        """Provide a basic explanation when AI is not available."""
        option_letters = ['A', 'B', 'C', 'D', 'E']
        
        explanation = f"""## 答案解析

**正确答案：** {option_letters[question.correct_answer]}
**你的选择：** {option_letters[user_answer]}

"""
        if question.explanation:
            explanation += f"**解析：** {question.explanation}\n\n"
        
        explanation += f"**考点标签：** {', '.join(question.skill_tags)}\n\n"
        explanation += "_提示：配置 API Key 后可获得更详细的 AI 讲解。_"
        
        return explanation
    
    
    def translate_question(self, question: Question) -> str:
        """Translate question content to Chinese."""
        if not self._get_client():
            return "⚠️ AI 未连接，请配置 API Key 后使用翻译功能。"

        try:
            prompt = TRANSLATION_PROMPT_TEMPLATE.format(
                question_content=question.content,
                option_a=question.options[0],
                option_b=question.options[1],
                option_c=question.options[2],
                option_d=question.options[3],
                option_e=question.options[4]
            )
            
            response = self._get_client().chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": "You are a professional GMAT tutor and translator."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.3, 
                max_tokens=1500
            )
            return response.choices[0].message.content
        except Exception as e:
            return f"翻译生成失败: {e}"

    def generate_session_summary(self,
                                logs: List[StudyLog],
                                questions: Dict[int, Question]) -> str:
        """
        Generate a summary of a study session.
        
        Args:
            logs: List of study logs from the session
            questions: Dict mapping question_id to Question objects
        """
        if not logs:
            return "没有学习记录可供总结。"
        
        # Calculate statistics
        total = len(logs)
        correct = sum(1 for log in logs if log.is_correct)
        accuracy = (correct / total * 100) if total > 0 else 0
        avg_time = sum(log.time_taken for log in logs) / total if total > 0 else 0
        
        # Error breakdown
        error_counts = {}
        tag_errors = {}
        
        for log in logs:
            if not log.is_correct:
                # Count by error category
                cat = log.error_category or "Unspecified"
                error_counts[cat] = error_counts.get(cat, 0) + 1
                
                # Count by skill tag
                q = questions.get(log.question_id)
                if q:
                    for tag in q.skill_tags:
                        tag_errors[tag] = tag_errors.get(tag, 0) + 1
        
        error_breakdown = "\n".join(f"- {cat}: {count}" for cat, count in error_counts.items()) or "- None"
        
        weak_tags = sorted(tag_errors.items(), key=lambda x: x[1], reverse=True)[:3]
        weak_tags_str = "\n".join(f"- {tag}: {count} errors" for tag, count in weak_tags) or "- None"
        
        prompt = SUMMARY_PROMPT_TEMPLATE.format(
            total_questions=total,
            correct_count=correct,
            accuracy=f"{accuracy:.1f}",
            avg_time=f"{avg_time:.0f}",
            error_breakdown=error_breakdown,
            weak_tags=weak_tags_str
        )
        
        client = self._get_client()
        if not client:
            return self._fallback_summary(total, correct, accuracy, avg_time, weak_tags)
        
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=800,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            print(f"AI summary error: {e}")
            return self._fallback_summary(total, correct, accuracy, avg_time, weak_tags)
    
    def _fallback_summary(self, total: int, correct: int, accuracy: float, 
                         avg_time: float, weak_tags: List[tuple]) -> str:
        """Generate a basic summary when AI is not available."""
        summary = f"""## 今日学习总结

**练习数据：**
- 完成题目：{total} 题
- 正确数量：{correct} 题
- 正确率：{accuracy:.1f}%
- 平均用时：{avg_time:.0f} 秒/题

"""
        if weak_tags:
            summary += "**薄弱环节：**\n"
            for tag, count in weak_tags:
                summary += f"- {tag}: {count} 道题做错\n"
            summary += "\n"
        
        if accuracy >= 80:
            summary += "✅ **整体表现良好！** 继续保持当前的学习节奏。\n"
        elif accuracy >= 60:
            summary += "📈 **表现中等。** 建议针对薄弱环节进行专项训练。\n"
        else:
            summary += "⚠️ **需要加强基础。** 建议放慢速度，仔细分析每道错题。\n"
        
        summary += "\n_提示：配置 API Key 后可获得更详细的 AI 分析和个性化建议。_"
        
        return summary
    
    def get_quick_tip(self, question_type: str, skill_tag: str) -> str:
        """Get a quick tip for a specific question type and skill."""
        client = self._get_client()
        
        prompt = QUICK_TIP_PROMPT_TEMPLATE.format(
            question_type=question_type,
            skill_tag=skill_tag
        )
        
        if not client:
            return self._get_fallback_tip(skill_tag)
        
        try:
            response = client.chat.completions.create(
                model=self.config.model,
                messages=[
                    {"role": "system", "content": SYSTEM_PROMPT},
                    {"role": "user", "content": prompt}
                ],
                max_tokens=200,
                temperature=0.7
            )
            return response.choices[0].message.content
        except Exception as e:
            return self._get_fallback_tip(skill_tag)
    
    def _get_fallback_tip(self, skill_tag: str) -> str:
        """Provide a static tip based on skill tag."""
        tips = {
            "Assumption": "找假设题的关键：正确答案是论证成立的必要条件。用'否定测试'——如果否定某个选项后论证崩塌，那就是正确答案。",
            "Strengthen": "加强题要找能填补论证缺口的选项。注意：好的加强选项不需要'证明'结论，只需要让结论'更可能'成立。",
            "Weaken": "削弱题要攻击'前提到结论'的推理过程，而不是攻击前提本身。寻找替代解释或破坏因果链的选项。",
            "Inference": "推断题要求'必然为真'。小心'大多数'≠'所有'，'有些'≠'必然'。正确选项通常比你预期的更保守。",
            "Evaluate": "评估题要找能决定论证强弱的关键信息。问自己：'如果知道这个信息，结论会更强还是更弱？'",
            "Boldface": "粗体题先判断每个粗体部分的角色（结论？前提？反驳？），再看它们之间的逻辑关系。"
        }
        return tips.get(skill_tag, "仔细阅读题干，识别论证结构，注意题目问的是什么。")


# ============== Error Taxonomy Reference ==============

ERROR_TAXONOMY = {
    "Understanding": {
        "description": "理解层面的错误 - 没有正确理解题目或选项的含义",
        "types": {
            "Text Misinterpretation": "误解题干中的关键信息或论证结构",
            "Option Misinterpretation": "误解选项的实际含义"
        },
        "remedy": "放慢阅读速度，用自己的话复述论证"
    },
    "Reasoning": {
        "description": "推理层面的错误 - 理解了但推理过程出错",
        "types": {
            "Confusion (Suff/Nec)": "混淆充分条件和必要条件",
            "Reverse Causality": "颠倒因果关系",
            "Scope Shift": "范围转移 - 选项讨论的范围与题干不一致",
            "Trap Answer": "掉入常见陷阱选项"
        },
        "remedy": "练习识别论证模式，学习常见陷阱类型"
    },
    "Execution": {
        "description": "执行层面的错误 - 会做但做错了",
        "types": {
            "Time Pressure": "时间压力导致仓促答题",
            "Careless": "粗心大意，漏看关键词"
        },
        "remedy": "练习时间管理，建立检查习惯"
    }
}


def get_error_taxonomy() -> Dict:
    """Return the error taxonomy for UI display."""
    return ERROR_TAXONOMY


# ============== Test ==============

def test_tutor():
    """Test the AI tutor with a sample question."""
    print("\n=== Testing AI Tutor ===\n")
    
    tutor = AITutor()
    
    print(f"AI Available: {tutor.is_available()}")
    
    # Create a sample question
    sample_q = Question(
        id=1,
        passage_id=None,
        category="Verbal",
        subcategory="CR",
        content="Studies show that employees who work from home report higher job satisfaction. Therefore, all companies should mandate remote work.",
        options=[
            "Working from home is possible for all jobs",
            "Job satisfaction improves productivity",
            "Remote workers are more loyal",
            "Office rent is expensive",
            "Commuting is stressful"
        ],
        correct_answer=0,
        skill_tags=["Assumption"],
        difficulty=3,
        explanation="The argument assumes all jobs can be done remotely."
    )
    
    print("Testing explanation generation...")
    explanation = tutor.explain_failure(sample_q, user_answer=1)
    print(explanation[:500] + "..." if len(explanation) > 500 else explanation)
    
    print("\n✓ Tutor test complete!")


if __name__ == "__main__":
    test_tutor()
