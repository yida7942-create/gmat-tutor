"""
GMAT Focus AI Tutor - OG Question Extractor
Extracts Critical Reasoning questions from the GMAT Official Guide Verbal Review PDF.

Works on Windows, macOS, and Linux (uses pypdf, no external tools needed).

Usage:
    python extract_og.py <pdf_path>
    python extract_og.py <pdf_path> --import
    python extract_og.py <pdf_path> --csv
"""

import re
import json
import sys
import os
from typing import List, Dict, Optional, Tuple


# ============== Configuration ==============

RC_QUESTION_START = 1
RC_QUESTION_END = 140
CR_QUESTION_START = 141
CR_QUESTION_END = 289

RC_DIFFICULTY_RANGES = [
    (1, 44, "Easy", 2),
    (45, 100, "Medium", 3),
    (101, 140, "Hard", 4),
]

CR_DIFFICULTY_RANGES = [
    (141, 192, "Easy", 2),
    (193, 235, "Medium", 3),
    (236, 289, "Hard", 4),
]

# Combined for backward compatibility
DIFFICULTY_RANGES = RC_DIFFICULTY_RANGES + CR_DIFFICULTY_RANGES

SKILL_TAG_PATTERNS = [
    (r"assumption.*(depends|required|requires)|assumes which|is an assumption (that|on which)", ["Assumption"]),
    (r"weakens|undermines?|undermine|calls into question|casts.*doubt|argue.*against|serious(ly)? (weaken|undercut)|most serious (doubt|weakness)|reject|counter", ["Weaken"]),
    (r"most useful (in|to).*(evaluat|establish|determin|decid)|most (important|helpful) to (know|determine|evaluate)|would be most useful to know|useful in evaluating|most useful results for evaluating|help in deciding", ["Evaluate"]),
    (r"boldface|bold face|two portions|two boldfaced|which of the following roles", ["Boldface"]),
    (r"resolve|explain.*discrepancy|helps? to explain|account for.*difference|apparent (discrepancy|paradox)|explain the contrast|explain why|best prospects for explaining|explain.*deaths", ["Resolve/Explain"]),
    (r"flaw|error in.*reasoning|vulnerable to.*criticism|most accurately describes|reasoning is flawed|weak point|best describes the.*point", ["Flaw/Describe"]),
    (r"can be (properly |logically )?(inferred|concluded)|must (also )?be true|properly concluded|logically follows|conclusions?\s*(can|could)|best supported by the observations|which of the following conclusions", ["Inference"]),
    (r"most likely (conclusion|completes)|logically completes|following\?\s*$", ["Complete/Conclude"]),
    (r"most (strongly )?(supports?|support)|strengthen|provides?.*(support|strongest|justification|reason|indication)|tends? to confirm|if true.*(suggest|indicate|support)|best prospect|support the (hypothesis|view|expectation|claim|conclusion)|strongest reason", ["Strengthen"]),
]


# ============== Step 1: Extract & Clean Text ==============

