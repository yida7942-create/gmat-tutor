"""
GMAT Focus AI Tutor - Database Layer
Micro-ORM using SQLite for question bank and study tracking.
"""

import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from dataclasses import dataclass, asdict
import os

DB_PATH = "gmat_tutor.db"

# ============== Data Classes ==============

@dataclass
class Passage:
    id: Optional[int]
    content: str
    category: str  # Science, Business, Social
    word_count: int

@dataclass
class Question:
    id: Optional[int]
    passage_id: Optional[int]
    category: str  # Verbal, Quant, DI
    subcategory: str  # CR, RC, DS, PS, etc.
    content: str
    options: List[str]  # JSON stored as text
    correct_answer: int  # 0-4 index
    skill_tags: List[str]  # JSON stored as text
    difficulty: int  # 1-5
    explanation: Optional[str] = None

@dataclass
class StudyLog:
    id: Optional[int]
    question_id: int
    user_answer: int
    is_correct: bool
    time_taken: int  # seconds
    error_category: Optional[str]  # Understanding, Reasoning, Execution
    error_detail: Optional[str]  # Specific error type
    timestamp: str

@dataclass
class UserWeakness:
    tag: str
    error_count: int
    total_attempts: int
    last_seen: str
    weight: float

# ============== Database Manager ==============

