"""
GMAT Focus AI Tutor - Scheduler
Dynamic task scheduling based on weakness weights and spaced repetition.
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from dataclasses import dataclass
from database import get_db, Question, UserWeakness, StudyLog

# ============== Configuration ==============

@dataclass
class SchedulerConfig:
    """Configuration for the scheduler."""
    # Daily targets
    default_question_count: int = 20
    default_time_minutes: int = 60
    
    # Constraints
    max_consecutive_same_tag: int = 3
    keep_alive_quota: float = 0.10  # 10% of questions from mastered topics
    
    # Emergency drill thresholds
    consecutive_error_threshold: int = 3
    
    # Weights
    min_weight: float = 0.5
    max_weight: float = 5.0


# ============== Daily Plan ==============

@dataclass
class DailyPlan:
    """Represents a day's study plan."""
    questions: List[Question]
    estimated_time_minutes: int
    focus_tags: List[str]  # Tags with highest weights
    created_at: str
    
    def to_dict(self) -> Dict:
        return {
            "question_ids": [q.id for q in self.questions],
            "question_count": len(self.questions),
            "estimated_time_minutes": self.estimated_time_minutes,
            "focus_tags": self.focus_tags,
            "created_at": self.created_at
        }


@dataclass
class EmergencyDrill:
    """Triggered when user struggles with a specific tag."""
    tag: str
    questions: List[Question]
    reason: str
    triggered_at: str


# ============== Scheduler ==============

