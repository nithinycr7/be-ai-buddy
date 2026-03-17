CONCEPT_EXTRACTION_PROMPT = """You are a curriculum assistant for Indian school students (CBSE/ICSE, grades 3-9).

Given a student's question or search query, extract the primary educational concept they are asking about.

Return a JSON object with ONLY these fields:
{{
  "concept_name": "exact concept name as it appears in textbooks",
  "subject": "Physics | Chemistry | Math | Biology | History | Geography | Civics",
  "estimated_grade": <integer 3-9>,
  "curriculum": "CBSE | ICSE | GENERAL",
  "confidence": <float 0.0-1.0>
}}

Rules:
- concept_name must be specific (e.g., "Newton's Second Law" not just "Newton")
- If the query is ambiguous, pick the most common school-level interpretation
- If no clear concept found, return confidence below 0.4

Student query: {query}"""


CONCEPT_CLASSIFICATION_PROMPT = """You are a curriculum expert for Indian school education (CBSE/ICSE, grades 3-9).

Classify the given concept into exactly ONE type:
- concept: An abstract idea or principle (e.g., Inertia, Democracy, Photosynthesis concept)
- equation: A mathematical or scientific formula (e.g., F=ma, Area of Circle, E=mc²)
- relationship: How two or more things interact (e.g., Action-Reaction, Supply-Demand)
- process: A sequence of steps or events (e.g., Water Cycle, Digestion, Cell Division)
- memory: Facts, dates, lists that require memorization (e.g., Capitals, Periodic Table symbols)

Also select the best learning_mode:
- diagram: for concepts and relationships (visual node-edge representation)
- equation_visualization: for formulas with interactive variables
- process_flow: for sequential processes
- mindmap: for broad concepts with many sub-parts
- step_by_step: for solving procedures
- mnemonic: for memory/recall tasks

Return ONLY this JSON (no other text):
{{
  "concept_type": "<concept|equation|relationship|process|memory>",
  "learning_mode": "<diagram|equation_visualization|process_flow|mindmap|step_by_step|mnemonic>",
  "reasoning": "<one sentence>"
}}

Concept: {concept_name}
Subject: {subject}
Grade: {grade}"""


EXPLANATION_GENERATION_PROMPT = """You are an expert teacher creating visual, interactive learning content for Indian school students.

Student Profile:
- Grade: {grade}
- Curriculum: {curriculum}
- Subject: {subject}

Concept: {concept_name}
Concept Type: {concept_type}
Learning Mode: {learning_mode}

Create a structured explanation that a React frontend can render as an interactive visual.

STRICT RULES:
1. Language must be simple and age-appropriate for grade {grade} students
2. NO long paragraphs — short punchy sentences only
3. Always include a real-life analogy a {grade}th grader would relate to
4. Return ONLY valid JSON — no markdown, no code blocks, no extra text

{mode_specific_instructions}

Return EXACTLY this JSON structure (fill every field):
{{
  "concept": "{concept_name}",
  "grade": {grade},
  "curriculum": "{curriculum}",
  "type": "{concept_type}",
  "learning_mode": "{learning_mode}",
  "explanation": "<1-2 sentence plain English explanation>",
  "analogy": "<vivid real-life analogy a student would love>",
  "visual_data": {visual_data_schema},
  "fun_fact": "<one surprising fact about this concept>",
  "common_mistake": "<one thing students always get wrong>",
  "related_concepts": ["<concept1>", "<concept2>", "<concept3>"],
  "quick_check": {{
    "question": "<single MCQ question testing this concept>",
    "options": ["A. <option>", "B. <option>", "C. <option>", "D. <option>"],
    "answer": "<A or B or C or D>",
    "hint": "<one-line hint>"
  }}
}}"""


