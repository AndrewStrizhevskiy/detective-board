import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parents[1] / "src"))

FIXTURE_DIR = HERE.parent / "fixtures" / "symbolic"
FIXTURE = FIXTURE_DIR / "holmes_mini.json"