class DatabaseManager:
    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        self.conn = None
        try:
            self._connect()
            self._create_tables()
        except sqlite3.DatabaseError:
            # Self-healing: Delete corrupt DB and retry
            if self.conn:
                self.conn.close()
            if os.path.exists(self.db_path):
                os.remove(self.db_path)
            self._connect()
            self._create_tables()
    
    def _connect(self):
        self.conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
    
    def _create_tables(self):
        cursor = self.conn.cursor()
        
        # Passages table (for RC)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS passages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                content TEXT NOT NULL,
                category TEXT NOT NULL,
                word_count INTEGER NOT NULL
            )
        """)
        
        # Questions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS questions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                passage_id INTEGER,
                category TEXT NOT NULL,
                subcategory TEXT NOT NULL,
                content TEXT NOT NULL,
                options TEXT NOT NULL,
                correct_answer INTEGER NOT NULL,
                skill_tags TEXT NOT NULL,
                difficulty INTEGER NOT NULL,
                explanation TEXT,
                FOREIGN KEY (passage_id) REFERENCES passages(id)
            )
        """)
        
        # Study logs table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS study_logs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                question_id INTEGER NOT NULL,
                user_answer INTEGER NOT NULL,
                is_correct BOOLEAN NOT NULL,
                time_taken INTEGER NOT NULL,
                error_category TEXT,
                error_detail TEXT,
                timestamp TEXT NOT NULL,
                FOREIGN KEY (question_id) REFERENCES questions(id)
            )
        """)
        
        # User weaknesses table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS user_weaknesses (
                tag TEXT PRIMARY KEY,
                error_count INTEGER NOT NULL DEFAULT 0,
                total_attempts INTEGER NOT NULL DEFAULT 0,
                last_seen TEXT,
                weight REAL NOT NULL DEFAULT 1.0
            )
        """)
        
        # Session store table (persist practice state across browser refreshes)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS session_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
        """)
        
        self.conn.commit()
    
    # ============== Question CRUD ==============
    
    def add_question(self, q: Question) -> int:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO questions (passage_id, category, subcategory, content, options, correct_answer, skill_tags, difficulty, explanation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            q.passage_id,
            q.category,
            q.subcategory,
            q.content,
            json.dumps(q.options),
            q.correct_answer,
            json.dumps(q.skill_tags),
            q.difficulty,
            q.explanation
        ))
        self.conn.commit()
        return cursor.lastrowid
    
    def get_question(self, question_id: int) -> Optional[Question]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM questions WHERE id = ?", (question_id,))
        row = cursor.fetchone()
        if row:
            return self._row_to_question(row)
        return None
    
    def get_questions_by_tags(self, tags: List[str], limit: int = 50) -> List[Question]:
        """Get questions that have any of the specified tags."""
        cursor = self.conn.cursor()
        # SQLite doesn't have native JSON array search, so we use LIKE
        conditions = " OR ".join(["skill_tags LIKE ?" for _ in tags])
        params = [f'%"{tag}"%' for tag in tags]
        cursor.execute(f"""
            SELECT * FROM questions WHERE {conditions} LIMIT ?
        """, params + [limit])
        return [self._row_to_question(row) for row in cursor.fetchall()]
    
    def get_questions_by_subcategory(self, subcategory: str, limit: int = 50) -> List[Question]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM questions WHERE subcategory = ? LIMIT ?
        """, (subcategory, limit))
        return [self._row_to_question(row) for row in cursor.fetchall()]
    
    def get_all_questions(self) -> List[Question]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM questions")
        return [self._row_to_question(row) for row in cursor.fetchall()]
    
    def get_unanswered_questions(self) -> List[Question]:
        """Get questions that haven't been attempted yet."""
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT q.* FROM questions q
            LEFT JOIN study_logs sl ON q.id = sl.question_id
            WHERE sl.id IS NULL
        """)
        return [self._row_to_question(row) for row in cursor.fetchall()]
    
    def _row_to_question(self, row) -> Question:
        return Question(
            id=row['id'],
            passage_id=row['passage_id'],
            category=row['category'],
            subcategory=row['subcategory'],
            content=row['content'],
            options=json.loads(row['options']),
            correct_answer=row['correct_answer'],
            skill_tags=json.loads(row['skill_tags']),
            difficulty=row['difficulty'],
            explanation=row['explanation']
        )
    
    # ============== Study Log CRUD ==============
    
    def add_study_log(self, log: StudyLog) -> int:
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT INTO study_logs (question_id, user_answer, is_correct, time_taken, error_category, error_detail, timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            log.question_id,
            log.user_answer,
            log.is_correct,
            log.time_taken,
            log.error_category,
            log.error_detail,
            log.timestamp
        ))
        self.conn.commit()
        
        # Update weakness weights after logging
        question = self.get_question(log.question_id)
        if question:
            for tag in question.skill_tags:
                self._update_weakness(tag, not log.is_correct)
        
        return cursor.lastrowid
    
    def get_study_logs(self, limit: int = 100) -> List[StudyLog]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM study_logs ORDER BY timestamp DESC LIMIT ?
        """, (limit,))
        return [self._row_to_study_log(row) for row in cursor.fetchall()]
    
    def get_logs_for_question(self, question_id: int) -> List[StudyLog]:
        cursor = self.conn.cursor()
        cursor.execute("""
            SELECT * FROM study_logs WHERE question_id = ? ORDER BY timestamp DESC
        """, (question_id,))
        return [self._row_to_study_log(row) for row in cursor.fetchall()]
    
    def get_recent_logs_by_tag(self, tag: str, days: int = 7) -> List[StudyLog]:
        """Get logs for questions with a specific tag from recent days."""
        cursor = self.conn.cursor()
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        cursor.execute("""
            SELECT sl.* FROM study_logs sl
            JOIN questions q ON sl.question_id = q.id
            WHERE q.skill_tags LIKE ? AND sl.timestamp > ?
            ORDER BY sl.timestamp DESC
        """, (f'%"{tag}"%', cutoff))
        return [self._row_to_study_log(row) for row in cursor.fetchall()]
    
    def _row_to_study_log(self, row) -> StudyLog:
        return StudyLog(
            id=row['id'],
            question_id=row['question_id'],
            user_answer=row['user_answer'],
            is_correct=bool(row['is_correct']),
            time_taken=row['time_taken'],
            error_category=row['error_category'],
            error_detail=row['error_detail'],
            timestamp=row['timestamp']
        )
    
    # ============== Weakness Management ==============
    
    def _update_weakness(self, tag: str, is_error: bool):
        """Update weakness weight after an attempt."""
        cursor = self.conn.cursor()
        now = datetime.now().isoformat()
        
        # Check if tag exists
        cursor.execute("SELECT * FROM user_weaknesses WHERE tag = ?", (tag,))
        row = cursor.fetchone()
        
        if row:
            new_error_count = row['error_count'] + (1 if is_error else 0)
            new_total = row['total_attempts'] + 1
            new_weight = self._calculate_weight(new_error_count, new_total, now, row['last_seen'])
            
            cursor.execute("""
                UPDATE user_weaknesses 
                SET error_count = ?, total_attempts = ?, last_seen = ?, weight = ?
                WHERE tag = ?
            """, (new_error_count, new_total, now, new_weight, tag))
        else:
            weight = 2.0 if is_error else 1.0
            cursor.execute("""
                INSERT INTO user_weaknesses (tag, error_count, total_attempts, last_seen, weight)
                VALUES (?, ?, 1, ?, ?)
            """, (tag, 1 if is_error else 0, now, weight))
        
        self.conn.commit()
    
    def _calculate_weight(self, error_count: int, total: int, now: str, last_seen: str) -> float:
        """
        Weight formula: Base * RecentErrorRate * TimeDecay
        - High error rate + Recently seen = High weight (needs practice)
        - Low error rate + Long time no see = Medium weight (keep-alive)
        - Low error rate + Recently seen = Low weight (mastered)
        """
        BASE_WEIGHT = 1.0
        
        # Error rate component (0.5 to 2.0)
        error_rate = error_count / total if total > 0 else 0.5
        error_factor = 0.5 + (error_rate * 1.5)
        
        # Time decay component (0.8 to 1.5)
        try:
            last_dt = datetime.fromisoformat(last_seen)
            now_dt = datetime.fromisoformat(now)
            days_since = (now_dt - last_dt).days
        except:
            days_since = 0
        
        # Longer time = higher weight (need to revisit)
        # But cap at 1.5 to avoid over-weighting old topics
        time_factor = min(1.5, 0.8 + (days_since * 0.05))
        
        # Keep-alive: if error rate is low but time is long, boost slightly
        if error_rate < 0.3 and days_since > 7:
            time_factor = max(time_factor, 1.2)
        
        return round(BASE_WEIGHT * error_factor * time_factor, 2)
    
    def get_all_weaknesses(self) -> List[UserWeakness]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM user_weaknesses ORDER BY weight DESC")
        return [
            UserWeakness(
                tag=row['tag'],
                error_count=row['error_count'],
                total_attempts=row['total_attempts'],
                last_seen=row['last_seen'],
                weight=row['weight']
            )
            for row in cursor.fetchall()
        ]
    
    def get_weakness_by_tag(self, tag: str) -> Optional[UserWeakness]:
        cursor = self.conn.cursor()
        cursor.execute("SELECT * FROM user_weaknesses WHERE tag = ?", (tag,))
        row = cursor.fetchone()
        if row:
            return UserWeakness(
                tag=row['tag'],
                error_count=row['error_count'],
                total_attempts=row['total_attempts'],
                last_seen=row['last_seen'],
                weight=row['weight']
            )
        return None
    
    # ============== Statistics ==============
    
    def get_stats(self) -> Dict[str, Any]:
        cursor = self.conn.cursor()
        
        # Total questions
        cursor.execute("SELECT COUNT(*) as count FROM questions")
        total_questions = cursor.fetchone()['count']
        
        # Total attempts
        cursor.execute("SELECT COUNT(*) as count FROM study_logs")
        total_attempts = cursor.fetchone()['count']
        
        # Correct attempts
        cursor.execute("SELECT COUNT(*) as count FROM study_logs WHERE is_correct = 1")
        correct_attempts = cursor.fetchone()['count']
        
        # Accuracy by subcategory
        cursor.execute("""
            SELECT q.subcategory, 
                   COUNT(*) as total,
                   SUM(CASE WHEN sl.is_correct THEN 1 ELSE 0 END) as correct
            FROM study_logs sl
            JOIN questions q ON sl.question_id = q.id
            GROUP BY q.subcategory
        """)
        accuracy_by_type = {
            row['subcategory']: {
                'total': row['total'],
                'correct': row['correct'],
                'accuracy': round(row['correct'] / row['total'] * 100, 1) if row['total'] > 0 else 0
            }
            for row in cursor.fetchall()
        }
        
        # Recent 7-day trend
        cursor.execute("""
            SELECT DATE(timestamp) as date,
                   COUNT(*) as total,
                   SUM(CASE WHEN is_correct THEN 1 ELSE 0 END) as correct
            FROM study_logs
            WHERE timestamp > datetime('now', '-7 days')
            GROUP BY DATE(timestamp)
            ORDER BY date
        """)
        daily_trend = [
            {
                'date': row['date'],
                'total': row['total'],
                'correct': row['correct'],
                'accuracy': round(row['correct'] / row['total'] * 100, 1) if row['total'] > 0 else 0
            }
            for row in cursor.fetchall()
        ]
        
        return {
            'total_questions': total_questions,
            'total_attempts': total_attempts,
            'correct_attempts': correct_attempts,
            'overall_accuracy': round(correct_attempts / total_attempts * 100, 1) if total_attempts > 0 else 0,
            'accuracy_by_type': accuracy_by_type,
            'daily_trend': daily_trend
        }
    
    def get_question_counts_by_type(self) -> Dict[str, int]:
        """Return question counts grouped by subcategory."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT subcategory, COUNT(*) as count FROM questions GROUP BY subcategory")
        return {row['subcategory']: row['count'] for row in cursor.fetchall()}
    
    # ============== Backup ==============
    
    def export_logs_to_csv(self, filepath: str = "study_logs_export.csv"):
        import csv
        logs = self.get_study_logs(limit=10000)
        
        with open(filepath, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['id', 'question_id', 'user_answer', 'is_correct', 'time_taken', 'error_category', 'error_detail', 'timestamp'])
            for log in logs:
                writer.writerow([
                    log.id, log.question_id, log.user_answer, log.is_correct,
                    log.time_taken, log.error_category, log.error_detail, log.timestamp
                ])
        return filepath
    
    def backup_database(self, backup_dir: str = "backups"):
        import shutil
        os.makedirs(backup_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_path = os.path.join(backup_dir, f"gmat_tutor_{timestamp}.db")
        shutil.copy(self.db_path, backup_path)
        return backup_path
    
    # ============== Session Store ==============
    
    def save_session(self, key: str, value: str):
        """Save a key-value pair for session persistence."""
        cursor = self.conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO session_store (key, value, updated_at)
            VALUES (?, ?, ?)
        """, (key, value, datetime.now().isoformat()))
        self.conn.commit()
    
    def load_session(self, key: str) -> Optional[str]:
        """Load a value by key. Returns None if not found."""
        cursor = self.conn.cursor()
        cursor.execute("SELECT value FROM session_store WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row['value'] if row else None
    
    def delete_session(self, key: str):
        """Delete a session key."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM session_store WHERE key = ?", (key,))
        self.conn.commit()
    
    def clear_session(self):
        """Clear all session data."""
        cursor = self.conn.cursor()
        cursor.execute("DELETE FROM session_store")
        self.conn.commit()
    
    def checkpoint(self):
        """Force WAL data into the main database file.

        SQLite WAL mode stores committed data in a separate .db-wal file.
        Without checkpointing, the main .db file may not contain latest data.
        This MUST be called before uploading the .db file to cloud backup.
        """
        if self.conn:
            try:
                self.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except Exception:
                pass

    def close(self):
        if self.conn:
            self.checkpoint()
            self.conn.close()


# ============== Singleton Instance ==============

_db_instance = None

def get_db() -> DatabaseManager:
    global _db_instance
    if _db_instance is None:
        _db_instance = DatabaseManager()
    return _db_instance
