SCHEMA = {
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
    for section, fields in SCHEMA.items():
        fixed[section] = {}
        raw_section = data.get(section, {})

        for key, t in fields.items():
            fixed[section][key] = normalize(raw_section.get(key), t)

    return fixed