class Scheduler:
    def __init__(self, config: SchedulerConfig = None):
        self.config = config or SchedulerConfig()
        self.db = get_db()
        self._current_session_errors: Dict[str, int] = {}  # tag -> consecutive errors
    
    # ============== Main Planning ==============
    
    def generate_daily_plan(self,
                           question_count: int = None,
                           time_minutes: int = None,
                           subcategory: str = None,
                           skill_tag: str = None) -> DailyPlan:
        """
        Generate a daily study plan using weighted random sampling.

        Priority:
        1. Questions from high-weight (weak) tags
        2. Keep-alive questions from mastered tags
        3. New/unseen questions

        Args:
            question_count: Number of questions to include
            time_minutes: Unused, for future time-based planning
            subcategory: Filter by question type (CR, RC)
            skill_tag: Filter by specific skill tag (e.g., Boldface, Strengthen)
        """
        target_count = question_count or self.config.default_question_count

        # Get all data - apply filters
        if skill_tag:
            # Skill tag specified: use the new method
            all_questions = self.db.get_questions_by_skill_tag(skill_tag, subcategory, limit=500)
        elif subcategory:
            all_questions = [q for q in self.db.get_all_questions() if q.subcategory == subcategory]
        else:
            all_questions = self.db.get_all_questions()
        
        weaknesses = {w.tag: w for w in self.db.get_all_weaknesses()}
        
        if not all_questions:
            return DailyPlan(
                questions=[],
                estimated_time_minutes=0,
                focus_tags=[],
                created_at=datetime.now().isoformat()
            )
        
        # Calculate keep-alive quota
        keep_alive_count = max(1, int(target_count * self.config.keep_alive_quota))
        weakness_count = target_count - keep_alive_count
        
        selected_questions = []
        selected_ids = set()
        
        # Step 1: Select questions from weak areas (weighted random)
        weak_questions = self._weighted_sample(
            all_questions, weaknesses, weakness_count, selected_ids
        )
        selected_questions.extend(weak_questions)
        selected_ids.update(q.id for q in weak_questions)
        
        # Step 2: Add keep-alive questions from mastered areas
        mastered_tags = [tag for tag, w in weaknesses.items() if w.weight < 1.0]
        if mastered_tags:
            keep_alive_questions = self._sample_from_tags(
                all_questions, mastered_tags, keep_alive_count, selected_ids
            )
            selected_questions.extend(keep_alive_questions)
            selected_ids.update(q.id for q in keep_alive_questions)
        
        # Step 3: Fill remaining slots with random questions if needed
        remaining = target_count - len(selected_questions)
        if remaining > 0:
            available = [q for q in all_questions if q.id not in selected_ids]
            fill_questions = random.sample(available, min(remaining, len(available)))
            selected_questions.extend(fill_questions)
        
        # Step 4: Shuffle to avoid clustering, but respect max consecutive rule
        selected_questions = self._shuffle_with_constraints(selected_questions)
        
        # Identify focus tags (top 3 by weight)
        focus_tags = self._get_top_weakness_tags(weaknesses, 3)
        
        # Estimate time (2 minutes per question average)
        estimated_time = len(selected_questions) * 2
        
        return DailyPlan(
            questions=selected_questions,
            estimated_time_minutes=estimated_time,
            focus_tags=focus_tags,
            created_at=datetime.now().isoformat()
        )
    
    def _weighted_sample(self, 
                        questions: List[Question], 
                        weaknesses: Dict[str, UserWeakness],
                        count: int,
                        exclude_ids: set) -> List[Question]:
        """Sample questions with probability proportional to weakness weight."""
        available = [q for q in questions if q.id not in exclude_ids]
        if not available:
            return []
        
        # Calculate weights for each question
        weights = []
        for q in available:
            # Use max weight among question's tags
            q_weight = max(
                (weaknesses[tag].weight if tag in weaknesses else 1.0)
                for tag in q.skill_tags
            ) if q.skill_tags else 1.0
            weights.append(q_weight)
        
        # Normalize weights
        total_weight = sum(weights)
        if total_weight == 0:
            weights = [1.0] * len(available)
            total_weight = len(available)
        
        probabilities = [w / total_weight for w in weights]
        
        # Weighted sampling without replacement
        selected = []
        available_with_weights = list(zip(available, probabilities))
        
        for _ in range(min(count, len(available))):
            if not available_with_weights:
                break
            
            questions_list, probs = zip(*available_with_weights)
            # Renormalize
            total_p = sum(probs)
            probs = [p / total_p for p in probs]
            
            # Select one
            chosen_idx = random.choices(range(len(questions_list)), weights=probs)[0]
            selected.append(questions_list[chosen_idx])
            
            # Remove chosen
            available_with_weights.pop(chosen_idx)
        
        return selected
    
    def _sample_from_tags(self,
                         questions: List[Question],
                         tags: List[str],
                         count: int,
                         exclude_ids: set) -> List[Question]:
        """Sample questions that have any of the specified tags."""
        matching = [
            q for q in questions 
            if q.id not in exclude_ids and any(tag in q.skill_tags for tag in tags)
        ]
        return random.sample(matching, min(count, len(matching)))
    
    def _shuffle_with_constraints(self, questions: List[Question]) -> List[Question]:
        """
        Shuffle questions while ensuring no more than max_consecutive_same_tag
        questions of the same tag appear in sequence.
        """
        if len(questions) <= 1:
            return questions
        
        random.shuffle(questions)
        max_consecutive = self.config.max_consecutive_same_tag
        
        # Simple constraint enforcement: swap if too many consecutive
        for i in range(len(questions) - max_consecutive):
            # Check if next max_consecutive questions share a tag
            window = questions[i:i + max_consecutive + 1]
            common_tags = set(window[0].skill_tags)
            for q in window[1:]:
                common_tags &= set(q.skill_tags)
            
            if common_tags:
                # Too many consecutive - find a question to swap
                for j in range(i + max_consecutive + 1, len(questions)):
                    # Check if swapping would help
                    swap_candidate = questions[j]
                    if not (set(swap_candidate.skill_tags) & common_tags):
                        questions[i + max_consecutive], questions[j] = questions[j], questions[i + max_consecutive]
                        break
        
        return questions
    
    def _get_top_weakness_tags(self, weaknesses: Dict[str, UserWeakness], n: int) -> List[str]:
        """Get the top N tags by weakness weight."""
        sorted_tags = sorted(
            weaknesses.items(),
            key=lambda x: x[1].weight,
            reverse=True
        )
        return [tag for tag, _ in sorted_tags[:n]]
    
    # ============== Emergency Drill ==============
    
    def record_answer(self, question: Question, is_correct: bool) -> Optional[EmergencyDrill]:
        """
        Record an answer and check if emergency drill should be triggered.
        Returns EmergencyDrill if triggered, None otherwise.
        """
        for tag in question.skill_tags:
            if is_correct:
                self._current_session_errors[tag] = 0
            else:
                self._current_session_errors[tag] = self._current_session_errors.get(tag, 0) + 1
                
                if self._current_session_errors[tag] >= self.config.consecutive_error_threshold:
                    # Trigger emergency drill
                    drill = self._create_emergency_drill(tag)
                    self._current_session_errors[tag] = 0  # Reset counter
                    return drill
        
        return None
    
    def _create_emergency_drill(self, tag: str) -> EmergencyDrill:
        """Create an emergency drill focused on a specific tag."""
        all_questions = self.db.get_questions_by_tags([tag], limit=10)
        
        # Prefer questions not recently attempted
        recent_logs = self.db.get_recent_logs_by_tag(tag, days=7)
        recent_question_ids = {log.question_id for log in recent_logs}
        
        # Prioritize non-recent questions
        non_recent = [q for q in all_questions if q.id not in recent_question_ids]
        recent = [q for q in all_questions if q.id in recent_question_ids]
        
        drill_questions = non_recent[:5] if len(non_recent) >= 5 else non_recent + recent[:5-len(non_recent)]
        
        return EmergencyDrill(
            tag=tag,
            questions=drill_questions,
            reason=f"Consecutive errors detected in '{tag}' questions",
            triggered_at=datetime.now().isoformat()
        )
    
    def reset_session(self):
        """Reset session-specific tracking (call at start of new study session)."""
        self._current_session_errors = {}
    
    # ============== Analytics ==============
    
    def get_recommended_focus(self) -> Dict[str, any]:
        """
        Analyze weaknesses and provide recommendations.
        """
        weaknesses = self.db.get_all_weaknesses()
        stats = self.db.get_stats()
        
        if not weaknesses:
            return {
                "primary_focus": None,
                "secondary_focus": None,
                "message": "No study history yet. Start practicing to get personalized recommendations!"
            }
        
        # Sort by weight
        sorted_weaknesses = sorted(weaknesses, key=lambda w: w.weight, reverse=True)
        
        # Primary focus: highest weight
        primary = sorted_weaknesses[0] if sorted_weaknesses else None
        secondary = sorted_weaknesses[1] if len(sorted_weaknesses) > 1 else None
        
        # Calculate accuracy for primary focus
        primary_accuracy = None
        if primary and primary.total_attempts > 0:
            primary_accuracy = (primary.total_attempts - primary.error_count) / primary.total_attempts * 100
        
        # Generate message
        if primary and primary.weight > 2.0:
            message = f"⚠️ Focus on '{primary.tag}' - your accuracy is {primary_accuracy:.0f}% and needs improvement."
        elif primary and primary.weight > 1.5:
            message = f"📈 '{primary.tag}' is your weakest area at {primary_accuracy:.0f}% accuracy. Keep practicing!"
        else:
            message = "🎯 Your skills are well-balanced. Continue with mixed practice."
        
        return {
            "primary_focus": {
                "tag": primary.tag,
                "weight": primary.weight,
                "accuracy": primary_accuracy,
                "attempts": primary.total_attempts
            } if primary else None,
            "secondary_focus": {
                "tag": secondary.tag,
                "weight": secondary.weight
            } if secondary else None,
            "message": message,
            "overall_accuracy": stats.get('overall_accuracy', 0)
        }
    
    def get_progress_summary(self, days: int = 7) -> Dict:
        """Get a summary of progress over recent days."""
        stats = self.db.get_stats()
        weaknesses = self.db.get_all_weaknesses()
        
        # Tag performance
        tag_performance = []
        for w in weaknesses:
            accuracy = ((w.total_attempts - w.error_count) / w.total_attempts * 100) if w.total_attempts > 0 else 0
            tag_performance.append({
                "tag": w.tag,
                "accuracy": round(accuracy, 1),
                "attempts": w.total_attempts,
                "weight": w.weight,
                "status": "weak" if w.weight > 1.5 else "improving" if w.weight > 1.0 else "strong"
            })
        
        # Sort by weight (weakest first)
        tag_performance.sort(key=lambda x: x["weight"], reverse=True)
        
        return {
            "total_attempts": stats["total_attempts"],
            "overall_accuracy": stats["overall_accuracy"],
            "daily_trend": stats["daily_trend"],
            "tag_performance": tag_performance,
            "accuracy_by_type": stats["accuracy_by_type"]
        }


