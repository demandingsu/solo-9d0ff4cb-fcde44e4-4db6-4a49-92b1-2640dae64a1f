import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENDOR = ROOT / ".pylib" / "lib" / "python3.11" / "site-packages"
for path in (ROOT, VENDOR):
    if path.is_dir() and str(path) not in sys.path:
        sys.path.insert(0, str(path))
