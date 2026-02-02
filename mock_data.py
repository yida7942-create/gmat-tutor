"""
GMAT Focus AI Tutor - Mock Data Generator
Generates realistic CR questions and simulated study history for testing.
"""

import random
from datetime import datetime, timedelta
from typing import List, Dict
from database import get_db, Question, StudyLog

# ============== CR Question Templates ==============

CR_SKILL_TAGS = [
    "Assumption",
    "Strengthen",
    "Weaken",
    "Inference",
    "Evaluate",
    "Boldface"
]

CR_QUESTION_TEMPLATES = [
    {
        "skill_tags": ["Assumption"],
        "content": """A local restaurant's revenue increased by 20% after they started offering delivery services. The restaurant owner concludes that offering delivery has directly caused this revenue increase.

Which of the following is an assumption on which the owner's conclusion depends?""",
        "options": [
            "The restaurant's competitors do not offer delivery services.",
            "No other factors contributed to the revenue increase during this period.",
            "Delivery services are more profitable than dine-in services.",
            "The restaurant had been experiencing declining revenue before offering delivery.",
            "Customers prefer delivery over dining in at the restaurant."
        ],
        "correct_answer": 1,
        "explanation": "The argument assumes that delivery is THE cause of revenue increase. Option B is necessary - if other factors (like a new marketing campaign or seasonal trends) contributed, the conclusion would be weakened."
    },
    {
        "skill_tags": ["Assumption"],
        "content": """Studies show that employees who work from home report higher job satisfaction than those who work in offices. Therefore, companies should allow all employees to work from home to maximize overall job satisfaction.

The argument above assumes which of the following?""",
        "options": [
            "Working from home is possible for all types of jobs.",
            "Job satisfaction is the most important factor for employee retention.",
            "Employees who currently work from home would not prefer to work in an office.",
            "Companies that allow remote work have higher profits.",
            "The studies were conducted across multiple industries."
        ],
        "correct_answer": 0,
        "explanation": "The conclusion recommends ALL employees work from home. This assumes all jobs can be done remotely - if some jobs require physical presence, the recommendation fails."
    },
    {
        "skill_tags": ["Weaken"],
        "content": """A pharmaceutical company claims that its new headache medication is more effective than existing treatments because in clinical trials, 80% of participants reported relief within 30 minutes of taking the medication.

Which of the following, if true, most seriously weakens the company's claim?""",
        "options": [
            "The clinical trial included only 50 participants.",
            "Some participants experienced mild side effects.",
            "In trials of a placebo, 78% of participants reported similar relief.",
            "The medication costs more than existing treatments.",
            "The company has previously developed successful medications."
        ],
        "correct_answer": 2,
        "explanation": "If a placebo achieved nearly the same result (78% vs 80%), the medication may not be genuinely effective - the relief could be due to placebo effect, not the drug itself."
    },
    {
        "skill_tags": ["Weaken"],
        "content": """City officials argue that building a new sports stadium will boost the local economy because it will attract tourists who will spend money at local businesses.

Which of the following, if true, most weakens this argument?""",
        "options": [
            "The stadium will create 500 construction jobs.",
            "Similar stadiums in other cities have attracted millions of visitors.",
            "Most stadium visitors come from within the city and reduce spending at other local venues on game days.",
            "The stadium will be funded entirely by private investors.",
            "Professional sports teams increase civic pride."
        ],
        "correct_answer": 2,
        "explanation": "If visitors are mostly locals who shift spending from other venues rather than adding new spending, the net economic benefit is minimal - money is just moved around, not added."
    },
    {
        "skill_tags": ["Strengthen"],
        "content": """Researchers found that students who eat breakfast perform better on morning exams than students who skip breakfast. They concluded that eating breakfast improves cognitive performance.

Which of the following, if true, most strengthens the researchers' conclusion?""",
        "options": [
            "Students who eat breakfast also tend to get more sleep.",
            "The breakfast-eating students in the study came from wealthier families.",
            "When the same students were tested on days they skipped breakfast, their performance declined.",
            "Breakfast provides essential nutrients that the body needs.",
            "Morning exams are generally more difficult than afternoon exams."
        ],
        "correct_answer": 2,
        "explanation": "Option C provides a controlled comparison - the SAME students perform differently based on breakfast, eliminating confounding variables like inherent ability or background."
    },
    {
        "skill_tags": ["Strengthen"],
        "content": """A tech company noticed that teams using their new project management software completed projects 15% faster than before. The company concluded that the software improves team efficiency.

Which of the following, if true, most strengthens this conclusion?""",
        "options": [
            "The software is more expensive than competing products.",
            "Teams that did not adopt the software showed no change in completion time during the same period.",
            "The software includes features for tracking individual employee performance.",
            "The company has invested heavily in marketing the software.",
            "Some teams found the software difficult to learn initially."
        ],
        "correct_answer": 1,
        "explanation": "Option B provides a control group - if non-adopters showed no improvement, it supports that the software (not external factors like easier projects) caused the improvement."
    },
    {
        "skill_tags": ["Inference"],
        "content": """All of the books in the Highland Library's rare collection were published before 1900. Some books published before 1900 are worth more than $10,000. The Highland Library recently acquired a book published in 1850.

If the statements above are true, which of the following must also be true?""",
        "options": [
            "The book published in 1850 is worth more than $10,000.",
            "The book published in 1850 will be added to the rare collection.",
            "Some books in the rare collection are worth more than $10,000.",
            "The Highland Library's rare collection contains only valuable books.",
            "The book published in 1850 was published before 1900."
        ],
        "correct_answer": 4,
        "explanation": "1850 is before 1900 - this is a logical certainty. Options A and C use 'some' language that doesn't guarantee inclusion. Option B is not stated."
    },
    {
        "skill_tags": ["Inference"],
        "content": """No employee who has received a formal warning may be promoted within six months of the warning. John, a sales associate, was promoted last month. Maria, a marketing analyst, received a formal warning two months ago.

Based on the information above, which of the following must be true?""",
        "options": [
            "John did not receive a formal warning in the past six months.",
            "Maria will not be promoted within the next six months.",
            "John is a better employee than Maria.",
            "Maria will receive another warning soon.",
            "John has never received a formal warning."
        ],
        "correct_answer": 0,
        "explanation": "John was promoted, so he couldn't have had a warning in the past 6 months (per the rule). Option B is wrong - Maria only needs to wait 4 more months."
    },
    {
        "skill_tags": ["Evaluate"],
        "content": """A city reduced speed limits on residential streets from 30 mph to 25 mph. City officials claim this change has made the streets safer for pedestrians.

The answer to which of the following questions would be most useful in evaluating the officials' claim?""",
        "options": [
            "What is the average commute time for city residents?",
            "How do the new speed limits compare to those in neighboring cities?",
            "Has the number of pedestrian accidents on these streets changed since the speed limit reduction?",
            "Do most residents support the new speed limits?",
            "How much revenue do speeding tickets generate for the city?"
        ],
        "correct_answer": 2,
        "explanation": "To evaluate if streets are 'safer,' we need data on actual safety outcomes (accidents). Other options address popularity, revenue, or comparisons that don't measure safety."
    },
    {
        "skill_tags": ["Evaluate"],
        "content": """A company's CEO argues that the recent increase in employee productivity is due to the new open-office layout implemented six months ago.

Which of the following would be most important to know in order to evaluate the CEO's argument?""",
        "options": [
            "Whether the open-office layout cost more than the previous layout.",
            "Whether any other changes were made to workplace policies during the same period.",
            "Whether employees prefer the open-office layout.",
            "How the company's productivity compares to industry averages.",
            "Whether the CEO has experience with open-office layouts."
        ],
        "correct_answer": 1,
        "explanation": "If other changes (new software, bonuses, training) also occurred, they could explain productivity gains. We need to isolate the layout as the cause."
    },
    {
        "skill_tags": ["Boldface"],
        "content": """**Experts predict that electric vehicle sales will double within five years.** However, this prediction assumes that charging infrastructure will expand proportionally. **If charging stations remain scarce, consumers may be reluctant to switch from gasoline vehicles.**

In the argument above, the two boldface portions play which of the following roles?""",
        "options": [
            "The first is evidence that supports the main conclusion; the second is the main conclusion.",
            "The first is a prediction that the argument questions; the second presents a potential obstacle to that prediction.",
            "The first is the main conclusion; the second provides support for that conclusion.",
            "The first and second are both evidence supporting the same conclusion.",
            "The first is a prediction the argument accepts; the second is an alternative prediction."
        ],
        "correct_answer": 1,
        "explanation": "The first boldface is a prediction being examined. The word 'However' signals the argument will challenge it. The second boldface explains why the prediction might fail."
    },
    {
        "skill_tags": ["Boldface"],
        "content": """Some analysts argue that streaming services will completely replace traditional television within a decade. **The declining number of cable subscriptions seems to support this view.** However, **many consumers still prefer the simplicity of cable packages over managing multiple streaming subscriptions.**

The roles played by the two boldface portions are best described as:""",
        "options": [
            "The first presents evidence for a position; the second presents evidence against that same position.",
            "The first is the main conclusion; the second is a supporting premise.",
            "The first and second both support the analysts' argument.",
            "The first questions a prediction; the second explains why the prediction will come true.",
            "The first describes a trend; the second predicts how that trend will continue."
        ],
        "correct_answer": 0,
        "explanation": "First boldface supports the 'streaming replaces TV' view with evidence (declining cable). Second boldface counters with evidence for why cable might persist (simplicity preference)."
    },
    {
        "skill_tags": ["Assumption", "Strengthen"],
        "content": """A study found that cities with more public parks have lower rates of obesity among residents. The study's authors recommend that cities invest in building more parks to reduce obesity.

The recommendation depends on which of the following assumptions?""",
        "options": [
            "Obesity is a significant health problem in most cities.",
            "Building parks is less expensive than other obesity interventions.",
            "The presence of parks contributes to lower obesity rather than other factors common to both.",
            "All residents have equal access to public parks.",
            "Parks in different cities are similar in size and features."
        ],
        "correct_answer": 2,
        "explanation": "Correlation ≠ causation. The assumption is that parks cause lower obesity, not that both are caused by a third factor (like wealth or urban planning priorities)."
    },
    {
        "skill_tags": ["Weaken", "Assumption"],
        "content": """After a company implemented a four-day work week, employee satisfaction scores increased by 25%. Management concluded that shorter work weeks lead to happier employees.

Which of the following, if true, would most seriously undermine management's conclusion?""",
        "options": [
            "Some employees worked overtime during the four-day week.",
            "The company also increased salaries by 15% when implementing the new schedule.",
            "Other companies have tried four-day weeks with mixed results.",
            "Employee satisfaction was already improving before the change.",
            "The four-day week was more popular among younger employees."
        ],
        "correct_answer": 1,
        "explanation": "If salaries also increased, we can't attribute satisfaction gains to the shorter week alone. The pay raise could be the real cause."
    },
    {
        "skill_tags": ["Inference", "Assumption"],
        "content": """Every finalist in the science competition has published at least one research paper. Dr. Chen has published five research papers. The competition committee will announce the finalists next week.

Which of the following can be properly inferred from the statements above?""",
        "options": [
            "Dr. Chen will be named a finalist.",
            "Dr. Chen has met the publication requirement for finalists.",
            "Publishing research papers guarantees becoming a finalist.",
            "The competition values research publications.",
            "Dr. Chen is more likely to be a finalist than someone with one paper."
        ],
        "correct_answer": 1,
        "explanation": "We know finalists need 'at least one' paper. Chen has five, so she meets this requirement. But meeting the requirement doesn't guarantee selection (A is wrong)."
    }
]

