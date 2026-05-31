from __future__ import annotations
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.security import api_key_guard

router = APIRouter(prefix="/engine", tags=["engine"], dependencies=[Depends(api_key_guard)])


class ExploreConfigRequest(BaseModel):
    topic_slug: str
    grade: Optional[int] = None
    force: bool = False
    topic: Optional[str] = None
    subject: Optional[str] = None
    grades: Optional[List[int]] = None
    board: Optional[str] = None


def choose_world_type(subject: Optional[str], topic_slug: str, topic: Optional[str]) -> str:
    hints = ' '.join([subject or '', topic or '', topic_slug or '']).lower()
    if any(term in hints for term in ['python', 'code', 'programming', 'syntax', 'variable', 'loop', 'print']):
        return 'code'
    if any(term in hints for term in ['math', 'mathematics', 'fraction', 'ratio', 'percent', 'probability', 'whole']):
        return 'balance'
    if any(term in hints for term in ['physics', 'space', 'planet', 'orbit', 'solar', 'astronomy', 'gravity']):
        return 'scale'
    return 'living'


def build_code_config(topic: str, subject: str, grade: int, grades: List[int]) -> dict:
    return {
        "topic": topic,
        "subject": subject,
        "world_type": "living",
        "defaultGrade": grade,
        "grades": grades,
        "summary": "Python syntax is the language rulebook for writing code. Each line is a step, and indentation tells the computer which lines belong together.",
        "key_idea": "Think of Python as talking to a robot one instruction at a time — use words like print, if, and for to make it do work.",
        "controls": [
            {
                "id": "clarity",
                "icon": "💡",
                "default": 5,
                "min": 0,
                "max": 10,
                "affects": "energy",
                "label": {"3": "Read code", "7": "Understand logic"}
            },
            {
                "id": "practice",
                "icon": "🧠",
                "default": 5,
                "min": 0,
                "max": 10,
                "affects": "growth",
                "label": {"3": "Try examples", "7": "Run programs"}
            }
        ],
        "health_formula": "((clarity / 10) * 55) + ((practice / 10) * 45)",
        "palette": {
            "sky": "#0f172a",
            "soil": "#111827",
            "grass": "#38bdf8",
            "water": "rgba(56,189,248,0.18)",
            "energy": "#f8fafc",
            "energyGlow": "#e2e8f0",
            "energyRay": "#60a5fa",
            "plant": {
                "leaf": "#a5b4fc",
                "stem": "#60a5fa",
                "root": "#c7d2fe"
            }
        },
        "depth_layers": {
            "3": {
                "visible": ["background", "world", "ui", "story"],
                "story_tone": "emotional",
                "show_labels": False,
                "show_chemistry": False,
                "show_formula": False
            },
            "7": {
                "visible": ["background", "world", "chemistry", "labels", "ui", "story"],
                "story_tone": "scientific",
                "show_labels": True,
                "show_chemistry": True,
                "show_formula": True,
                "formula": "print('Hello, world!')"
            }
        },
        "labels": [
            {"text": "Indentation matters", "points_to": "leaves", "side": "left"},
            {"text": "Run each line", "points_to": "stem", "side": "right"},
            {"text": "If conditions", "points_to": "roots", "side": "left"}
        ],
        "story_beats": [
            {
                "id": "ready",
                "trigger": "health < 40",
                "grades": [3, 4, 5, 6, 7, 8],
                "tone": "emotional",
                "message": "💻 The code is just starting. Little changes make it run better.",
                "color": "#38bdf8"
            },
            {
                "id": "learning",
                "trigger": "health >= 40 && health <= 70",
                "grades": [3, 4, 5, 6, 7, 8],
                "tone": "informational",
                "message": "📘 Great! You are learning how lines of Python work together.",
                "color": "#8b5cf6"
            },
            {
                "id": "expert",
                "trigger": "health > 70",
                "grades": [7, 8],
                "tone": "scientific",
                "message": "🚀 Your code is smooth now. Keep practicing and try a quiz next!",
                "color": "#22c55e"
            }
        ]
    }


