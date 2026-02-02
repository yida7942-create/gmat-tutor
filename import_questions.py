"""
GMAT Focus AI Tutor - Import Questions from JSON
Import pre-extracted questions into the database.

This is the simplest way to load questions - no PDF parsing needed.
The og_questions.json file is already included in this package.

Usage:
    python import_questions.py
    python import_questions.py path/to/custom_questions.json
"""

import json
import sys
import os
from database import get_db, Question


def import_from_json(json_path: str = "og_questions.json"):
    """Import questions from a JSON file into the database."""

    if not os.path.exists(json_path):
        print(f"ERROR: File not found: {json_path}")
        print("Make sure og_questions.json is in the same directory.")
        sys.exit(1)

    with open(json_path, 'r', encoding='utf-8') as f:
        questions = json.load(f)

    print(f"Found {len(questions)} questions in {json_path}")

    db = get_db()

    # Check if database already has questions
    existing = db.get_all_questions()
    if existing:
        print(f"\nDatabase already has {len(existing)} questions.")
        response = input("Add these questions anyway? (y/n): ").strip().lower()
        if response != 'y':
            print("Skipped.")
            return

    count = 0
    for q in questions:
        db.add_question(Question(
            id=None,
            passage_id=None,
            category=q.get('category', 'Verbal'),
            subcategory=q.get('subcategory', 'CR'),
            content=q['content'],
            options=q['options'],
            correct_answer=q['correct_answer'],
            skill_tags=q['skill_tags'],
            difficulty=q.get('difficulty', 3),
            explanation=q.get('explanation', ''),
        ))
        count += 1

    print(f"\n✅ Imported {count} questions into database (gmat_tutor.db)")

    # Show summary
    stats = db.get_stats()
    print(f"\nDatabase now has:")
    print(f"  Total questions: {stats['total_questions']}")
    print(f"  Total study logs: {stats['total_attempts']}")


if __name__ == "__main__":
    json_path = sys.argv[1] if len(sys.argv) > 1 else "og_questions.json"
    import_from_json(json_path)
