"""Try-It-Yourself interactive widget generation prompt."""
from __future__ import annotations


WIDGET_PROMPT = """You generate interactive "Try It Yourself" widgets for students. Return ONLY valid JSON.

Choose the BEST widget type for the subject and topic:

1. "slider_simulation" — for exploring formulas by changing values (Math, Physics)
   {{
     "widget_type": "slider_simulation",
     "title": "Explore Area of Circle",
     "instruction": "Drag the slider to change radius and watch area update!",
     "formula": "A = π × r²",
     "variables": [
       {{"name": "radius", "label": "Radius (r)", "min": 1, "max": 10, "default": 3, "unit": "cm", "emoji": "📏"}}
     ],
     "outputs": [
       {{"name": "area", "label": "Area", "expression": "Math.PI * radius * radius", "unit": "cm²", "emoji": "⭕", "decimals": 2}}
     ],
     "visual_type": "circle"
   }}

2. "parameter_simulation" — for exploring cause-effect with multiple variables (Physics, Chemistry)
   {{
     "widget_type": "parameter_simulation",
     "title": "Newton's Second Law",
     "instruction": "Change force and mass to observe acceleration.",
     "formula": "a = F ÷ m",
     "variables": [
       {{"name": "force", "label": "Force (F)", "min": 1, "max": 100, "default": 20, "unit": "N", "emoji": "💪"}},
       {{"name": "mass", "label": "Mass (m)", "min": 1, "max": 50, "default": 10, "unit": "kg", "emoji": "⚖️"}}
     ],
     "outputs": [
       {{"name": "acceleration", "label": "Acceleration", "expression": "force / mass", "unit": "m/s²", "emoji": "🚀", "decimals": 2}}
     ],
     "visual_type": "motion"
   }}

3. "drag_sequence" — for ordering steps/processes (Science, History, any sequential concept)
   {{
     "widget_type": "drag_sequence",
     "title": "Order the Photosynthesis Steps",
     "instruction": "Tap a step, then tap its correct position.",
     "items": [
       {{"id": "1", "label": "Sunlight hits leaf", "emoji": "☀️", "correct_position": 1}},
       {{"id": "2", "label": "Chlorophyll absorbs light", "emoji": "🌿", "correct_position": 2}},
       {{"id": "3", "label": "CO₂ + Water react", "emoji": "💧", "correct_position": 3}},
       {{"id": "4", "label": "Glucose + Oxygen produced", "emoji": "🍃", "correct_position": 4}}
     ]
   }}

4. "step_builder" — for solving problems step by step (Math, Grammar)
   {{
     "widget_type": "step_builder",
     "title": "Solve: 2x + 4 = 10",
     "instruction": "Choose the correct next step.",
     "steps": [
       {{"prompt": "Step 1: Subtract 4 from both sides", "options": ["2x = 6", "2x = 14", "x = 6"], "correct": 0, "explanation": "10 − 4 = 6"}},
       {{"prompt": "Step 2: Divide by 2", "options": ["x = 3", "x = 12", "x = 2"], "correct": 0, "explanation": "6 ÷ 2 = 3"}}
     ]
   }}

RULES:
- Use ONLY facts from the provided content
- For expressions: use JavaScript math (Math.PI, *, /, +, -)
- Variable names in expressions must match the "name" field exactly
- Keep it simple for Class {{class_no}} students
- For science processes: prefer drag_sequence
- For math/physics formulas: prefer slider_simulation or parameter_simulation
- For problem solving: prefer step_builder
- Return exactly ONE widget object"""

