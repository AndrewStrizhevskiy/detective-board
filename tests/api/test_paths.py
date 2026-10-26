"""Default data paths match what the builders write; real-mode startup reports them."""

import pytest

from detective_board.api import ApiConfig
from detective_board.api.__main__ import main
from detective_board.api.config import REPO_ROOT, load_config
from detective_board.index import build as index_build


def test_defaults_match_builders():
    cfg = ApiConfig()
    assert cfg.index_path == "data/index/db.sqlite"
    assert cfg.graph_path == "data/graph/graph.sqlite"
    assert cfg.embed_model == index_build.CONFIG.model
    assert cfg.embed_dim == index_build.CONFIG.dim
    assert cfg.embed_doc_prefix == index_build.CONFIG.doc_prefix
    assert cfg.embed_query_prefix == index_build.CONFIG.query_prefix
    assert str(cfg.resolve(cfg.index_path)).startswith(str(REPO_ROOT))


def test_data_status_present_and_missing(tmp_path):
    idx = tmp_path / "index" / "db.sqlite"
    idx.parent.mkdir()
    idx.write_bytes(b"")
    cfg = ApiConfig(index_path=str(idx), graph_path=str(tmp_path / "graph" / "graph.sqlite"))
    index_line, graph_line = cfg.data_status()
    assert index_line.startswith("index: present")
    assert graph_line.startswith("graph: graph not found") and "just graph" in graph_line


def test_main_without_index_exits_with_actionable_message(tmp_path, capsys, monkeypatch):
    monkeypatch.setenv("DETECTIVE_BOARD_INDEX_PATH", str(tmp_path / "nope.sqlite"))
    monkeypatch.setenv("DETECTIVE_BOARD_GRAPH_PATH", str(tmp_path / "nope-g.sqlite"))
    with pytest.raises(SystemExit) as e:
        main([])
    assert e.value.code == 2
    err = capsys.readouterr().err
    assert "just index" in err and "just graph" in err


def test_main_reports_present_files(tmp_path, capsys, monkeypatch):
    for n in ("i", "g"):
        (tmp_path / f"{n}.sqlite").write_bytes(b"")
    monkeypatch.setenv("DETECTIVE_BOARD_INDEX_PATH", str(tmp_path / "i.sqlite"))
    monkeypatch.setenv("DETECTIVE_BOARD_GRAPH_PATH", str(tmp_path / "g.sqlite"))
    called = {}
    import uvicorn

    monkeypatch.setattr(uvicorn, "run", lambda app, **kw: called.update(kw))
    main(["--port", "8123"])
    err = capsys.readouterr().err
    assert "index: present" in err and "graph: present" in err
    assert called["port"] == 8123
    assert load_config().index_path.endswith("i.sqlite")
