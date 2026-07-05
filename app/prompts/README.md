# app/prompts

**Every LLM prompt lives here** — one home, never inline in a service. A service
imports its prompt; it does not define one.

## Two forms
- **`.py` modules** — prompt strings (`.format()` placeholders), builder functions,
  or small dicts. Import directly:
  `from app.prompts.summary import SUMMARY_PROMPT, validate_blocks`
- **`.txt` files** — the large system prompts, loaded at runtime with
  `Path(__file__).parent.parent / "prompts" / "X_prompt.txt"` + `.read_text()`
  (cached in a module global). Used for the biggest prompts (story, silf, guru, engine).

## Contents
| File | Used by |
|------|---------|
| `summary.py` (`SUMMARY_PROMPT` + `validate_blocks`) | daily_class_service, summary_blocks |
| `widget.py` (`WIDGET_PROMPT`) | daily_class_service |
| `mindmap.py` (`MINDMAP_PROMPT`) | mindmap |
| `chat.py` (`TUTOR_SYSTEM_PROMPT`) | chat_service |
| `tts.py` (`SSML_TEMPLATE`) | ai_service |
| `simulation.py` (templates + `_build_simulation_prompt`) | ai_service |
| `silf_animation.py` (`ANIM_SYSTEM`, `PANEL_SYSTEM`) | silf_animation_service |
| `silf_verifier.py` (`JUDGE_SYSTEM`) | silf_verifier_service |
| `intervention.py` (`TIER_BRIEF`, `build_intervention_prompt`) | intervention_engine |
| `quiz_prompts.py`, `lesson_plan_prompt.py`, `learning_engine_prompts.py` | quiz/lesson-plan/learning-engine |
| `*.txt` (story / silf_story / guru_shishya / engine) | story/silf/guru/engine services |

## Rule
Adding an LLM call? Put its prompt in a file here and import it. Small per-request
user-message assembly (interpolating the current topic/summary into a `messages`
list) stays in the service — that's request shaping, not a reusable prompt.