MODE_INSTRUCTIONS = {
    "diagram": """For learning_mode=diagram, visual_data must be:
{
  "nodes": [
    {"id": "n1", "label": "...", "color": "#hex", "size": "large|medium|small", "icon": "emoji", "description": "..."}
  ],
  "edges": [
    {"from": "n1", "to": "n2", "label": "...", "style": "solid|dashed|arrow"}
  ],
  "layout": "radial|tree|force",
  "highlight_node": "id of the main concept node"
}
Make 4-7 nodes. Use bright hex colors. The main concept should be the center node.""",

    "equation_visualization": """For learning_mode=equation_visualization, visual_data must be:
{
  "formula": "F = m × a",
  "formula_latex": "F = m \\\\times a",
  "variables": [
    {"symbol": "F", "name": "Force", "unit": "Newton (N)", "color": "#FF6B6B", "description": "..."},
    {"symbol": "m", "name": "Mass", "unit": "kg", "color": "#4ECDC4", "description": "..."},
    {"symbol": "a", "name": "Acceleration", "unit": "m/s²", "color": "#45B7D1", "description": "..."}
  ],
  "interactive_example": {
    "default_values": {"m": 10, "a": 5},
    "solve_for": "F",
    "result": 50,
    "unit": "N",
    "slider_ranges": {"m": [1, 100], "a": [1, 50]}
  },
  "worked_example": {
    "problem": "A real-life problem statement.",
    "steps": ["Step 1: ...", "Step 2: ...", "Step 3: ..."],
    "answer": "..."
  }
}""",

    "process_flow": """For learning_mode=process_flow, visual_data must be:
{
  "steps": [
    {"id": 1, "title": "...", "description": "...", "icon": "emoji", "color": "#hex"}
  ],
  "flow_type": "linear|cyclic|branching",
  "connections": [
    {"from": 1, "to": 2, "label": "then"}
  ],
  "loop_back_to": null
}
Use 4-7 steps. Use bright, distinct colors per step. cyclic if it repeats (like water cycle).""",

    "mindmap": """For learning_mode=mindmap, visual_data must be:
{
  "center": {"label": "...", "color": "#hex", "icon": "emoji"},
  "branches": [
    {
      "id": "b1",
      "label": "...",
      "color": "#hex",
      "icon": "emoji",
      "children": [
        {"label": "...", "note": "short note"}
      ]
    }
  ]
}
Include 4-6 branches, each with 2-3 children.""",

    "step_by_step": """For learning_mode=step_by_step, visual_data must be:
{
  "problem_type": "...",
  "steps": [
    {
      "step_number": 1,
      "title": "...",
      "instruction": "...",
      "formula_used": "optional formula",
      "calculation": "optional",
      "result": "optional",
      "tip": "optional tip"
    }
  ],
  "final_answer": "...",
  "check_method": "how to verify the answer"
}""",

    "mnemonic": """For learning_mode=mnemonic, visual_data must be:
{
  "mnemonic_type": "acronym|rhyme|story|visual_peg",
  "mnemonic_text": "...",
  "breakdown": [
    {"letter_or_part": "P", "stands_for": "Planets", "visual": "emoji"}
  ],
  "practice_phrase": "...",
  "memory_palace": "optional vivid scene to imagine"
}""",
}


VISUAL_SCHEMA_PLACEHOLDER = {
    "diagram":                '{"nodes": [...], "edges": [...], "layout": "radial", "highlight_node": "n1"}',
    "equation_visualization": '{"formula": "...", "variables": [...], "interactive_example": {...}, "worked_example": {...}}',
    "process_flow":           '{"steps": [...], "flow_type": "linear", "connections": [...], "loop_back_to": null}',
    "mindmap":                '{"center": {...}, "branches": [...]}',
    "step_by_step":           '{"problem_type": "...", "steps": [...], "final_answer": "...", "check_method": "..."}',
    "mnemonic":               '{"mnemonic_type": "acronym", "mnemonic_text": "...", "breakdown": [...], "practice_phrase": "..."}',
}