# Additional templates for variety
CR_ADDITIONAL_TEMPLATES = [
    {
        "skill_tags": ["Assumption"],
        "content": """Online sales of Company X increased by 40% after they redesigned their website. The marketing team concludes that the website redesign was responsible for the sales increase.

Which of the following is an assumption required by this conclusion?""",
        "options": [
            "The website redesign cost less than the increase in revenue.",
            "Customers find the new website design more visually appealing.",
            "The sales increase was not primarily caused by factors unrelated to the website redesign.",
            "Company X's competitors did not redesign their websites.",
            "Online shopping has become more popular in recent years."
        ],
        "correct_answer": 2,
        "explanation": "The argument assumes website redesign = cause of sales increase. If external factors (holiday season, price drops) caused it, the conclusion fails."
    },
    {
        "skill_tags": ["Weaken"],
        "content": """A fitness center claims that members who attend their yoga classes experience 30% less stress than non-members. The center uses this data to argue that yoga reduces stress.

Which of the following, if true, most weakens the fitness center's argument?""",
        "options": [
            "Yoga classes are the most popular offering at the fitness center.",
            "People who actively seek to reduce stress are more likely to join yoga classes.",
            "The fitness center offers other stress-reduction programs.",
            "Some yoga instructors have more experience than others.",
            "Yoga has been practiced for thousands of years."
        ],
        "correct_answer": 1,
        "explanation": "This is selection bias. If low-stress-seekers self-select into yoga, the correlation doesn't show yoga reduces stress - less-stressed people simply chose yoga."
    },
    {
        "skill_tags": ["Strengthen"],
        "content": """Hospital A has a higher patient mortality rate than Hospital B. A healthcare analyst concluded that Hospital B provides better quality care than Hospital A.

Which of the following, if true, most strengthens the analyst's conclusion?""",
        "options": [
            "Hospital A is a teaching hospital with medical students.",
            "Hospital A and Hospital B treat patients with similar severity of conditions.",
            "Hospital B has more doctors per patient than Hospital A.",
            "Hospital A is located in an urban area while Hospital B is suburban.",
            "Hospital B was recently renovated."
        ],
        "correct_answer": 1,
        "explanation": "The main objection to comparing mortality rates is case mix - if Hospital A treats sicker patients, higher mortality is expected. Option B eliminates this confound."
    },
    {
        "skill_tags": ["Evaluate"],
        "content": """A school district claims that its new math curriculum has improved student performance because average test scores increased by 10% this year.

The answer to which of the following questions would be most useful in evaluating the district's claim?""",
        "options": [
            "What percentage of students passed the math test?",
            "How does the new curriculum differ from the previous one?",
            "Did the difficulty level of the math test change this year?",
            "How much did the new curriculum cost to implement?",
            "What do teachers think of the new curriculum?"
        ],
        "correct_answer": 2,
        "explanation": "If the test got easier, score increases don't reflect real improvement. We need to know if we're comparing apples to apples."
    },
    {
        "skill_tags": ["Inference"],
        "content": """All managers at TechCorp must complete a leadership training program. No one who completed the program before 2020 is eligible for the senior executive track. James is a manager at TechCorp who is on the senior executive track.

If the statements above are true, which of the following must be true?""",
        "options": [
            "James is an excellent manager.",
            "James completed the leadership training program in 2020 or later.",
            "James will become a senior executive.",
            "James has worked at TechCorp since before 2020.",
            "The leadership training program was updated in 2020."
        ],
        "correct_answer": 1,
        "explanation": "James is a manager (so he completed training). He's on executive track (so he can't have completed before 2020). Therefore: completed in 2020 or later."
    }
]

