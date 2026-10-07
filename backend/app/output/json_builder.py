import json


def build_json(document: dict) -> str:
    """Deterministic, valid JSON of the canonical document (key order = model field order)."""
    return json.dumps(document, indent=2, ensure_ascii=False, allow_nan=False)