def build_living_config(topic: str, subject: str, grade: int, grades: List[int]) -> dict:
    return {
        "topic": topic,
        "subject": subject,
        "world_type": "living",
        "defaultGrade": grade,
        "grades": grades,
        "controls": [
            {
                "id": "sun",
                "icon": "☀️",
                "default": 5,
                "min": 0,
                "max": 10,
                "affects": "energy",
                "label": {"3": "Sunlight", "7": "Light Intensity"}
            },
            {
                "id": "water",
                "icon": "💧",
                "default": 5,
                "min": 0,
                "max": 10,
                "affects": "growth",
                "label": {"3": "Water", "7": "H₂O Input"}
            }
        ],
        "health_formula": "((sun / 10) * 55) + ((water / 10) * 45)",
        "palette": {
            "sky": "#bae6fd",
            "soil": "#7dd3fc",
            "grass": "#4ade80",
            "water": "rgba(59,130,246,0.18)",
            "energy": "#fde68a",
            "energyGlow": "#fef3c7",
            "energyRay": "#fcd34d",
            "plant": {
                "leaf": "#22c55e",
                "stem": "#166534",
                "root": "#4b5563"
            }
        },
        "depth_layers": {
            "3": {
                "visible": ["background", "world", "ui", "story"],
                "story_tone": "emotional",
                "show_labels": False,
                "show_chemistry": False,
                "show_formula": False
            },
            "7": {
                "visible": ["background", "world", "chemistry", "labels", "ui", "story"],
                "story_tone": "scientific",
                "show_labels": True,
                "show_chemistry": True,
                "show_formula": True,
                "formula": "6CO₂ + 6H₂O → C₆H₁₂O₆ + 6O₂"
            }
        },
        "labels": [
            {"text": "Light energy", "points_to": "sun", "side": "right"},
            {"text": "Chlorophyll", "points_to": "leaves", "side": "left"},
            {"text": "H₂O via roots", "points_to": "roots", "side": "left"},
            {"text": "Stomata", "points_to": "leaf_edge", "side": "right"}
        ],
        "story_beats": [
            {
                "id": "critical",
                "trigger": "health < 25",
                "grades": [3, 4, 5, 6, 7, 8],
                "tone": "emotional",
                "message": "🥀 The plant is in danger. Give it water and sunlight.",
                "color": "#dc2626"
            },
            {
                "id": "warning",
                "trigger": "health < 50 && health >= 25",
                "grades": [3, 4, 5, 6, 7, 8],
                "tone": "emotional",
                "message": "⚠️ Struggling. Try increasing sunlight or water.",
                "color": "#d97706"
            },
            {
                "id": "thriving",
                "trigger": "health > 80",
                "grades": [3, 4],
                "tone": "emotional",
                "message": "🌿 Perfect! Your plant is thriving.",
                "color": "#16a34a"
            },
            {
                "id": "co2active",
                "trigger": "health > 50",
                "grades": [7, 8],
                "tone": "scientific",
                "message": "CO₂ entering through stomata. Glucose being synthesised.",
                "color": "#185FA5"
            },
            {
                "id": "o2peak",
                "trigger": "health > 80",
                "grades": [7, 8],
                "tone": "scientific",
                "message": "Photosynthesis at peak rate. O₂ releasing as byproduct.",
                "color": "#16a34a"
            }
        ]
    }


def build_scale_config(topic: str, subject: str, grade: int, grades: List[int]) -> dict:
    return {
        "topic": topic,
        "subject": subject,
        "world_type": "scale",
        "defaultGrade": grade,
        "grades": grades,
        "controls": [
            {
                "id": "speed",
                "icon": "🚀",
                "default": 5,
                "min": 0,
                "max": 10,
                "affects": "speed",
                "label": {"3": "Orbital speed", "7": "Angular velocity"}
            },
            {
                "id": "zoom",
                "icon": "🔍",
                "default": 5,
                "min": 0,
                "max": 10,
                "affects": "zoom",
                "label": {"3": "Distance", "7": "Zoom level"}
            }
        ],
        "health_formula": "((speed / 10) * 50) + ((zoom / 10) * 50)",
        "palette": {
            "spaceTop": "#0b1224",
            "spaceMid": "#07102a",
            "spaceEnd": "#01040c",
            "star": "#a5f3fc",
            "orbit": "rgba(148, 163, 184, 0.22)",
            "labelText": "#e2e8f0",
            "scienceText": "#93c5fd"
        },
        "scaleWorld": {
            "centralBody": {
                "label": "Sun",
                "color": "#fbbf24",
                "radius": 32,
                "glow": True
            },
            "bodies": [
                {"name": "Mercury", "color": "#cbd5e1", "radius": 5, "orbitRadius": 80, "speed": 2, "grade_reveal": 3},
                {"name": "Venus",   "color": "#fbbf24", "radius": 7, "orbitRadius": 115, "speed": 1.5, "grade_reveal": 3},
                {"name": "Earth",   "color": "#38bdf8", "radius": 8, "orbitRadius": 155, "speed": 1.1, "grade_reveal": 4, "scienceLabel": "Habitable"},
                {"name": "Mars",    "color": "#f97316", "radius": 6, "orbitRadius": 190, "speed": 0.9, "grade_reveal": 5, "scienceLabel": "Red planet"}
            ]
        },
        "depth_layers": {
            "3": {
                "visible": ["background", "world", "ui", "story"],
                "story_tone": "emotional",
                "show_labels": False,
                "show_chemistry": False,
                "show_formula": False
            },
            "7": {
                "visible": ["background", "world", "labels", "ui", "story"],
                "story_tone": "scientific",
                "show_labels": True,
                "show_chemistry": False,
                "show_formula": False
            }
        },
        "labels": [
            {"text": "Orbit path", "points_to": "Mercury", "side": "left"},
            {"text": "Escape velocity", "points_to": "Sun", "side": "right"},
            {"text": "Gravity well", "points_to": "Sun", "side": "left"}
        ],
        "story_beats": [
            {
                "id": "slow",
                "trigger": "health < 40",
                "grades": [3, 4, 5, 6],
                "tone": "emotional",
                "message": "🌑 The system feels sluggish. Increase speed or zoom in to see more detail.",
                "color": "#64748b"
            },
            {
                "id": "balanced",
                "trigger": "health >= 40 && health <= 70",
                "grades": [3, 4, 5, 6, 7, 8],
                "tone": "informational",
                "message": "🪐 The planets are moving steadily in their orbits.",
                "color": "#38bdf8"
            },
            {
                "id": "fast_lane",
                "trigger": "health > 70",
                "grades": [7, 8],
                "tone": "scientific",
                "message": "🚀 The system is energetic and stable. You’ve found a good balance.",
                "color": "#fbbf24"
            }
        ]
    }