def extract_and_clean(pdf_path: str) -> List[str]:
    """Extract text from PDF using pypdf, or read as plain text fallback."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    lines_raw = None
    
    # Try pypdf first
    try:
        from pypdf import PdfReader
        print(f"  Reading {pdf_path} with pypdf...")
        reader = PdfReader(pdf_path)
        print(f"  {len(reader.pages)} pages found")
        all_text = []
        for i, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                all_text.append(text)
        lines_raw = '\n'.join(all_text).split('\n')
    except Exception as e:
        print(f"  pypdf failed ({e}), trying plain text fallback...")
    
    # Fallback: read as plain text (for VitalSource HTML-saved-as-PDF files)
    if lines_raw is None:
        try:
            with open(pdf_path, 'r', encoding='utf-8', errors='replace') as f:
                lines_raw = f.readlines()
            lines_raw = [line.rstrip('\r\n') for line in lines_raw]
            print(f"  Read {len(lines_raw)} lines as plain text")
        except Exception as e2:
            raise RuntimeError(f"Could not read file: {e2}")

    # Clean artifacts
    cleaned = []
    for line in lines_raw:
        if re.match(r'^\s*23/06/2024', line):
            continue
        if re.match(r'^\s*file:///', line):
            continue
        if re.match(r'^\s*\d+/\d+\s*$', line):
            continue
        cleaned.append(line.replace('\f', ''))

    return cleaned


# ============== Step 2: Find Section Boundaries ==============

def find_sections(lines: List[str]) -> Dict[str, int]:
    """Find line numbers of key sections (uses LAST occurrence, not TOC)."""
    rc_q_start = rc_ak_start = rc_exp_start = None
    cr_q_start = cr_ak_start = cr_exp_start = None

    for i, line in enumerate(lines):
        s = line.strip()
        # RC sections
        if '4.4 Practice Questions: Reading Comprehension' in s:
            rc_q_start = i
        if '4.5 Answer Key: Reading Comprehension' in s:
            rc_ak_start = i
        if '4.6 Answer Explanations: Reading Comprehension' in s:
            rc_exp_start = i
        # CR sections
        if '4.7 Practice Questions: Critical Reasoning' in s:
            cr_q_start = i
        if '4.8 Answer Key: Critical Reasoning' in s:
            cr_ak_start = i
        if '4.9 Answer Explanations: Critical Reasoning' in s:
            cr_exp_start = i

    # Find CR exp_end: first '5.0' or 'Appendix' AFTER cr_exp_start
    cr_exp_end = len(lines)
    if cr_exp_start is not None:
        for i in range(cr_exp_start + 1, len(lines)):
            s = lines[i].strip()
            if s.startswith('5.0 GMAT') or s.startswith('Appendix'):
                cr_exp_end = i
                break

    return {
        # RC
        'rc_q_start': rc_q_start,
        'rc_ak_start': rc_ak_start,
        'rc_exp_start': rc_exp_start,
        # CR  
        'q_start': cr_q_start,  # backward compat
        'ak_start': cr_ak_start,
        'exp_start': cr_exp_start,
        'exp_end': cr_exp_end,
    }


# ============== Step 3: Parse Answer Key ==============

def parse_answer_key(lines: List[str], start: int, end: int) -> Dict[int, str]:
    answers = {}
    for line in lines[start:end]:
        m = re.match(r'^\s*(\d+)\.\s+([A-E])\s*$', line.strip())
        if m:
            answers[int(m.group(1))] = m.group(2)
    return answers


# ============== Step 4a: Parse RC Questions ==============

RC_SKILL_TAG_PATTERNS = [
    (r"primary purpose|main idea|main point|primarily concerned|primarily about", ["Main Idea"]),
    (r"according to the (passage|author)|stated in the passage|passage (states|mentions|indicates)", ["Detail"]),
    (r"can be inferred|suggests|implies|would.*agree|most likely", ["Inference"]),
    (r"in order to|function|role|serves.*to|purpose of.*mention", ["Function"]),
    (r"strengthen|weaken|support|undermine", ["Strengthen/Weaken"]),
    (r"tone|attitude", ["Tone"]),
    (r"structure|organization|organized", ["Structure"]),
    (r"EXCEPT|NOT|LEAST", ["EXCEPT"]),
]


def infer_rc_skill_tags(stem: str) -> List[str]:
    """Infer RC skill tags from question stem."""
    stem_lower = stem.lower()
    for pattern, tags in RC_SKILL_TAG_PATTERNS:
        if re.search(pattern, stem_lower):
            return tags
    return ["RC-General"]


def parse_rc_questions(lines: List[str], start: int, end: int) -> Dict[int, Dict]:
    """Parse RC section: extract passages and their associated questions."""
    section_text = '\n'.join(lines[start:end])
    
    # Clean line number markers like (5), (10), (15)
    section_text = re.sub(r'\n\(\d+\)\s*\n', '\n', section_text)
    section_text = re.sub(r'^\(\d+\)\s*', '', section_text, flags=re.MULTILINE)
    
    # Find all "Questions X-Y refer to the passage" markers
    ref_pattern = r'Questions\s+(\d+)[–\-](\d+)\s+refer to the passage'
    ref_matches = list(re.finditer(ref_pattern, section_text))
    
    if not ref_matches:
        print("  ⚠ No RC question-passage references found")
        return {}
    
    questions = {}
    
    for ref_idx, ref_match in enumerate(ref_matches):
        q_start_num = int(ref_match.group(1))
        q_end_num = int(ref_match.group(2))
        
        # The passage is the text BEFORE this reference marker
        # Find the start of this passage block
        if ref_idx == 0:
            # First passage starts after the section header + difficulty line
            passage_block_start = 0
        else:
            # Passage starts after the last question of the previous group
            passage_block_start = _find_last_option_end(section_text, ref_matches[ref_idx - 1])
        
        passage_text_raw = section_text[passage_block_start:ref_match.start()]
        
        # Clean the passage: remove difficulty headers, page refs, etc.
        passage_text = _clean_passage(passage_text_raw)
        
        # Questions come after the reference marker until the next passage
        if ref_idx < len(ref_matches) - 1:
            questions_block_end = ref_matches[ref_idx + 1].start()
            # Actually, questions end before the next passage starts
            # The next passage starts somewhere between this Q block end and next ref
        else:
            questions_block_end = len(section_text)
        
        questions_block = section_text[ref_match.end():questions_block_end]
        
        # Parse individual questions from this block
        q_blocks = re.split(r'\n(?=\d{1,3}\.\s)', questions_block)
        
        for q_block in q_blocks:
            q_block = q_block.strip()
            if not q_block:
                continue
            num_match = re.match(r'^(\d{1,3})\.\s', q_block)
            if not num_match:
                continue
            q_num = int(num_match.group(1))
            if q_num < q_start_num or q_num > q_end_num:
                continue
            
            parsed = _parse_rc_question(q_block, q_num, passage_text)
            if parsed:
                questions[q_num] = parsed
    
    return questions


def _find_last_option_end(text: str, prev_ref_match) -> int:
    """Find where the last question's options end after a reference match."""
    # Search for the pattern of the last option E. followed by passage-like text
    search_start = prev_ref_match.end()
    # Find last "E." option in this question group then some content after it
    e_matches = list(re.finditer(r'\nE\.\s', text[search_start:search_start + 5000]))
    if e_matches:
        last_e = e_matches[-1]
        # Find end of this option (next blank line or next numbered item)
        after_e = search_start + last_e.end()
        next_break = re.search(r'\n\s*\n', text[after_e:after_e + 500])
        if next_break:
            return after_e + next_break.end()
    return search_start + 2000  # fallback


