SCHEMA = {
    "lesson_overview": str,
    "learning_outcomes": {
        "items": list,
        "time": int
    },
    "core_instruction": {
        "text": str,
        "time": int
    },
    "practice_activity": {
        "text": str,
        "time": int
    },
    "assessment": {
        "text": str,
        "time": int
    }
}

def normalize(value, expected_type):
    if expected_type == list:
        if isinstance(value, list): return value
        if isinstance(value, str): return [value]
        return []
    if expected_type == int:
        try: return int(value)
        except: return 0
    if expected_type == str:
        return value if isinstance(value, str) else ""
    return value

def validate_and_fix(data: dict) -> dict:
    fixed = {}
    for key, expected_structure in SCHEMA.items():
        # Case 1: Nested Section (dict)
        if isinstance(expected_structure, dict):
            fixed[key] = {}
            raw_section = data.get(key, {})
            # If raw_section is not a dict (e.g. missing or wrong type), treat as empty
            if not isinstance(raw_section, dict):
                raw_section = {}
            
            for field, t in expected_structure.items():
                fixed[key][field] = normalize(raw_section.get(field), t)
        
        # Case 2: Flat Field (type)
        elif isinstance(expected_structure, type):
            fixed[key] = normalize(data.get(key), expected_structure)

    return fixed
