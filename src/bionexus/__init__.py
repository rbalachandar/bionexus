"""bionexus — lean framework for agentic drug discovery.

Core is dependency-light (pydantic only). All integrations are adapters.
"""
__version__ = "0.1.0"

from bionexus.core.contracts import Envelope  # noqa: F401
from bionexus.core.registry import Registry  # noqa: F401
from bionexus.core.safety import (  # noqa: F401
    ForbiddenComboRule,
    LabGateway,
    MaxBslRule,
    MaxStepsRule,
    SafetyEngine,
)