# ============== User Profile for Simulation ==============

class UserProfile:
    """Simulates a user with specific strengths and weaknesses."""
    
    def __init__(self, 
                 assumption_weakness: float = 0.6,
                 strengthen_weakness: float = 0.4,
                 weaken_weakness: float = 0.5,
                 inference_weakness: float = 0.3,
                 evaluate_weakness: float = 0.4,
                 boldface_weakness: float = 0.35):
        """
        Weakness values = probability of getting a question wrong.
        Higher = weaker in this area.
        """
        self.weakness_map = {
            "Assumption": assumption_weakness,
            "Strengthen": strengthen_weakness,
            "Weaken": weaken_weakness,
            "Inference": inference_weakness,
            "Evaluate": evaluate_weakness,
            "Boldface": boldface_weakness
        }
    
    def will_answer_correctly(self, skill_tags: List[str]) -> bool:
        """Simulate whether user answers correctly based on their weakness profile."""
        # Use the highest weakness among the question's tags
        max_weakness = max(self.weakness_map.get(tag, 0.3) for tag in skill_tags)
        return random.random() > max_weakness
    
    def get_error_type(self, skill_tags: List[str]) -> tuple:
        """Generate a plausible error category and detail."""
        error_categories = {
            "Understanding": ["Text Misinterpretation", "Option Misinterpretation"],
            "Reasoning": ["Confusion (Suff/Nec)", "Reverse Causality", "Scope Shift", "Trap Answer"],
            "Execution": ["Time Pressure", "Careless"]
        }
        
        # Weight reasoning errors higher for logic-heavy tags
        if any(tag in ["Assumption", "Weaken", "Strengthen"] for tag in skill_tags):
            weights = [0.2, 0.6, 0.2]
        else:
            weights = [0.3, 0.4, 0.3]
        
        category = random.choices(list(error_categories.keys()), weights=weights)[0]
        detail = random.choice(error_categories[category])
        return category, detail


