
from app.utils.validator import validate_and_fix, SCHEMA
import json

data = {
    "lesson_overview": "This is a summary.",
    "learning_outcomes": {
        "items": ["Outcome 1"],
        "time": 5
    },
    "extra_field": "should be removed"
}

print(f"SCHEMA keys: {SCHEMA.keys()}")
fixed = validate_and_fix(data)
print(f"Fixed: {json.dumps(fixed, indent=2)}")

assert "lesson_overview" in fixed, "lesson_overview missing!"
assert fixed["lesson_overview"] == "This is a summary.", "matches input"
print("Test Passed")
