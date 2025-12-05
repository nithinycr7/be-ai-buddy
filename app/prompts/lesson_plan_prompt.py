import json

def lesson_plan_prompt(class_no, subject, chapter):
    return f"""
You are an expert NCERT teacher with strong lesson design experience.

Create a clear and classroom-ready lesson plan for:

Class: {class_no}
Subject: {subject}
Chapter: {chapter}

Follow the schema STRICTLY:

{{
  "learning_outcomes": {{
    "items": ["string", "string"],
    "time": number
  }},
  "core_instruction": {{
    "text": "string",
    "time": number
  }},
  "practice_activity": {{
    "text": "string",
    "time": number
  }},
  "assessment": {{
    "text": "string",
    "time": number
  }}
}}

CONTENT QUALITY RULES:
- Learning outcomes MUST follow Bloom’s verbs (e.g., identify, explain, apply, analyze).
- Core instruction MUST be 4–6 sentences OR 60–120 words. It should include examples relevant to real life or student experience.
- Practice activity MUST be actionable and written as step-by-step instructions (minimum 3 steps).
- Assessment MUST include one question students can respond to verbally or in writing.
- Time values must feel realistic for a 30–50 minute lesson.

STRICT OUTPUT RULES:
- DO NOT add extra fields.
- DO NOT return markdown, bullets, or commentary outside the JSON.
- MUST produce machine-parseable JSON only.
"""




def build_edit_prompt(sections_context, instruction):
    return f"""
You are an expert lesson plan editor.

Your task: Update ONLY the given sections based on the teacher's instruction.

CURRENT SECTIONS (JSON):
{json.dumps(sections_context, indent=2)}

TEACHER INSTRUCTION:
"{instruction}"

RESPONSE REQUIREMENTS:
- Return ONLY the updated sections.
- Follow the same schema and key names.
- Do NOT remove or rename any field.
- Keep "time" as a number.
- Keep content clear, actionable, and 2–5 sentences long.
- Practice activity must be stepwise if applicable.

STRICT OUTPUT FORMAT:
Return ONLY valid JSON. No markdown. No comments.
"""
