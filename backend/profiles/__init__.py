"""
vQA — Application Profiles Package
=====================================
Module: backend/profiles/__init__.py

Auto-registers the built-in vSuite profile at import time and exports
the convenience ``get_active_profile()`` function.

Usage
-----
    from backend.profiles import get_active_profile

    profile = get_active_profile()           # Default (vsuite)
    profile = get_active_profile("vsuite")   # Explicit

Architecture Context
--------------------
Importing this package triggers the vSuite profile registration.
Additional profiles can be registered by:
  1. Creating a new module in ``backend/profiles/`` (e.g., ``myapp.py``)
  2. Importing the module (adds to the registry via ``profile_registry.register()``)
  3. Setting ``VQA_PROFILE=myapp`` env var or passing ``profile: "myapp"``
     in the ``/execute`` request body.
"""

from typing import Optional

# Auto-register built-in profiles by importing their modules.
# Each module calls ``profile_registry.register()`` at module level.
import backend.profiles.vsuite  # noqa: F401 — side-effect import

# Re-export core types for convenient importing
from backend.profiles.base import (  # noqa: F401
    AppProfile,
    AuthVerificationStrategy,
    LocatorStep,
    LoginFormSelectors,
    RoleDefinition,
)

# Import the registry singleton
from backend.profiles.registry import profile_registry


def get_active_profile(override: Optional[str] = None) -> AppProfile:
    """
    Get the currently active AppProfile.

    Convenience wrapper around ``profile_registry.get_active()``.

    Resolution order:
      1. ``override`` parameter (from API request)
      2. ``VQA_PROFILE`` environment variable
      3. Default: ``"vsuite"``

    Parameters
    ----------
    override : str, optional
        Explicit profile name.  Empty string = no override.

    Returns
    -------
    AppProfile
        The resolved active profile.

    Example
    -------
    >>> from backend.profiles import get_active_profile
    >>> p = get_active_profile()
    >>> p.name
    'vsuite'
    >>> len(p.roles)
    9
    """
    return profile_registry.get_active(override)
