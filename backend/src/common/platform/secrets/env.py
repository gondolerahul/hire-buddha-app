"""``env`` secrets: ``some-secret`` is the environment variable ``SOME_SECRET``."""
from __future__ import annotations

import os
from typing import Optional

from src.common.platform.secrets import validate_secret_name


def env_name(secret_name: str) -> str:
    return validate_secret_name(secret_name).upper().replace("-", "_")


class EnvSecrets:
    name = "env"

    async def get(self, name: str) -> Optional[str]:
        value = os.environ.get(env_name(name))
        return value if value else None
