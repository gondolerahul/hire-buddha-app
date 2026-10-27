"""Run a ``world`` helper where an environment's settings are — an API pod (Phase 15 T10-2).

The journeys drive a browser from wherever they run; their data setup needs
the environment's database and signing key, which on Azure only its pods
have. With ``JOURNEY_KUBE=<namespace>/<pod or deploy/name>`` the journeys'
``db_call`` sends each helper here through ``kubectl exec``::

    python -m tests.journeys.remote <helper> <base64 JSON arguments>

It prints one line, ``JOURNEY-RESULT <JSON>``. A ``World`` travels as
``{"__world__": …}``; ids as strings. Only this module, ``world`` and the two
harness modules it uses need to be on the pod (the journeys' conftest copies
them to ``/tmp`` first): the image has no pytest.
"""
from __future__ import annotations

import base64
import json
import sys
import uuid
from typing import Any

MARK = "JOURNEY-RESULT "


def encode(value: Any) -> Any:
    from tests.journeys.world import World

    if isinstance(value, World):
        return {"__world__": value.to_json()}
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, dict):
        return {str(k): encode(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [encode(v) for v in value]
    return value


def decode(value: Any) -> Any:
    from tests.journeys.world import World

    if isinstance(value, dict) and "__world__" in value:
        return World.from_json(value["__world__"])
    if isinstance(value, dict):
        return {k: decode(v) for k, v in value.items()}
    if isinstance(value, list):
        return [decode(v) for v in value]
    return value


def main(argv: list) -> int:
    from tests.journeys import world

    helper, raw = argv[1], argv[2]
    args = decode(json.loads(base64.b64decode(raw)))
    # Ids arrive as strings; the helpers take UUIDs where they name a company.
    args = [uuid.UUID(a) if isinstance(a, str) and helper in ("spend", "pay", "partner_state", "company_exists") and i == 0 else a
            for i, a in enumerate(args)]
    if helper == "teardown" and len(args) > 1:
        args[1] = [uuid.UUID(str(a)) for a in args[1]]
    result = getattr(world, helper)(*args)
    print(MARK + json.dumps(encode(result), default=str), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
