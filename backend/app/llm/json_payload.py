from __future__ import annotations

import json
from typing import Any

from pydantic_core import to_jsonable_python


def dumps_model_payload(value: Any, **kwargs: Any) -> str:
    """Serialize business values into the JSON text sent to model providers."""
    return json.dumps(
        to_jsonable_python(value, fallback=str),
        **kwargs,
    )