def _clean_passage(raw: str) -> str:
    """Clean passage text: remove headers, artifacts, line numbers."""
    lines = raw.split('\n')
    cleaned = []
    for line in lines:
        s = line.strip()
        # Skip difficulty headers
        if re.match(r'Questions \d+ to \d+ .* Difficulty', s):
            continue
        # Skip empty or very short lines
        if not s:
            continue
        # Skip page markers
        if re.match(r'^\d+/\d+$', s):
            continue
        # Skip line number markers left over
        if re.match(r'^\(\d+\)$', s):
            continue
        cleaned.append(s)
    
    text = ' '.join(cleaned)
    # Clean up whitespace
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _parse_rc_question(block: str, q_num: int, passage: str) -> Optional[Dict]:
    """Parse a single RC question."""
    text = re.sub(r'^\d{1,3}\.\s*', '', block)
    option_matches = list(re.finditer(r'\n\s*([A-E])\.\s', text))
    
    if len(option_matches) < 5:
        # Try inline options (sometimes no newline before A.)
        option_matches = list(re.finditer(r'(?:^|\n)\s*([A-E])\.\s', text))
    
    if len(option_matches) < 5:
        print(f"  ⚠ RC Q{q_num}: only {len(option_matches)} options found, skipping")
        return None
    
    # Question stem is text before options
    stem = text[:option_matches[0].start()].strip()
    stem = re.sub(r'\s+', ' ', stem).strip()
    
    options = []
    for i in range(5):
        opt_start = option_matches[i].end()
        opt_end = option_matches[i + 1].start() if i < 4 else len(text)
        opt_text = text[opt_start:opt_end].strip()
        opt_text = re.sub(r'\s+', ' ', opt_text).strip().rstrip('.')
        options.append(opt_text)
    
    # For RC, content includes the passage + question stem
    content = f"{passage}\n\n{stem}"
    
    return {
        'passage': passage,
        'question_stem': stem,
        'content': content,
        'options': options,
    }


