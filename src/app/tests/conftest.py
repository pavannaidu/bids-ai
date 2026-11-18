import sys
from pathlib import Path

# Makes `from server...` importable regardless of the directory pytest is
# invoked from — server/ isn't pip-installed, it's just a plain package.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
