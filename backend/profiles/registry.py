"""
vQA — Profile Registry
========================
Module: backend/profiles/registry.py

Singleton registry that maps profile names → AppProfile instances.

Usage
-----
    from backend.profiles.registry import profile_registry

    # Register a profile (typically done in the profile's own module)
    profile_registry.register(my_profile)

    # Get the active profile (from VQA_PROFILE env var or default)
    profile = profile_registry.get_active()

    # Get a specific profile by name
    profile = profile_registry.get("vsuite")

    # List all registered profiles
    names = profile_registry.list_profiles()

Architecture Context
--------------------
The registry is populated at import time by ``backend/profiles/__init__.py``
which auto-imports the ``vsuite`` profile module.  Additional profiles
can be registered by importing their modules or calling ``register()``
directly.

The active profile is resolved in this priority order:
  1. Explicit name passed to ``get()`` (e.g., from API request body)
  2. ``VQA_PROFILE`` environment variable
  3. Default: ``"vsuite"``

See Also
--------
  - ``backend/profiles/base.py``    — AppProfile dataclass
  - ``backend/profiles/vsuite.py``  — reference vSuite profile
  - ``backend/profiles/__init__.py`` — auto-registration
"""

import logging
import os
from typing import Optional

from backend.profiles.base import AppProfile

logger = logging.getLogger(__name__)


class ProfileRegistry:
    """
    Singleton registry mapping profile names → AppProfile instances.

    Thread-safe for reads (the common path).  Registration is expected
    to happen only during startup, before any concurrent requests.

    Attributes
    ----------
    _profiles : dict[str, AppProfile]
        Internal mapping of lowercase profile names to instances.

    _default_name : str
        Name of the default profile when no explicit selection is made.
    """

    def __init__(self, default_name: str = "vsuite") -> None:
        self._profiles: dict[str, AppProfile] = {}
        self._default_name: str = default_name

    def register(self, profile: AppProfile) -> None:
        """
        Register an AppProfile instance.

        If a profile with the same name is already registered, it is
        silently replaced (allows hot-reload during development).

        Parameters
        ----------
        profile : AppProfile
            The profile to register.  ``profile.name`` is used as the key.

        Raises
        ------
        ValueError
            If the profile has an empty name.
        """
        if not profile.name:
            raise ValueError("AppProfile.name cannot be empty")

        key = profile.name.lower()
        action = "replaced" if key in self._profiles else "registered"
        self._profiles[key] = profile
        logger.info(
            "Profile %s: '%s' (%s) — %d roles, auth=%s",
            action,
            profile.name,
            profile.display_name,
            len(profile.roles),
            profile.auth_verification,
        )

    def get(self, name: str) -> AppProfile:
        """
        Get a profile by name.

        Parameters
        ----------
        name : str
            Profile name (case-insensitive).

        Returns
        -------
        AppProfile
            The registered profile.

        Raises
        ------
        KeyError
            If no profile with the given name is registered.
        """
        key = name.lower()
        if key not in self._profiles:
            available = ", ".join(sorted(self._profiles.keys())) or "(none)"
            raise KeyError(f"Profile '{name}' not found. Available profiles: {available}")
        return self._profiles[key]

    def get_active(self, override: Optional[str] = None) -> AppProfile:
        """
        Get the currently active profile.

        Resolution order:
          1. ``override`` parameter (from API request body)
          2. ``VQA_PROFILE`` environment variable
          3. Default profile (``"vsuite"``)

        Parameters
        ----------
        override : str, optional
            Explicit profile name from the API request.
            Empty string is treated as "no override".

        Returns
        -------
        AppProfile
            The resolved active profile.
        """
        name = override or os.getenv("VQA_PROFILE", "") or self._default_name
        return self.get(name)

    def list_profiles(self) -> list[str]:
        """Return sorted list of all registered profile names."""
        return sorted(self._profiles.keys())

    def is_registered(self, name: str) -> bool:
        """Check if a profile name is registered (case-insensitive)."""
        return name.lower() in self._profiles

    @property
    def default_name(self) -> str:
        """The default profile name."""
        return self._default_name


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

#: Global profile registry instance.  Populated by profile modules.
profile_registry = ProfileRegistry()
"""
Singleton profile registry.

Usage::

    from backend.profiles.registry import profile_registry
    profile = profile_registry.get_active()
"""