def build_balance_config(topic: str, subject: str, grade: int, grades: List[int]) -> dict:
    return {
        "topic": topic,
        "subject": subject,
        "world_type": "balance",
        "defaultGrade": grade,
        "grades": grades,
        "controls": [
            {
                "id": "fill",
                "icon": "🍕",
                "default": 5,
                "min": 0,
                "max": 10,
                "affects": "fill",
                "label": {"3": "Filled amount", "7": "Part size"}
            },
            {
                "id": "divide",
                "icon": "⚖️",
                "default": 5,
                "min": 0,
                "max": 10,
                "affects": "divide",
                "label": {"3": "Divisions", "7": "Number of parts"}
            }
        ],
        "health_formula": "((fill / 10) * 60) + ((divide / 10) * 40)",
        "palette": {
            "background": "#f8fafc",
            "accent": "#fb923c",
            "fillColor": "#f97316",
            "divideColor": "#2563eb"
        },
        "depth_layers": {
            "3": {
                "visible": ["background", "world", "ui", "story"],
                "story_tone": "emotional",
                "show_labels": False,
                "show_chemistry": False,
                "show_formula": False
            },
            "7": {
                "visible": ["background", "world", "labels", "ui", "story"],
                "story_tone": "informational",
                "show_labels": True,
                "show_chemistry": False,
                "show_formula": False
            }
        },
        "labels": [
            {"text": "Filled portion", "points_to": "fill", "side": "left"},
            {"text": "Total parts", "points_to": "divide", "side": "right"}
        ],
        "story_beats": [
            {
                "id": "small_portion",
                "trigger": "health < 40",
                "grades": [3, 4, 5],
                "tone": "emotional",
                "message": "🟠 A small part is filled. Try increasing the amount so the whole makes sense.",
                "color": "#f97316"
            },
            {
                "id": "balanced_parts",
                "trigger": "health >= 40 && health <= 70",
                "grades": [3, 4, 5, 6, 7, 8],
                "tone": "informational",
                "message": "🟡 The pieces are coming together. Focus on both amount and division.",
                "color": "#60a5fa"
            },
            {
                "id": "well_scaled",
                "trigger": "health > 70",
                "grades": [7, 8],
                "tone": "scientific",
                "message": "✅ You’ve achieved a strong ratio. That’s how even portions look.",
                "color": "#16a34a"
            }
        ]
    }


@router.post("/config")
async def get_explore_config(req: ExploreConfigRequest):
    grade = req.grade or 3
    grades = req.grades or [grade]
    topic = req.topic or "Interactive World"
    subject = req.subject or "Science"

    world_type = choose_world_type(subject, req.topic_slug, topic)
    if world_type == 'code':
        config = build_code_config(topic, subject, grade, grades)
    elif world_type == 'scale':
        config = build_scale_config(topic, subject, grade, grades)
    elif world_type == 'balance':
        config = build_balance_config(topic, subject, grade, grades)
    else:
        config = build_living_config(topic, subject, grade, grades)

    return {
        "config": config,
        "from_cache": not req.force,
        "generated_at": datetime.utcnow().isoformat() + "Z",
        "generation_ms": 16,
    }