# ============== Data Generation Functions ==============

def generate_mock_questions(db=None) -> int:
    """Generate mock CR questions and insert into database."""
    if db is None:
        db = get_db()
    
    all_templates = CR_QUESTION_TEMPLATES + CR_ADDITIONAL_TEMPLATES
    count = 0
    
    for template in all_templates:
        q = Question(
            id=None,
            passage_id=None,
            category="Verbal",
            subcategory="CR",
            content=template["content"],
            options=template["options"],
            correct_answer=template["correct_answer"],
            skill_tags=template["skill_tags"],
            difficulty=random.randint(2, 4),
            explanation=template.get("explanation")
        )
        db.add_question(q)
        count += 1
    
    print(f"✓ Generated {count} CR questions")
    return count


def generate_mock_study_history(db=None, num_sessions: int = 50, profile: UserProfile = None) -> int:
    """
    Generate simulated study history based on a user profile.
    This creates realistic patterns of mistakes for testing the scheduler.
    """
    if db is None:
        db = get_db()
    if profile is None:
        # Default profile: weak in Assumption and Weaken
        profile = UserProfile(
            assumption_weakness=0.65,
            strengthen_weakness=0.35,
            weaken_weakness=0.55,
            inference_weakness=0.25,
            evaluate_weakness=0.40,
            boldface_weakness=0.30
        )
    
    questions = db.get_all_questions()
    if not questions:
        print("✗ No questions in database. Run generate_mock_questions() first.")
        return 0
    
    count = 0
    base_time = datetime.now() - timedelta(days=14)  # Start from 2 weeks ago
    
    for i in range(num_sessions):
        # Pick a random question
        q = random.choice(questions)
        
        # Simulate answer based on profile
        is_correct = profile.will_answer_correctly(q.skill_tags)
        
        # Generate answer
        if is_correct:
            user_answer = q.correct_answer
            error_category = None
            error_detail = None
        else:
            # Pick a wrong answer
            wrong_options = [j for j in range(5) if j != q.correct_answer]
            user_answer = random.choice(wrong_options)
            error_category, error_detail = profile.get_error_type(q.skill_tags)
        
        # Simulate time taken (60-180 seconds, faster for correct answers)
        base_time_taken = random.randint(60, 150)
        if is_correct:
            time_taken = int(base_time_taken * 0.8)
        else:
            time_taken = int(base_time_taken * 1.2)
        
        # Create timestamp (spread over past 2 weeks)
        timestamp = base_time + timedelta(
            days=random.randint(0, 14),
            hours=random.randint(8, 22),
            minutes=random.randint(0, 59)
        )
        
        log = StudyLog(
            id=None,
            question_id=q.id,
            user_answer=user_answer,
            is_correct=is_correct,
            time_taken=time_taken,
            error_category=error_category,
            error_detail=error_detail,
            timestamp=timestamp.isoformat()
        )
        db.add_study_log(log)
        count += 1
    
    print(f"✓ Generated {count} study log entries")
    return count


