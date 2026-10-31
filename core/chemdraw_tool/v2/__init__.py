"""Task-level surface (v2).

The caller is an agent, not a person: one call per task, every answer carries a
preview image and a verifiable identity. See docs/v2/requirements.md.
"""

from . import geometry, route, session, tasks  # noqa: F401

__all__ = ['geometry', 'route', 'session', 'tasks']