# ============== Quick Test ==============

def test_scheduler():
    """Quick test of scheduler functionality."""
    print("\n=== Testing Scheduler ===\n")
    
    scheduler = Scheduler()
    
    # Test daily plan generation
    print("Generating daily plan...")
    plan = scheduler.generate_daily_plan(question_count=10)
    print(f"  Questions in plan: {len(plan.questions)}")
    print(f"  Estimated time: {plan.estimated_time_minutes} minutes")
    print(f"  Focus tags: {plan.focus_tags}")
    
    # Test recommendations
    print("\nGetting recommendations...")
    recs = scheduler.get_recommended_focus()
    print(f"  Message: {recs['message']}")
    if recs['primary_focus']:
        print(f"  Primary focus: {recs['primary_focus']['tag']} (weight: {recs['primary_focus']['weight']:.2f})")
    
    # Test progress summary
    print("\nGetting progress summary...")
    progress = scheduler.get_progress_summary()
    print(f"  Total attempts: {progress['total_attempts']}")
    print(f"  Overall accuracy: {progress['overall_accuracy']}%")
    print("  Tag performance:")
    for tp in progress['tag_performance'][:3]:
        print(f"    - {tp['tag']}: {tp['accuracy']}% ({tp['status']})")
    
    print("\n✓ Scheduler test complete!")


if __name__ == "__main__":
    test_scheduler()
