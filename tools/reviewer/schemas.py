from typing import Any, Dict, List

RULE_IDS: List[str] = [
    "TMA-UI-01",
    "TMA-UI-02",
    "TMA-SEC-01",
    "STATE-01",
    "BACK-01",
]

SEVERITY_LEVELS: List[str] = ["CRITICAL", "WARNING"]

RESPONSE_JSON_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "properties": {
        "passed": {"type": "boolean"},
        "summary": {"type": "string"},
        "issues": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "rule_id": {"type": "string", "enum": RULE_IDS},
                    "severity": {"type": "string", "enum": SEVERITY_LEVELS},
                    "file": {"type": "string"},
                    "line_hint": {"type": "string"},
                    "message": {"type": "string"},
                    "suggestion": {"type": "string"},
                },
                "required": [
                    "rule_id",
                    "severity",
                    "file",
                    "line_hint",
                    "message",
                    "suggestion",
                ],
            },
        },
    },
    "required": ["passed", "summary", "issues"],
}