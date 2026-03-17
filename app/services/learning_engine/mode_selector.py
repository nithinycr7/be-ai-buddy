from __future__ import annotations
from app.models.learning_engine_schemas import ConceptType, LearningMode

# Primary and secondary modes per concept type
MODE_MAP: dict[str, list[str]] = {
    ConceptType.CONCEPT:      [LearningMode.DIAGRAM,                LearningMode.MINDMAP],
    ConceptType.EQUATION:     [LearningMode.EQUATION_VISUALIZATION, LearningMode.STEP_BY_STEP],
    ConceptType.RELATIONSHIP: [LearningMode.DIAGRAM,                LearningMode.MINDMAP],
    ConceptType.PROCESS:      [LearningMode.PROCESS_FLOW,           LearningMode.STEP_BY_STEP],
    ConceptType.MEMORY:       [LearningMode.MNEMONIC,               LearningMode.MINDMAP],
}


def select_mode(concept_type: str, grade: int, preferred: str | None = None) -> str:
    """
    Select the best learning mode.
    - Grade 3-5: avoid heavy equation_visualization, prefer step_by_step
    - Grade 6+:  full mode set available
    - preferred: student can explicitly override via UI
    """
    if preferred:
        try:
            return LearningMode(preferred)
        except ValueError:
            pass

    candidates = MODE_MAP.get(concept_type, [LearningMode.DIAGRAM])

    # Downgrade equation_visualization for younger students
    if grade <= 5 and LearningMode.EQUATION_VISUALIZATION in candidates:
        return LearningMode.STEP_BY_STEP

    return candidates[0]


def get_all_modes(concept_type: str, grade: int) -> list[str]:
    """Return all available modes for this concept type (for the UI mode switcher tab)."""
    base = list(MODE_MAP.get(concept_type, [LearningMode.DIAGRAM]))

    # Always add mindmap as an option
    if LearningMode.MINDMAP not in base:
        base.append(LearningMode.MINDMAP)

    # Gate equation_visualization for young grades
    if grade <= 5 and LearningMode.EQUATION_VISUALIZATION in base:
        base.remove(LearningMode.EQUATION_VISUALIZATION)

    return base
