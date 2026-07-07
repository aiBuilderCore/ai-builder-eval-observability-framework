"""eeof_core — shared contracts, data plane, model providers, and job plumbing.

Import surface used across the eight services. The data plane and provider are
selected by config (APP_ENV, MODEL_PROVIDER) so services never branch on env.
"""

from . import dataplane, ids, jobs, messaging, models
from .config import settings
from .providers import get_provider
from .worker import BaseWorker

__all__ = [
    "BaseWorker",
    "dataplane",
    "get_provider",
    "ids",
    "jobs",
    "messaging",
    "models",
    "settings",
]
