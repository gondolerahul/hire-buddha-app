"""
schemas/ — Pydantic DTOs split per bounded context (Phase 11 Track 1).

DO NOT add code here. Add it to the appropriate submodule.

This file is a backwards-compat re-export so existing
``from src.ai.schemas import X`` calls continue to work.
"""
# pyright: reportWildcardImportFromLibrary=false
from src.ai.schemas.enums import *           # noqa: F401, F403
from src.ai.schemas.persona import *         # noqa: F401, F403
from src.ai.schemas.reasoning import *       # noqa: F401, F403
from src.ai.schemas.planning import *        # noqa: F401, F403
from src.ai.schemas.governance import *      # noqa: F401, F403
from src.ai.schemas.io_contract import *     # noqa: F401, F403
from src.ai.schemas.capabilities import *    # noqa: F401, F403
from src.ai.schemas.entity import *          # noqa: F401, F403
from src.ai.schemas.execution import *       # noqa: F401, F403
from src.ai.schemas.document import *        # noqa: F401, F403
from src.ai.schemas.cortex import *          # noqa: F401, F403
from src.ai.schemas.tools import *           # noqa: F401, F403
from src.ai.schemas.prompts import *         # noqa: F401, F403