def initialize_mock_data():
    """Full initialization: create questions and simulated history."""
    db = get_db()
    
    # Check if data already exists
    existing_questions = db.get_all_questions()
    if existing_questions:
        print(f"Database already contains {len(existing_questions)} questions.")
        response = input("Reset and regenerate? (y/n): ").strip().lower()
        if response != 'y':
            print("Skipping data generation.")
            return
        
        # Reset database
        import os
        db.close()
        os.remove("gmat_tutor.db")
        db = DatabaseManager()
    
    print("\n=== Generating Mock Data ===\n")
    
    # Generate questions
    generate_mock_questions(db)
    
    # Generate study history with a specific profile
    profile = UserProfile(
        assumption_weakness=0.65,  # Struggles with assumptions
        strengthen_weakness=0.35,  # OK at strengthen
        weaken_weakness=0.55,      # Struggles with weaken
        inference_weakness=0.25,   # Good at inference
        evaluate_weakness=0.40,    # OK at evaluate
        boldface_weakness=0.30     # Good at boldface
    )
    generate_mock_study_history(db, num_sessions=50, profile=profile)
    
    # Print summary
    print("\n=== Summary ===")
    stats = db.get_stats()
    print(f"Total questions: {stats['total_questions']}")
    print(f"Total attempts: {stats['total_attempts']}")
    print(f"Overall accuracy: {stats['overall_accuracy']}%")
    
    print("\n=== Weakness Weights ===")
    weaknesses = db.get_all_weaknesses()
    for w in weaknesses:
        accuracy = ((w.total_attempts - w.error_count) / w.total_attempts * 100) if w.total_attempts > 0 else 0
        print(f"  {w.tag}: weight={w.weight:.2f}, accuracy={accuracy:.1f}% ({w.total_attempts} attempts)")


if __name__ == "__main__":
    initialize_mock_data()
