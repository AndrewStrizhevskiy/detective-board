"""scripts/check_vendor_hashes.py: vendored web assets match the sums in web/vendor/README.md."""

import importlib.util
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location(
    "check_vendor_hashes", ROOT / "scripts" / "check_vendor_hashes.py"
)
assert _spec and _spec.loader
cvh = importlib.util.module_from_spec(_spec)
sys.modules["check_vendor_hashes"] = cvh
_spec.loader.exec_module(cvh)


def test_vendored_assets_match_their_recorded_sums():
    assert cvh.check() == []


def test_a_changed_or_unrecorded_asset_is_caught(tmp_path):
    vendor = tmp_path / "vendor"
    shutil.copytree(ROOT / "web" / "vendor", vendor)
    target = vendor / "fonts" / "special-elite-latin.woff2"
    target.write_bytes(target.read_bytes() + b"x")
    (vendor / "extra.js").write_text("// not recorded")
    problems = cvh.check(vendor)
    assert any(p.startswith("fonts/special-elite-latin.woff2: sha256") for p in problems)
    assert "extra.js: no sha256 recorded in web/vendor/README.md" in problems
