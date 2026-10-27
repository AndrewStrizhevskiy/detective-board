"""Offline archive scripts (issue #8): what can be checked without Linux, Ollama or the data."""

import hashlib
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
PACK = ROOT / "scripts" / "pack_offline.sh"
VERIFY = ROOT / "scripts" / "verify_offline.sh"

bash = shutil.which("bash")
pytestmark = pytest.mark.skipif(bash is None, reason="needs bash")


@pytest.mark.parametrize("script", [PACK, VERIFY])
def test_scripts_parse_and_have_help(script):
    assert subprocess.run([bash, "-n", str(script)], capture_output=True).returncode == 0
    out = subprocess.run([bash, str(script), "--help"], capture_output=True, text=True)
    assert out.returncode == 0 and "Usage:" in out.stdout
    # the help is the comment header only, every line of it
    assert all(line.startswith("#") for line in out.stdout.splitlines())


# the dry run resolves the ref with git; the archive's copy of the repo (git archive) has no .git
needs_git = pytest.mark.skipif(not (ROOT / ".git").exists(), reason="needs a git checkout")


def _dry_run(env_extra, tmp_path):
    env = {**os.environ, **env_extra, "PATH": f"{tmp_path / 'bin'}:/usr/bin:/bin"}
    return subprocess.run(
        [bash, str(PACK), "--dry-run"], capture_output=True, text=True, env=env, cwd=ROOT
    )


@needs_git
def test_dry_run_names_every_missing_input_and_refuses(tmp_path):
    (tmp_path / "bin").mkdir()
    out = _dry_run({"OLLAMA_MODELS": str(tmp_path / "nowhere")}, tmp_path)
    assert out.returncode == 2
    assert "NOT READY" in out.stdout
    if not shutil.which("ollama", path="/usr/bin:/bin"):  # some distros install it there
        assert "ollama not found on PATH" in out.stdout
    for model in ("bge-m3:latest", "qwen3:4b-instruct", "qwen3:4b"):
        assert f"model not pulled: {model}" in out.stdout
    assert "qwen3:8b" not in out.stdout, "the 8B model is optional (--with-8b)"


@needs_git
def test_a_model_with_another_build_is_refused(tmp_path):
    """The manifest's sha256 prefix must equal the ID pinned in docs/team/models.md."""
    models = tmp_path / "models"
    mf = models / "manifests" / "registry.ollama.ai" / "library" / "bge-m3" / "latest"
    mf.parent.mkdir(parents=True)
    mf.write_text('{"config": {"digest": "sha256:00"}, "layers": []}')
    have = hashlib.sha256(mf.read_bytes()).hexdigest()[:12]
    (tmp_path / "bin").mkdir()
    out = _dry_run({"OLLAMA_MODELS": str(models)}, tmp_path)
    assert out.returncode == 2
    assert f"model bge-m3:latest has ID {have}, docs/team/models.md pins 790764642607" in out.stdout
