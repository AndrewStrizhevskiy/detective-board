import sys
from pathlib import Path

# The package is not installed in the bare `uv run --with pytest` env: use the source tree.
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
