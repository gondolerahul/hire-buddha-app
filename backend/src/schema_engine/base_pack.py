"""Base pack v1 (tech spec §8.5): the platform's standard objects in schema
``business`` — account, contact (with its lifecycle stage, D10), activity
(an actual business interaction, D11) and consent.

One definition: the planner turns it into both the blueprint entries and the
DDL (an ``add_object`` per object), so the two cannot drift. Base-pack
upgrades never add ``x_`` columns or ``custom`` tables, so a business's own
additions cannot collide with them.
"""
from __future__ import annotations

from typing import Any, Dict, List

VERSION = "1.0"

LIFECYCLE_STAGES = ["subscriber", "lead", "marketing_qualified", "sales_qualified", "opportunity", "customer",
                    "evangelist", "other"]

OBJECTS: Dict[str, Dict[str, Any]] = {
    "account": {
        "label": "Account", "plural": "Accounts",
        "description": "An organisation the business deals with.",
        "fields": {
            "name": {"type": "text", "max_length": 200, "required": True},
            "domain": {"type": "text", "max_length": 200},
            "industry": {"type": "text", "max_length": 120},
            "website": {"type": "url"},
            "phone": {"type": "phone", "sensitivity": "pii"},
            "city": {"type": "text", "max_length": 120},
            "country": {"type": "text", "max_length": 2},
        },
        "indexes": [["name"], ["domain"]],
    },
    "contact": {
        "label": "Contact", "plural": "Contacts",
        "description": "A person; 'lead' is a lifecycle stage, not a separate object (D10).",
        "fields": {
            "first_name": {"type": "text", "max_length": 120},
            "last_name": {"type": "text", "max_length": 120},
            "email": {"type": "email", "sensitivity": "pii"},
            "phone": {"type": "phone", "sensitivity": "pii"},
            "account": {"type": "ref", "to": "account", "on_delete": "set_null"},
            "lifecycle_stage": {"type": "enum", "values": LIFECYCLE_STAGES, "default": "lead"},
            "source": {"type": "text", "max_length": 120},
            "external_ref": {"type": "text", "max_length": 200},
        },
        "indexes": [["email"], ["phone"], ["lifecycle_stage"], ["account"]],
    },
    "activity": {
        "label": "Activity", "plural": "Activities",
        "description": "An actual interaction with a contact: a call, a message, a meeting (D11).",
        "fields": {
            "contact": {"type": "ref", "to": "contact", "on_delete": "cascade"},
            "account": {"type": "ref", "to": "account", "on_delete": "set_null"},
            "kind": {"type": "enum", "values": ["call", "email", "message", "meeting", "note", "task", "visit"],
                     "required": True},
            "subject": {"type": "text", "max_length": 300},
            "body": {"type": "long_text"},
            "occurred_at": {"type": "datetime"},
            "channel": {"type": "text", "max_length": 60},
            "run_id": {"type": "text", "max_length": 64},
        },
        "indexes": [["contact"], ["occurred_at"]],
    },
    "consent": {
        "label": "Consent", "plural": "Consents",
        "description": "Whether a contact agreed to be contacted, on which channel, for what.",
        "fields": {
            "contact": {"type": "ref", "to": "contact", "on_delete": "cascade", "required": True},
            "channel": {"type": "enum", "values": ["email", "phone", "sms", "whatsapp", "post"], "required": True},
            "purpose": {"type": "text", "max_length": 120},
            "status": {"type": "enum", "values": ["granted", "withdrawn"], "required": True, "default": "granted"},
            "recorded_at": {"type": "datetime"},
            "evidence": {"type": "long_text"},
        },
        "indexes": [["contact"], ["channel", "status"]],
    },
}

ORDER = ["account", "contact", "activity", "consent"]  # references point backwards


def operations() -> List[Dict[str, Any]]:
    """The base pack as change operations: one ``add_object`` each, in dependency order."""
    return [{"op": "add_object", "object": name,
             "definition": {**OBJECTS[name], "storage": {"schema": "business", "table": name}, "platform": True}}
            for name in ORDER]
