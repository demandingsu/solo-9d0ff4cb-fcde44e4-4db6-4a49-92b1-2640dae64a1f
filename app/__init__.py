"""Technical-response checker web application."""

from __future__ import annotations

import sys
from pathlib import Path

# The repository ships its runtime dependencies in .pylib so the application
# can be started and tested without network access.  Adding that directory
# here (before app.main imports FastAPI) keeps local runs simple.
_VENDOR = Path(__file__).resolve().parent.parent / ".pylib" / "lib" / "python3.11" / "site-packages"
if _VENDOR.is_dir() and str(_VENDOR) not in sys.path:
    sys.path.insert(0, str(_VENDOR))