# ============== Step 4b: Parse CR Questions ==============

def parse_questions(lines: List[str], start: int, end: int) -> Dict[int, Dict]:
    section_text = '\n'.join(lines[start:end])
    blocks = re.split(r'\n(?=\d{2,3}\.\s)', section_text)

    questions = {}
    for block in blocks:
        block = block.strip()
        if not block:
            continue
        num_match = re.match(r'^(\d{2,3})\.\s', block)
        if not num_match:
            continue
        q_num = int(num_match.group(1))
        if q_num < CR_QUESTION_START or q_num > CR_QUESTION_END:
            continue
        parsed = _parse_one_question(block, q_num)
        if parsed:
            questions[q_num] = parsed

    return questions


def _parse_one_question(block: str, q_num: int) -> Optional[Dict]:
    text = re.sub(r'^\d{2,3}\.\s*', '', block)
    option_matches = list(re.finditer(r'\n\s*([A-E])\.\s', text))

    if len(option_matches) < 5:
        print(f"  ⚠ Q{q_num}: only {len(option_matches)} options found, skipping")
        return None

    pre_options = text[:option_matches[0].start()].strip()
    stimulus, stem = _split_stimulus_stem(pre_options)

    options = []
    for i in range(5):
        opt_start = option_matches[i].end()
        opt_end = option_matches[i + 1].start() if i < 4 else len(text)
        opt_text = text[opt_start:opt_end].strip()
        opt_text = re.sub(r'\s+', ' ', opt_text).strip().rstrip('.')
        options.append(opt_text)

    stimulus = re.sub(r'\s+', ' ', stimulus).strip()
    stem = re.sub(r'\s+', ' ', stem).strip()

    # Build content: avoid duplication
    if stem and stem != stimulus:
        content = f"{stimulus}\n\n{stem}"
    else:
        content = stimulus

    return {
        'stimulus': stimulus,
        'question_stem': stem or stimulus,
        'content': content,
        'options': options,
    }


def _split_stimulus_stem(text: str) -> Tuple[str, str]:
    stem_starters = [
        r'Which of the following',
        r'The answer to which of the following',
        r'If the statements? above',
        r'From the passage above',
        r'Each of the following',
        r'The argument (above )?(is most vulnerable|most closely)',
        r'The two (portions|boldface|highlighted)',
        r'In the argument above',
        r'The information above',
        r'The reasoning in the argument',
        r'The pattern of reasoning',
        r'How would the above',
        r'What is the main point',
        r'The (explanation|argument|plan|council|author|passage|response|point|method)',
        r'(His|Her|Its|Harry\'s) method of',
        r'A serious flaw in the reasoning',
        r'Of the following, the best',
        r'In determining the impact',
        r'The statements above most strongly suggest',
    ]
    pattern = '|'.join(f'({s})' for s in stem_starters)
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return text[:match.start()].strip(), text[match.start():].strip()

    # Try splitting at question mark
    q_mark = text.rfind('?')
    if q_mark > 0:
        sent_start = max(text.rfind('.', 0, q_mark), text.rfind('\n', 0, q_mark))
        if sent_start > 0:
            return text[:sent_start + 1].strip(), text[sent_start + 1:].strip()

    # Last resort: split at the last sentence boundary
    # Find the last period that's followed by a capital letter (sentence boundary)
    last_split = -1
    for m in re.finditer(r'\.\s+[A-Z]', text):
        last_split = m.start()
    if last_split > len(text) * 0.3:  # Only split if it's past 30% of text
        return text[:last_split + 1].strip(), text[last_split + 2:].strip()

    # True fallback: return the whole text as stimulus, empty stem
    return text, ""


# ============== Step 5: Parse Explanations ==============

