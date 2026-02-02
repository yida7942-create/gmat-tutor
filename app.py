"""
GMAT Focus AI Tutor - Streamlit App
Main user interface for the study assistant.
"""

import streamlit as st
from datetime import datetime
import time
import json
import os
from typing import Optional
from typing import Optional
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor

from database import get_db, Question, StudyLog, DatabaseManager
from scheduler import Scheduler, DailyPlan, SchedulerConfig
from tutor import AITutor, TutorConfig, get_error_taxonomy
from gist_sync import get_gist_client

# ============== Page Config ==============

st.set_page_config(
    page_title="GMAT Focus AI Tutor",
    page_icon="📚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ============== Security (App Lock) ==============

def check_password():
    """Returns `True` if the user had the correct password."""
    # 1. If no password is set in secrets, allow access (for local dev convenience)
    if "password" not in st.secrets:
        # Debugging: Show connected secrets keys (safely)
        st.warning(f"⚠️ 未检测到密码配置。当前读取到的 Secrets Keys: {list(st.secrets.keys())}")
        return True

    def password_entered():
        if st.session_state["password"] == st.secrets["password"]:
            st.session_state["password_correct"] = True
            del st.session_state["password"]  # don't store password
        else:
            st.session_state["password_correct"] = False

    if "password_correct" not in st.session_state:
        # First run, show input
        st.text_input(
            "🔑 请输入访问密码", type="password", on_change=password_entered, key="password"
        )
        return False
    elif not st.session_state["password_correct"]:
        # Password incorrect, show input + error
        st.text_input(
            "🔑 请输入访问密码", type="password", on_change=password_entered, key="password"
        )
        st.error("密码错误")
        return False
    else:
        # Password correct
        return True

if not check_password():
    st.stop()

# ============== Auto-Initialize Database ==============

def ensure_database_ready():
    """If database is empty and og_questions.json exists, auto-import."""
    db = get_db()
    existing = db.get_all_questions()
    if len(existing) == 0:
        json_path = os.path.join(os.path.dirname(__file__), "og_questions.json")
        if os.path.exists(json_path):
            with open(json_path, 'r', encoding='utf-8') as f:
                questions = json.load(f)
            for q in questions:
                from database import Question as Q
                db.add_question(Q(
                    id=None, passage_id=None,
                    category=q.get('category', 'Verbal'),
                    subcategory=q.get('subcategory', 'CR'),
                    content=q['content'],
                    options=q['options'],
                    correct_answer=q['correct_answer'],
                    skill_tags=q['skill_tags'],
                    difficulty=q.get('difficulty', 3),
                    explanation=q.get('explanation', ''),
                ))
            return len(questions)
    return 0

# Run auto-init on first load
if 'db_initialized' not in st.session_state:
    imported = ensure_database_ready()
    st.session_state.db_initialized = True
    if imported > 0:
        st.toast(f"✅ 自动导入了 {imported} 道 OG 真题", icon="📚")


# ============== Session State Init ==============

def _load_ai_from_secrets() -> AITutor:
    """Try to load AI config from Streamlit secrets OR database."""
    # 1. Try Secrets (Priority for Cloud)
    try:
        ai_conf = st.secrets.get("ai", {})
        if ai_conf and ai_conf.get("api_key"):
            model = ai_conf.get("model", "doubao-seed-1-6-251015")
            base_url = ai_conf.get("base_url", None)
            
            # Auto-fix Base URL for Coding Plan if user configures it wrong
            if model == "ark-code-latest" and base_url and "/coding" not in base_url:
                base_url = "https://ark.cn-beijing.volces.com/api/coding/v3"
            
            config = TutorConfig(
                model=model,
                base_url=base_url,
            )
            return AITutor(config=config, api_key=ai_conf["api_key"])
    except Exception:
        pass

    # 2. Try Database (Priority for Local / Session persistence)
    try:
        db = get_db()
        api_key = db.load_session('api_key')
        if api_key:
            model = db.load_session('model_name') or "doubao-seed-1-6-251015"
            base_url = db.load_session('base_url')
            config = TutorConfig(model=model, base_url=base_url)
            return AITutor(config=config, api_key=api_key)
    except Exception:
        pass

    return AITutor()


def init_session_state():
    """Initialize session state variables."""
    defaults = {
        'db': get_db(),
        'scheduler': Scheduler(),
        'tutor': _load_ai_from_secrets(),
        'current_plan': None,
        'current_question_idx': 0,
        'session_logs': [],
        'question_start_time': None,
        'show_result': False,
        'last_answer': None,
        'page': '🏠 Dashboard',
        'ai_executor': ThreadPoolExecutor(max_workers=2),
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value

init_session_state()


# ============== Sidebar ==============

def render_sidebar():
    """Render the sidebar with navigation and settings."""
    with st.sidebar:
        st.title("📚 GMAT Focus AI Tutor")
        st.markdown("---")

        pages = ["🏠 Dashboard", "📝 Practice", "📊 Progress", "⚙️ Settings"]
        current = st.session_state.get('page', '🏠 Dashboard')
        
        # Use buttons for navigation (more reliable than radio for programmatic switching)
        for p in pages:
            btn_type = "primary" if p == current else "secondary"
            if st.button(p, key=f"nav_{p}", use_container_width=True, type=btn_type):
                st.session_state.page = p
                st.rerun()

        st.markdown("---")

        # Quick stats
        stats = st.session_state.db.get_stats()
        col1, col2 = st.columns(2)
        col1.metric("已练习", stats['total_attempts'])
        col2.metric("正确率", f"{stats['overall_accuracy']}%")

        st.caption(f"题库: {stats['total_questions']} 道题")

        st.markdown("---")

        # AI Status
        if st.session_state.tutor.is_available():
            st.success("🤖 AI 已连接")
        else:
            st.info("🤖 AI 未连接（使用内置解析）")

        return current


# ============== Dashboard Page ==============

def render_dashboard():
    """Render the main dashboard."""
    st.header("🏠 Dashboard")

    # Check if database has questions
    stats = st.session_state.db.get_stats()
    if stats['total_questions'] == 0:
        st.warning("⚠️ 数据库中没有题目！请先导入题目。")
        st.markdown("""
        **导入方法：**
        1. 如果包里有 `og_questions.json`，运行 `python import_questions.py`
        2. 或者从 PDF 提取：`python extract_og.py "你的PDF路径.pdf" --import`
        """)
        return

    # Get recommendations
    scheduler = st.session_state.scheduler
    recs = scheduler.get_recommended_focus()

    col1, col2 = st.columns([2, 1])

    with col1:
        st.subheader("📋 今日建议")
        st.info(recs['message'])

        if recs['primary_focus']:
            pf = recs['primary_focus']
            st.markdown(f"**重点关注:** `{pf['tag']}` — 正确率 {pf['accuracy']:.1f}%（{pf['attempts']} 次尝试）")

    with col2:
        # Question type and count selectors
        type_counts = st.session_state.db.get_question_counts_by_type()
        type_options = {}
        if type_counts.get('RC', 0) > 0:
            type_options['📖 RC 阅读理解'] = 'RC'
        if type_counts.get('CR', 0) > 0:
            type_options['🧠 CR 逻辑推理'] = 'CR'
        if len(type_options) > 1:
            type_options = {'📖 RC 阅读理解': 'RC', '🧠 CR 逻辑推理': 'CR', '🔀 混合练习': None, **{}}
            # Rebuild in order
            type_options = {}
            if type_counts.get('RC', 0) > 0:
                type_options['📖 RC 阅读理解'] = 'RC'
            if type_counts.get('CR', 0) > 0:
                type_options['🧠 CR 逻辑推理'] = 'CR'
            type_options['🔀 混合练习'] = None

        selected_label = st.radio(
            "选择练习类型",
            list(type_options.keys()),
            index=0,
            key="dash_type_radio"
        )
        selected_subcategory = type_options[selected_label]
        
        # Show available count
        if selected_subcategory:
            avail = type_counts.get(selected_subcategory, 0)
            st.caption(f"题库: {avail} 题")
        else:
            st.caption(f"题库: {sum(type_counts.values())} 题")

        question_count = st.selectbox("题目数量", [5, 10, 15, 20], index=1, key="dash_count")
        if st.button("🚀 开始练习", use_container_width=True, type="primary"):
            plan = scheduler.generate_daily_plan(
                question_count=question_count,
                subcategory=selected_subcategory
            )
            if plan.questions:
                st.session_state.current_plan = plan
                st.session_state.current_question_idx = 0
                st.session_state.session_logs = []
                st.session_state.show_result = False
                st.session_state.last_answer = None
                st.session_state.question_start_time = None
                st.session_state.scheduler.reset_session()
                # Persist plan to DB for refresh recovery
                _save_practice_state(plan, 0)
                # Switch to Practice page
                st.session_state.page = '📝 Practice'
                st.rerun()
            else:
                st.error("无法生成练习计划（该类型题库可能为空）。")

    st.markdown("---")

    # RC / CR accuracy overview
    stats = st.session_state.db.get_stats()
    if stats['accuracy_by_type']:
        st.subheader("📊 分项正确率")
        type_cols = st.columns(len(stats['accuracy_by_type']))
        for idx, (sub, data) in enumerate(sorted(stats['accuracy_by_type'].items())):
            label = "📖 RC 阅读理解" if sub == "RC" else "🧠 CR 逻辑推理"
            with type_cols[idx]:
                st.metric(
                    label=label,
                    value=f"{data['accuracy']}%",
                    delta=f"{data['correct']}/{data['total']} 题"
                )
        st.markdown("---")

    # Tag performance overview
    st.subheader("📊 技能概览")
    progress = scheduler.get_progress_summary()

    if progress['tag_performance']:
        cols = st.columns(min(3, len(progress['tag_performance'])))
        for idx, perf in enumerate(progress['tag_performance'][:6]):
            col_idx = idx % 3
            with cols[col_idx]:
                emoji = "🔴" if perf['status'] == "weak" else "🟡" if perf['status'] == "improving" else "🟢"
                st.metric(
                    label=f"{emoji} {perf['tag']}",
                    value=f"{perf['accuracy']}%",
                    delta=f"{perf['attempts']} 次"
                )
    else:
        st.info("还没有练习记录。点击上方按钮开始练习！")

    # Daily trend
    if progress['daily_trend']:
        st.markdown("---")
        st.subheader("📈 最近 7 天趋势")
        import pandas as pd
        df = pd.DataFrame(progress['daily_trend'])
        if not df.empty:
            st.line_chart(df.set_index('date')['accuracy'])


# ============== Practice State Persistence ==============

def _save_practice_state(plan, question_idx: int):
    """Save current practice state to DB for refresh recovery."""
    db = st.session_state.db
    
    # Serialize complex objects
    # StudyLogs need to be serialized to dicts
    logs_data = [asdict(log) for log in st.session_state.session_logs] if st.session_state.session_logs else []
    
    # Last answer needs to be serialized (question object inside it needs handling)
    last_answer_data = None
    if st.session_state.last_answer:
        la = st.session_state.last_answer.copy()
        if 'question' in la:
            la['question_id'] = la['question'].id
            del la['question'] # Don't save the full object, just ID
        last_answer_data = la

    state = {
        'question_ids': [q.id for q in plan.questions],
        'question_idx': question_idx,
        'started_at': datetime.now().isoformat(),
        'show_result': st.session_state.show_result,
        'last_answer': last_answer_data,
        'session_logs': logs_data
    }
    db.save_session('practice_state', json.dumps(state))
    db.save_session('practice_page', '📝 Practice')


def _clear_practice_state():
    """Clear saved practice state."""
    db = st.session_state.db
    db.delete_session('practice_state')
    db.delete_session('practice_page')


def _restore_practice_state() -> bool:
    """Try to restore practice state from DB. Returns True if restored."""
    db = st.session_state.db
    raw = db.load_session('practice_state')
    if not raw:
        return False
    try:
        state = json.loads(raw)
        question_ids = state['question_ids']
        question_idx = state['question_idx']
        
        # Rebuild plan from question IDs
        questions = []
        for qid in question_ids:
            q = db.get_question(qid)
            if q:
                questions.append(q)
        
        if not questions:
            _clear_practice_state()
            return False
        
        plan = DailyPlan(
            questions=questions,
            estimated_time_minutes=len(questions) * 2,
            focus_tags=[],
            created_at=state.get('started_at', datetime.now().isoformat())
        )
        st.session_state.current_plan = plan
        st.session_state.current_question_idx = question_idx
        
        # Restore extended state
        st.session_state.show_result = state.get('show_result', False)
        
        # Restore logs
        logs_raw = state.get('session_logs', [])
        st.session_state.session_logs = [StudyLog(**log) for log in logs_raw]
        
        # Restore last answer
        la_raw = state.get('last_answer')
        if la_raw:
            # Rehydrate question object if needed
            qid = la_raw.get('question_id')
            if qid:
                # Find the question object in our plan
                q_obj = next((q for q in questions if q.id == qid), None)
                la_raw['question'] = q_obj
            st.session_state.last_answer = la_raw
        else:
            st.session_state.last_answer = None

        st.session_state.question_start_time = None # Reset timer on refresh to avoid huge times
        st.session_state.page = '📝 Practice'
        return True
    except Exception:
        _clear_practice_state()
        return False


# ============== Practice Page ==============

def render_practice():
    """Render the practice/study interface."""
    st.header("📝 Practice Mode")

    plan = st.session_state.current_plan

    # Try to restore from DB if no active plan
    if plan is None or not plan.questions:
        if _restore_practice_state():
            plan = st.session_state.current_plan
            st.toast("📋 已恢复上次练习进度", icon="🔄")

    # No active plan
    if plan is None or not plan.questions:
        st.info("当前没有进行中的练习计划。")

        # Type selector
        type_counts = st.session_state.db.get_question_counts_by_type()
        type_map = {}
        if type_counts.get('RC', 0) > 0:
            type_map['📖 RC 阅读理解'] = 'RC'
        if type_counts.get('CR', 0) > 0:
            type_map['🧠 CR 逻辑推理'] = 'CR'
        if len(type_map) > 1:
            type_map['🔀 混合练习'] = None

        col1, col2, col3 = st.columns(3)
        with col1:
            selected_label = st.radio(
                "练习类型",
                list(type_map.keys()),
                index=0,
                key="prac_type_radio"
            )
            selected_sub = type_map[selected_label]
        with col2:
            question_count = st.slider("题目数量", 5, 30, 10, key="prac_count")
        with col3:
            st.write("")  # spacing
            st.write("")
            if st.button("▶️ 开始练习", type="primary", use_container_width=True):
                new_plan = st.session_state.scheduler.generate_daily_plan(
                    question_count=question_count,
                    subcategory=selected_sub
                )
                if new_plan.questions:
                    st.session_state.current_plan = new_plan
                    st.session_state.current_question_idx = 0
                    st.session_state.session_logs = []
                    st.session_state.show_result = False
                    st.session_state.last_answer = None
                    st.session_state.question_start_time = None
                    st.session_state.scheduler.reset_session()
                    _save_practice_state(new_plan, 0)
                    st.rerun()
                else:
                    st.error("该类型题库为空，请先导入题目。")
        return

    # Check if practice is complete
    if st.session_state.current_question_idx >= len(plan.questions):
        render_session_summary()
        return

    # Current question
    current_q = plan.questions[st.session_state.current_question_idx]

    # Progress bar
    progress_val = st.session_state.current_question_idx / len(plan.questions)
    st.progress(progress_val)
    st.caption(f"第 {st.session_state.current_question_idx + 1} / {len(plan.questions)} 题")

    # Start timer
    if st.session_state.question_start_time is None:
        st.session_state.question_start_time = time.time()

    st.markdown("---")

    # Tags and metadata
    type_label = "📖 RC 阅读理解" if current_q.subcategory == "RC" else "🧠 CR 逻辑推理"
    tags_str = " | ".join([f"`{tag}`" for tag in current_q.skill_tags])
    st.caption(f"**{type_label}** | **考点:** {tags_str} | **难度:** {'⭐' * current_q.difficulty}")

    # Question content
    st.markdown(current_q.content)
    st.markdown("---")

    if not st.session_state.show_result:
        render_question_options(current_q)
    else:
        render_result_view(current_q)


def render_question_options(question: Question):
    """Render the answer options."""
    option_letters = ['A', 'B', 'C', 'D', 'E']

    st.markdown("**选择你的答案:**")

    for idx, option in enumerate(question.options):
        if st.button(
            f"{option_letters[idx]}. {option}",
            key=f"opt_{st.session_state.current_question_idx}_{idx}",
            use_container_width=True
        ):
            time_taken = int(time.time() - st.session_state.question_start_time)
            is_correct = (idx == question.correct_answer)

            st.session_state.last_answer = {
                'user_answer': idx,
                'is_correct': is_correct,
                'time_taken': time_taken,
                'question': question
            }
            st.session_state.show_result = True
            st.rerun()


def render_result_view(question: Question):
    """Render the result after answering."""
    result = st.session_state.last_answer
    letters = ['A', 'B', 'C', 'D', 'E']

    # Result
    if result['is_correct']:
        st.success(f"✅ 正确！用时 {result['time_taken']} 秒")
    else:
        st.error(f"❌ 错误！正确答案是 **{letters[question.correct_answer]}**，你选了 **{letters[result['user_answer']]}**")

    # Show options with highlighting
    for idx, option in enumerate(question.options):
        prefix = letters[idx]
        if idx == question.correct_answer:
            st.markdown(f"✅ **{prefix}. {option}**")
        elif idx == result['user_answer'] and not result['is_correct']:
            st.markdown(f"❌ ~~{prefix}. {option}~~")
        else:
            st.markdown(f"&nbsp;&nbsp;&nbsp;&nbsp;{prefix}. {option}")

    st.markdown("---")

    # --- Content Generation (Eager Load) ---
    # Trigger futures if not cached/running
    
    # 1. AI Explanation Future
    exp_cache_key = f"ai_exp_{question.id}_{result['user_answer']}"
    exp_future_key = f"future_exp_{question.id}_{result['user_answer']}"
    
    if exp_cache_key not in st.session_state and exp_future_key not in st.session_state:
        # Submit task
        future = st.session_state.ai_executor.submit(
            st.session_state.tutor.explain_failure,
            question, 
            result['user_answer'], 
            result['is_correct']
        )
        st.session_state[exp_future_key] = future

    # 2. Translation Future
    trans_cache_key = f"ai_trans_{question.id}"
    trans_future_key = f"future_trans_{question.id}"
    
    if trans_cache_key not in st.session_state and trans_future_key not in st.session_state:
        # Submit task
        future = st.session_state.ai_executor.submit(
            st.session_state.tutor.translate_question,
            question
        )
        st.session_state[trans_future_key] = future

    # --- Display Sections ---

    # 2. AI Explanation
    with st.expander("🤖 AI 讲解", expanded=True):
        if exp_cache_key in st.session_state:
             st.markdown(st.session_state[exp_cache_key])
        elif exp_future_key in st.session_state:
            # Check status
            f = st.session_state[exp_future_key]
            if f.done():
                try:
                    res = f.result()
                    st.session_state[exp_cache_key] = res
                    del st.session_state[exp_future_key] # Cleanup future
                    st.markdown(res)
                    st.rerun() # Rerun to refresh state mostly for cleaner look, but maybe optional
                except Exception as e:
                    st.error(f"生成失败: {e}")
            else:
                st.info("🤖 AI 正在分析题目... (后台生成中)")
        else:
            st.error("任务启动失败")

    # 3. Translation
    with st.expander("🌐 中文翻译", expanded=False):
        if trans_cache_key in st.session_state:
             st.markdown(st.session_state[trans_cache_key])
        elif trans_future_key in st.session_state:
             f = st.session_state[trans_future_key]
             if f.done():
                res = f.result()
                st.session_state[trans_cache_key] = res
                del st.session_state[trans_future_key]
                st.markdown(res)
             else:
                st.info("🌐 正在生成翻译... (后台生成中)")

    st.markdown("---")
    
    # Error tagging (moved to bottom)
    error_category = None
    error_detail = None

    if not result['is_correct']:
        st.subheader("📝 错误归因 (Self-Tagging)")
        st.caption("反思一下：这道题为什么做错了？")

        error_taxonomy = get_error_taxonomy()

        col1, col2 = st.columns(2)
        with col1:
            error_category = st.selectbox(
                "错误大类",
                list(error_taxonomy.keys()),
                format_func=lambda x: f"{x} - {error_taxonomy[x]['description'][:15]}...",
                key=f"err_cat_{st.session_state.current_question_idx}"
            )
        with col2:
            error_types = error_taxonomy[error_category]['types']
            error_detail = st.selectbox(
                "具体原因",
                list(error_types.keys()),
                key=f"err_det_{st.session_state.current_question_idx}"
            )

        st.caption(f"💡 **改进建议:** {error_taxonomy[error_category]['remedy']}")
        st.markdown("---")

    # Next button
    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        if st.button("下一题 →", type="primary", use_container_width=True,
                      key=f"next_{st.session_state.current_question_idx}"):
            # Save study log
            log = StudyLog(
                id=None,
                question_id=question.id,
                user_answer=result['user_answer'],
                is_correct=result['is_correct'],
                time_taken=result['time_taken'],
                error_category=error_category,
                error_detail=error_detail,
                timestamp=datetime.now().isoformat()
            )
            st.session_state.db.add_study_log(log)
            st.session_state.session_logs.append(log)

            # Check emergency drill
            drill = st.session_state.scheduler.record_answer(
                question, result['is_correct']
            )
            if drill:
                st.toast(f"⚠️ 连续错误检测: {drill.tag}，建议专项训练", icon="⚠️")

            # Advance
            st.session_state.current_question_idx += 1
            st.session_state.show_result = False
            st.session_state.question_start_time = None
            st.session_state.last_answer = None
            
            # Persist progress to DB
            current_plan = st.session_state.current_plan
            if current_plan and st.session_state.current_question_idx < len(current_plan.questions):
                _save_practice_state(current_plan, st.session_state.current_question_idx)
            else:
                _clear_practice_state()
            
            st.rerun()


def render_session_summary():
    """Render summary after completing a practice session."""
    st.header("🎉 练习完成！")

    logs = st.session_state.session_logs
    if not logs:
        st.info("没有记录。")
        if st.button("返回 Dashboard"):
            st.session_state.current_plan = None
            st.session_state.page = '🏠 Dashboard'
            st.rerun()
        return

    total = len(logs)
    correct = sum(1 for log in logs if log.is_correct)
    accuracy = (correct / total * 100) if total > 0 else 0
    avg_time = sum(log.time_taken for log in logs) / total if total > 0 else 0

    col1, col2, col3, col4 = st.columns(4)
    col1.metric("总题数", total)
    col2.metric("正确数", correct)
    col3.metric("正确率", f"{accuracy:.1f}%")
    col4.metric("平均用时", f"{avg_time:.0f}s")

    st.markdown("---")

    # AI Summary
    st.subheader("🤖 AI 学习总结")
    questions = {q.id: q for q in st.session_state.current_plan.questions}

    with st.spinner("生成总结..."):
        summary = st.session_state.tutor.generate_session_summary(logs, questions)
    st.markdown(summary)

    st.markdown("---")

    col1, col2 = st.columns(2)
    with col1:
        if st.button("📊 查看进度", use_container_width=True):
            st.session_state.current_plan = None
            _clear_practice_state()
            st.session_state.page = '📊 Progress'
            st.rerun()
    with col2:
        if st.button("🔄 再来一轮", use_container_width=True, type="primary"):
            st.session_state.current_plan = None
            st.session_state.current_question_idx = 0
            st.session_state.session_logs = []
            _clear_practice_state()
            st.session_state.page = '🏠 Dashboard'
            st.rerun()


# ============== Progress Page ==============

def render_progress():
    """Render the progress tracking page."""
    st.header("📊 Progress Tracking")

    progress = st.session_state.scheduler.get_progress_summary()

    col1, col2 = st.columns(2)
    col1.metric("总练习题数", progress['total_attempts'])
    col2.metric("整体正确率", f"{progress['overall_accuracy']}%")

    st.markdown("---")

    # Tag performance
    st.subheader("📈 各考点表现")
    if progress['tag_performance']:
        import pandas as pd
        df = pd.DataFrame(progress['tag_performance'])
        df = df.rename(columns={
            'tag': '考点', 'accuracy': '正确率 (%)', 'attempts': '尝试次数',
            'weight': '权重', 'status': '状态'
        })

        def highlight_status(row):
            colors = {'weak': '#ffcccc', 'improving': '#ffffcc', 'strong': '#ccffcc'}
            color = colors.get(row['状态'], '')
            return [f'background-color: {color}'] * len(row)

        st.dataframe(
            df.style.apply(highlight_status, axis=1),
            use_container_width=True, hide_index=True
        )
    else:
        st.info("暂无练习数据。")

    st.markdown("---")

    # Error analysis
    st.subheader("🔍 错误类型分析")
    logs = st.session_state.db.get_study_logs(limit=200)
    error_logs = [log for log in logs if not log.is_correct and log.error_category]

    if error_logs:
        import pandas as pd
        error_counts = {}
        for log in error_logs:
            error_counts[log.error_category] = error_counts.get(log.error_category, 0) + 1
        df_err = pd.DataFrame([{'错误类型': k, '次数': v} for k, v in error_counts.items()])
        st.bar_chart(df_err.set_index('错误类型'))
    else:
        st.info("暂无错误归因数据。做题后标记错误原因即可看到分析。")

    st.markdown("---")

    # Export
    st.subheader("💾 数据管理")
    col1, col2 = st.columns(2)
    with col1:
        if st.button("导出学习记录 (CSV)"):
            filepath = st.session_state.db.export_logs_to_csv()
            st.success(f"已导出: {filepath}")
    with col2:
        if st.button("备份数据库"):
            backup_path = st.session_state.db.backup_database()
            st.success(f"已备份: {backup_path}")


# ============== Settings Page ==============

def render_settings():
    """Render the settings page."""
    st.header("⚙️ Settings")

    # AI Config
    st.subheader("🤖 AI 配置")

    # CI/Secrets Status
    if st.secrets.get("ai", {}).get("api_key"):
        with st.expander("🔐 已检测到 Cloud Secrets 配置", expanded=True):
            s_model = st.secrets.get("ai", {}).get("model", "Unknown")
            s_base = st.secrets.get("ai", {}).get("base_url", "Unknown")
            st.success(f"已加载 Secrets 配置 (模型: `{s_model}`)")
            if s_model == "ark-code-latest" and "/coding" not in s_base:
                st.warning("⚠️ 检测到 Secrets 中的 Base URL 可能不匹配 Coding Plan。系统已自动为您修正。")
    # Provider presets
    provider = st.selectbox(
        "选择 AI 服务商",
        [
            "火山方舟 Coding Plan（推荐）",
            "火山方舟（标准 API）",
            "DeepSeek",
            "Moonshot",
            "OpenAI",
            "自定义",
        ],
        key="ai_provider"
    )

    provider_presets = {
        "火山方舟 Coding Plan（推荐）": {
            "base_url": "https://ark.cn-beijing.volces.com/api/coding/v3",
            "model_hint": "Coding Plan 用 ark-code-latest（自动选模型）",
            "default_model": "ark-code-latest",
            "help_text": (
                "**配置方法：** 登录 [火山方舟控制台](https://console.volcengine.com/ark) → "
                "左侧 API Key 管理 → 创建 API Key → 复制到下方。\n\n"
                "Coding Plan Lite/Pro 均可使用。"
            ),
        },
        "火山方舟（标准 API）": {
            "base_url": "https://ark.cn-beijing.volces.com/api/v3",
            "model_hint": "填 Model ID（如 doubao-seed-1-6-251015）或接入点 ID（ep-xxx）",
            "default_model": "doubao-seed-1-6-251015",
            "help_text": (
                "标准按量付费 API。登录控制台 → 模型列表 获取 Model ID，"
                "或创建推理接入点获取 Endpoint ID。"
            ),
        },
        "DeepSeek": {
            "base_url": "https://api.deepseek.com",
            "model_hint": "推荐 deepseek-chat",
            "default_model": "deepseek-chat",
            "help_text": "在 [DeepSeek 平台](https://platform.deepseek.com) 获取 API Key。",
        },
        "Moonshot": {
            "base_url": "https://api.moonshot.cn/v1",
            "model_hint": "推荐 moonshot-v1-8k",
            "default_model": "moonshot-v1-8k",
            "help_text": "在 Moonshot 开发者平台获取 API Key。",
        },
        "OpenAI": {
            "base_url": "",
            "model_hint": "推荐 gpt-4o-mini",
            "default_model": "gpt-4o-mini",
            "help_text": "在 OpenAI 平台获取 API Key。",
        },
        "自定义": {
            "base_url": "",
            "model_hint": "填你的模型名称",
            "default_model": "",
            "help_text": "任何兼容 OpenAI API 的服务均可使用。",
        },
    }

    preset = provider_presets[provider]
    
    # Auto-update model name if provider changes (and model_name is not set or matches old default)
    # We use a state tracking variable to detect provider switch
    if 'last_provider' not in st.session_state:
        st.session_state.last_provider = provider
    
    if st.session_state.last_provider != provider:
        st.session_state.model_name = preset['default_model']
        st.session_state.base_url = preset['base_url']
        st.session_state.last_provider = provider
        st.rerun()

    # Show help text
    st.info(preset['help_text'])

    col1, col2 = st.columns(2)
    with col1:
        api_key = st.text_input(
            "API Key",
            type="password",
            key="api_key",
            help="在服务商控制台获取"
        )
    with col2:
        model_name = st.text_input(
            "模型名称",
            key="model_name", # bind to session state
            help=preset['model_hint']
        )
    
    # Ensure base_url is synced with state for display
    if 'base_url' not in st.session_state:
        st.session_state.base_url = preset['base_url']

    # Only show base_url for custom provider
    if provider == "自定义":
        base_url = st.text_input(
            "API Base URL",
            key="base_url",
            help="填写服务商的 API 地址"
        )
    else:
        base_url = preset['base_url']
        if base_url:
            st.caption(f"📡 API 地址: `{base_url}`")

    if st.button("保存并测试连接", type="primary"):
        # Values are already in st.session_state due to widget keys
        # st.session_state.api_key = api_key 
        # st.session_state.model_name = model_name
        # st.session_state.base_url = base_url
        
        # Explicitly get latest from state
        api_key = st.session_state.api_key
        model_name = st.session_state.model_name
        base_url = st.session_state.get('base_url', '')

        config = TutorConfig(
            model=model_name,
            base_url=base_url if base_url else None,
        )
        
        # Runtime correction for manual entry
        if config.model == "ark-code-latest" and config.base_url and "/coding" not in config.base_url:
             config.base_url = "https://ark.cn-beijing.volces.com/api/coding/v3"
             st.info("💡 已自动将 API 地址修正为 Coding Plan 专用地址。")
        st.session_state.tutor = AITutor(config=config, api_key=api_key)
        
        # Save to DB for persistence
        try:
            db = get_db()
            db.save_session('api_key', api_key)
            db.save_session('model_name', model_name)
            if base_url:
                db.save_session('base_url', base_url)
            st.success("配置已保存！(设置已存入本地数据库，刷新页面不会丢失)")
        except Exception as e:
            st.warning(f"配置已生效，但保存到数据库失败: {e}")

        if st.session_state.tutor.is_available():
            with st.spinner("测试连接中..."):
                try:
                    client = st.session_state.tutor._get_client()
                    response = client.chat.completions.create(
                        model=model_name,
                        messages=[{"role": "user", "content": "Say OK"}],
                        max_tokens=10,
                    )
                    reply = response.choices[0].message.content if response.choices else "OK"
                    st.success(f"✅ 连接成功！模型回复: {reply[:50]}")
                except Exception as e:
                    err_msg = str(e)
                    st.error(f"❌ 连接失败: {err_msg[:300]}")
                    if "coding" in base_url and ("not found" in err_msg.lower() or "404" in err_msg):
                        st.warning(
                            "💡 Coding Plan 的 API 可能不支持通用对话。"
                            "建议切换到「火山方舟（标准 API）」，使用 Model ID 调用。"
                            "标准 API 按量计费，doubao 系列非常便宜（约 0.0004 元/千 tokens）。"
                        )
        else:
            st.warning("⚠️ 未连接（检查 API Key 和 openai 包是否已安装：pip install openai）")

    st.markdown("---")

    # Scheduler Config
    st.subheader("📅 调度器配置")
    col1, col2 = st.columns(2)
    with col1:
        default_q = st.number_input("默认每日题数", 5, 50, 20)
    with col2:
        max_consec = st.number_input("同考点最大连续题数", 1, 10, 3)

    keep_alive = st.slider("强项保持比例 (%)", 5, 30, 10)

    if st.button("保存调度器配置"):
        config = SchedulerConfig(
            default_question_count=default_q,
            max_consecutive_same_tag=max_consec,
            keep_alive_quota=keep_alive / 100
        )
        st.session_state.scheduler = Scheduler(config)
        st.success("✅ 已保存")

    st.markdown("---")

    # Data Management
    st.subheader("🗃️ 数据管理")
    stats = st.session_state.db.get_stats()
    st.info(f"当前: {stats['total_questions']} 道题，{stats['total_attempts']} 条记录")

    col1, col2, col3 = st.columns(3)
    with col1:
        if st.button("导入 OG 真题"):
            json_path = os.path.join(os.path.dirname(__file__), "og_questions.json")
            if os.path.exists(json_path):
                existing = st.session_state.db.get_all_questions()
                if existing:
                    st.warning("数据库已有题目，跳过导入")
                else:
                    with open(json_path, 'r', encoding='utf-8') as f:
                        questions = json.load(f)
                    for q in questions:
                        st.session_state.db.add_question(Question(
                            id=None, passage_id=None,
                            category=q.get('category', 'Verbal'),
                            subcategory=q.get('subcategory', 'CR'),
                            content=q['content'], options=q['options'],
                            correct_answer=q['correct_answer'],
                            skill_tags=q['skill_tags'],
                            difficulty=q.get('difficulty', 3),
                            explanation=q.get('explanation', ''),
                        ))
                    st.success(f"✅ 导入了 {len(questions)} 道题")
                    st.rerun()
            else:
                st.error("og_questions.json 不存在")

    with col2:
        if st.button("生成模拟数据"):
            from mock_data import generate_mock_questions, generate_mock_study_history, UserProfile
            existing = st.session_state.db.get_all_questions()
            if existing:
                st.warning("数据库已有数据")
            else:
                generate_mock_questions(st.session_state.db)
                profile = UserProfile(assumption_weakness=0.65, weaken_weakness=0.55, inference_weakness=0.25)
                generate_mock_study_history(st.session_state.db, 50, profile)
                st.success("✅ 模拟数据已生成")
                st.rerun()

    with col3:
        if st.button("🗑️ 重置数据"):
            import shutil
            st.session_state.db.close()
            if os.path.exists("gmat_tutor.db"):
                os.remove("gmat_tutor.db")
            # Re-init
            from database import DatabaseManager
            st.session_state.db = DatabaseManager()
            st.session_state.db_initialized = False
            st.success("✅ 已重置")
            st.rerun()


# ============== Main ==============

def main():
    page = render_sidebar()

    if page == "🏠 Dashboard":
        render_dashboard()
    elif page == "📝 Practice":
        render_practice()
    elif page == "📊 Progress":
        render_progress()
    elif page == "⚙️ Settings":
        render_settings()


if __name__ == "__main__":
    main()
