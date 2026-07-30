"""Environment helpers for Nobody ``NOBODY_*`` settings."""

from __future__ import annotations

import os
from typing import Optional


def env_get(name: str, default: Optional[str] = None) -> Optional[str]:
    """Read ``NOBODY_<suffix>`` (or a full ``NOBODY_*`` key).

    ``name`` may be the full key (``NOBODY_ADMIN_USER``) or the shared
    suffix (``ADMIN_USER``). Empty strings count as set.
    """
    if name.startswith("NOBODY_"):
        key = name
    else:
        key = f"NOBODY_{name}"

    if key in os.environ:
        return os.environ[key]
    return default