def parse_explanations(lines: List[str], start: int, end: int, q_range: Tuple[int, int] = None) -> Dict[int, Dict]:
    """Parse explanations section. q_range is (start_num, end_num) inclusive."""
    if q_range is None:
        q_range = (CR_QUESTION_START, CR_QUESTION_END)
    
    section_text = '\n'.join(lines[start:end])
    blocks = re.split(r'\n(?=\d{1,3}\.\s)', section_text)

    explanations = {}
    for block in blocks:
        block = block.strip()
        num_match = re.match(r'^(\d{1,3})\.\s', block)
        if not num_match:
            continue
        q_num = int(num_match.group(1))
        if q_num < q_range[0] or q_num > q_range[1]:
            continue

        og_type = "Unknown"
        for type_name in ["Evaluation of a Plan", "Argument Evaluation", "Argument Construction"]:
            if type_name in block:
                og_type = type_name
                break

        parts = []
        sit = re.search(r'Situation\s+(.*?)(?=Reasoning|\n[A-E]\.)', block, re.DOTALL)
        if sit:
            parts.append("Situation: " + re.sub(r'\s+', ' ', sit.group(1)).strip())
        reas = re.search(r'Reasoning\s+(.*?)(?=\n[A-E]\.)', block, re.DOTALL)
        if reas:
            parts.append("Reasoning: " + re.sub(r'\s+', ' ', reas.group(1)).strip())
        correct_match = re.search(r'The correct answer is ([A-E])\.', block)
        if correct_match:
            letter = correct_match.group(1)
            corr_exp = re.search(
                rf'{letter}\.\s+Correct\.\s*(.*?)(?=\n[A-E]\.\s|The correct answer)',
                block, re.DOTALL
            )
            if corr_exp:
                parts.append(f"Why {letter} is correct: " + re.sub(r'\s+', ' ', corr_exp.group(1)).strip())

        explanation = '\n\n'.join(parts) if parts else f"OG Type: {og_type}"
        explanations[q_num] = {'og_question_type': og_type, 'explanation': explanation}

    return explanations


# ============== Step 6: Skill Tags & Difficulty ==============

def infer_skill_tags(stem: str, og_type: str) -> List[str]:
    stem_lower = stem.lower()
    for pattern, tags in SKILL_TAG_PATTERNS:
        if re.search(pattern, stem_lower):
            return tags
    fallback = {
        "Evaluation of a Plan": ["Evaluate"],
        "Argument Evaluation": ["Evaluate"],
        "Argument Construction": ["Strengthen"],
    }
    return fallback.get(og_type, ["CR-General"])


def get_difficulty(q_num: int) -> Tuple[str, int]:
    for lo, hi, label, value in DIFFICULTY_RANGES:
        if lo <= q_num <= hi:
            return label, value
    return "Medium", 3


# ============== Main Pipeline ==============

