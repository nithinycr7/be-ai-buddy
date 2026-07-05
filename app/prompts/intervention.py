"""Adaptive-intervention prompt: tier briefs + the micro-intervention builder."""
from __future__ import annotations

from typing import Any, Dict, List


TIER_BRIEF = {
    "prerequisite_gap": (
        "The student mostly understands the topic but a PREREQUISITE skill is "
        "tripping them up (e.g. fractions causing algebra mistakes). Identify "
        "that single prerequisite and write a short RECALL refresher for it."
    ),
    "core_gap": (
        "The student does NOT yet understand the core concept of this topic. "
        "Re-explain the core idea from the ground up in the SIMPLEST possible "
        "terms, then show one fully worked example."
    ),
}


def build_intervention_prompt(wrong_questions: List[Dict[str, Any]], topic: str,
                  subject: str, class_no: int, tier: str) -> str:
    lines = []
    for i, q in enumerate(wrong_questions, 1):
        lines.append(
            f"{i}. Q: {q.get('question','')}\n"
            f"   Student answered: {q.get('student_answer','(blank)')}\n"
            f"   Correct answer: {q.get('correct','')}"
        )
    wrong_block = "\n".join(lines) if lines else "(no per-question detail available)"

    return f"""You are a master grade-{class_no} {subject} tutor running a 2-3 minute
micro-intervention for ONE student on the topic: "{topic}".

{TIER_BRIEF.get(tier, TIER_BRIEF['core_gap'])}

Here are the questions this student got WRONG and what they answered:
{wrong_block}

From these mistakes, infer the SINGLE root gap (one concept only — never a list).

Then produce:
1. gap_concept: the one root concept the student is missing (3-6 words).
2. intervention_type: a short human label for the teacher dashboard
   (e.g. "Fraction Recall", "Concept Review").
3. explanation: a <=120-word, warm, plain-language refresher of that concept.
   No jargon. Speak directly to the student.
4. worked_example: ONE fully worked example showing the concept step by step.
5. verification_questions: EXACTLY 3 questions that test the SAME concept but
   with DIFFERENT numbers/values than the questions above (measure
   understanding, not memorised answers). Keep them easy-to-medium. Use a mix:
   at least 2 MCQ and at most 1 SOLVE/FILL_BLANK.

Return STRICT JSON only:
{{
  "gap_concept": "...",
  "intervention_type": "...",
  "explanation": "...",
  "worked_example": "...",
  "verification_questions": [
    {{
      "question": "...",
      "question_type": "MCQ" | "FILL_BLANK" | "SOLVE",
      "difficulty": "easy" | "medium",
      "options": [{{"key": "a", "description": "..."}}],  // [] for non-MCQ
      "correct": ["a"]  // option key(s) for MCQ, or answer text for FILL_BLANK/SOLVE
      ,"explanation": "why this is correct"
    }}
  ]
}}"""
