"""proef — framework for agentic drug discovery.

Core is dependency-light (pydantic only). All integrations are adapters.
"""
__version__ = "0.1.0"

# Legacy names: this project was called BioNexus. Environment variables set under the old
# prefixes (BIONEXUS_*, BN_*) keep working; the new name wins when both are set.
import os as _os

for _old, _new in (("BIONEXUS_", "PROEF_"), ("BN_PROGRAM", "PROEF_PROGRAM"),
                   ("BN_CAMPAIGN_ID", "PROEF_CAMPAIGN_ID"), ("BN_SKIP_DOCKER", "PROEF_SKIP_DOCKER"),
                   ("BN_REQUIRE_DOCKER", "PROEF_REQUIRE_DOCKER"), ("BN_SANDBOX_IMAGE", "PROEF_SANDBOX_IMAGE")):
    for _k in [k for k in _os.environ if k.startswith(_old)]:
        _os.environ.setdefault(_new + _k[len(_old):] if _old.endswith("_") else _new, _os.environ[_k])

from proef.core.contracts import Envelope  # noqa: F401
from proef.core.registry import Registry  # noqa: F401
from proef.core.safety import (  # noqa: F401
    ForbiddenComboRule,
    LabGateway,
    MaxBslRule,
    MaxStepsRule,
    SafetyEngine,
)