def extract_all_questions(pdf_path: str) -> List[Dict]:
    """Extract both RC and CR questions from the OG Verbal Review."""
    print("=== GMAT OG Verbal Question Extractor ===\n")

    print("Step 1: Extracting text from PDF...")
    lines = extract_and_clean(pdf_path)
    print(f"  {len(lines)} lines after cleaning")

    print("Step 2: Finding section boundaries...")
    sections = find_sections(lines)
    for k, v in sections.items():
        print(f"  {k}: line {v}")

    all_questions = []

    # ---- RC ----
    if sections['rc_q_start'] is not None and sections['rc_ak_start'] is not None:
        print("\n--- Reading Comprehension ---")
        
        print("Step 3a: Parsing RC answer key...")
        rc_answer_key = parse_answer_key(lines, sections['rc_ak_start'], sections['rc_exp_start'])
        rc_answers = {k: v for k, v in rc_answer_key.items() if RC_QUESTION_START <= k <= RC_QUESTION_END}
        print(f"  Found {len(rc_answers)} RC answers")

        print("Step 4a: Parsing RC questions...")
        rc_questions = parse_rc_questions(lines, sections['rc_q_start'], sections['rc_ak_start'])
        print(f"  Parsed {len(rc_questions)} RC questions")

        print("Step 5a: Parsing RC explanations...")
        rc_explanations = parse_explanations(
            lines, sections['rc_exp_start'], sections['q_start'],
            q_range=(RC_QUESTION_START, RC_QUESTION_END)
        )
        print(f"  Parsed {len(rc_explanations)} RC explanations")

        print("Step 6a: Assembling RC...")
        rc_missing = []
        for q_num in range(RC_QUESTION_START, RC_QUESTION_END + 1):
            if q_num not in rc_questions:
                rc_missing.append(q_num)
                continue

            q = rc_questions[q_num]
            correct_letter = rc_answers.get(q_num, 'A')
            correct_index = ord(correct_letter) - ord('A')
            exp = rc_explanations.get(q_num, {})
            explanation = exp.get('explanation', '')
            diff_label, diff_value = get_difficulty(q_num)
            skill_tags = infer_rc_skill_tags(q['question_stem'])

            all_questions.append({
                'og_number': q_num,
                'category': 'Verbal',
                'subcategory': 'RC',
                'content': q['content'],
                'stimulus': q.get('passage', ''),
                'question_stem': q['question_stem'],
                'options': q['options'],
                'correct_answer': correct_index,
                'correct_answer_letter': correct_letter,
                'skill_tags': skill_tags,
                'og_question_type': 'Reading Comprehension',
                'difficulty_label': diff_label,
                'difficulty': diff_value,
                'explanation': explanation,
            })

        if rc_missing:
            print(f"  ⚠ Could not parse {len(rc_missing)} RC questions: {rc_missing[:20]}{'...' if len(rc_missing) > 20 else ''}")
        print(f"  ✅ Assembled {len([q for q in all_questions if q['subcategory'] == 'RC'])} RC questions")
    else:
        print("\n⚠ RC sections not found, skipping RC extraction")

    # ---- CR ----
    if sections['q_start'] is not None and sections['ak_start'] is not None:
        print("\n--- Critical Reasoning ---")
        
        print("Step 3b: Parsing CR answer key...")
        cr_answer_key = parse_answer_key(lines, sections['ak_start'], sections['exp_start'])
        cr_answers = {k: v for k, v in cr_answer_key.items() if CR_QUESTION_START <= k <= CR_QUESTION_END}
        print(f"  Found {len(cr_answers)} CR answers")

        print("Step 4b: Parsing CR questions...")
        cr_questions = parse_questions(lines, sections['q_start'], sections['ak_start'])
        print(f"  Parsed {len(cr_questions)} CR questions")

        print("Step 5b: Parsing CR explanations...")
        cr_explanations = parse_explanations(
            lines, sections['exp_start'], sections['exp_end'],
            q_range=(CR_QUESTION_START, CR_QUESTION_END)
        )
        print(f"  Parsed {len(cr_explanations)} CR explanations")

        print("Step 6b: Assembling CR...")
        cr_missing = []
        for q_num in range(CR_QUESTION_START, CR_QUESTION_END + 1):
            if q_num not in cr_questions:
                cr_missing.append(q_num)
                continue

            q = cr_questions[q_num]
            correct_letter = cr_answers.get(q_num, 'A')
            correct_index = ord(correct_letter) - ord('A')
            exp = cr_explanations.get(q_num, {})
            og_type = exp.get('og_question_type', 'Unknown')
            explanation = exp.get('explanation', '')
            diff_label, diff_value = get_difficulty(q_num)
            skill_tags = infer_skill_tags(q['question_stem'], og_type)

            all_questions.append({
                'og_number': q_num,
                'category': 'Verbal',
                'subcategory': 'CR',
                'content': q['content'],
                'stimulus': q['stimulus'],
                'question_stem': q['question_stem'],
                'options': q['options'],
                'correct_answer': correct_index,
                'correct_answer_letter': correct_letter,
                'skill_tags': skill_tags,
                'og_question_type': og_type,
                'difficulty_label': diff_label,
                'difficulty': diff_value,
                'explanation': explanation,
            })

        if cr_missing:
            print(f"  ⚠ Could not parse {len(cr_missing)} CR questions: {cr_missing[:15]}{'...' if len(cr_missing) > 15 else ''}")
        print(f"  ✅ Assembled {len([q for q in all_questions if q['subcategory'] == 'CR'])} CR questions")
    else:
        print("\n⚠ CR sections not found, skipping CR extraction")

    # Sort by og_number
    all_questions.sort(key=lambda q: q['og_number'])
    
    rc_count = sum(1 for q in all_questions if q['subcategory'] == 'RC')
    cr_count = sum(1 for q in all_questions if q['subcategory'] == 'CR')
    print(f"\n✅ Total extracted: {len(all_questions)} questions (RC: {rc_count}, CR: {cr_count})")
    return all_questions


# Keep old function for backward compatibility
def extract_cr_questions(pdf_path: str) -> List[Dict]:
    """Extract only CR questions (backward compatible)."""
    all_q = extract_all_questions(pdf_path)
    return [q for q in all_q if q['subcategory'] == 'CR']


# ============== Export ==============

def export_json(questions: List[Dict], path: str = "og_questions.json"):
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(questions, f, ensure_ascii=False, indent=2)
    print(f"✅ Exported to {path}")


def export_csv(questions: List[Dict], path: str = "og_questions.csv"):
    import csv
    with open(path, 'w', newline='', encoding='utf-8') as f:
        w = csv.writer(f)
        w.writerow(['og_number', 'difficulty', 'skill_tags', 'answer',
                     'question_stem', 'opt_A', 'opt_B', 'opt_C', 'opt_D', 'opt_E'])
        for q in questions:
            w.writerow([
                q['og_number'], q['difficulty_label'],
                ', '.join(q['skill_tags']), q['correct_answer_letter'],
                q['question_stem'][:120],
                q['options'][0][:80], q['options'][1][:80],
                q['options'][2][:80], q['options'][3][:80], q['options'][4][:80],
            ])
    print(f"✅ Exported to {path}")


def import_to_database(questions: List[Dict]):
    from database import get_db, Question
    db = get_db()
    count = 0
    for q in questions:
        db.add_question(Question(
            id=None, passage_id=None,
            category=q['category'], subcategory=q['subcategory'],
            content=q['content'], options=q['options'],
            correct_answer=q['correct_answer'],
            skill_tags=q['skill_tags'], difficulty=q['difficulty'],
            explanation=q['explanation'],
        ))
        count += 1
    print(f"✅ Imported {count} questions into database")


# ============== Report ==============

def print_report(questions: List[Dict]):
    print("\n" + "=" * 50)
    print("EXTRACTION REPORT")
    print("=" * 50)

    print("\nBy Question Type:")
    for sub in ["RC", "CR"]:
        n = sum(1 for q in questions if q['subcategory'] == sub)
        if n > 0:
            print(f"  {sub}: {n}")

    print("\nBy Difficulty:")
    for label in ["Easy", "Medium", "Hard"]:
        n = sum(1 for q in questions if q['difficulty_label'] == label)
        print(f"  {label}: {n}")

    print("\nBy Skill Tag:")
    tags = {}
    for q in questions:
        for t in q['skill_tags']:
            tags[t] = tags.get(t, 0) + 1
    for t, n in sorted(tags.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")

    print("\nBy OG Question Type:")
    types = {}
    for q in questions:
        t = q['og_question_type']
        types[t] = types.get(t, 0) + 1
    for t, n in sorted(types.items(), key=lambda x: -x[1]):
        print(f"  {t}: {n}")

    if questions:
        s = questions[0]
        print(f"\nSample (Q{s['og_number']}):")
        print(f"  Tags: {s['skill_tags']}")
        print(f"  Stem: {s['question_stem'][:100]}...")
        print(f"  Answer: {s['correct_answer_letter']}")

    print("=" * 50)


# ============== Main ==============

def main():
    if len(sys.argv) < 2:
        print("Usage: python extract_og.py <pdf_path> [--import] [--csv] [--cr-only]")
        print()
        print("Examples:")
        print('  python extract_og.py "GMAT_OG_Verbal_Review.pdf"')
        print('  python extract_og.py "GMAT_OG_Verbal_Review.pdf" --import --csv')
        print('  python extract_og.py "GMAT_OG_Verbal_Review.pdf" --cr-only')
        sys.exit(1)

    pdf_path = sys.argv[1]
    
    if '--cr-only' in sys.argv:
        questions = extract_cr_questions(pdf_path)
    else:
        questions = extract_all_questions(pdf_path)

    if not questions:
        print("No questions extracted.")
        sys.exit(1)

    print_report(questions)
    export_json(questions)

    if '--csv' in sys.argv:
        export_csv(questions)
    if '--import' in sys.argv:
        import_to_database(questions)

    print("\nDone!")


if __name__ == "__main__":
    main()
