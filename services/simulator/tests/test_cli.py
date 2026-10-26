"""`python -m pitchmind_simulator`: file output and the paced live stream."""

import argparse
import json
from pathlib import Path

import pytest
from pitchmind_simulator import __main__ as cli


def test_writes_a_match_file_and_prints_a_summary(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "nested" / "M042.jsonl"
    argv = ["sim", "--scenario", "organic", "--seed", "42", "--match-id", "M042", "--out", str(out)]
    monkeypatch.setattr("sys.argv", argv)
    cli.main()
    lines = out.read_text(encoding="utf-8").splitlines()
    assert json.loads(lines[0])["msg"] == "match_meta"
    assert len(lines) > 500
    printed = capsys.readouterr().out
    assert "organic seed=42" in printed and "pass accuracy" in printed


def test_live_mode_streams_to_stdout_paced_by_match_time(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    sleeps: list[float] = []
    monkeypatch.setattr("time.sleep", sleeps.append)
    monkeypatch.setattr("sys.argv", ["sim", "--live", "--speed", "1000"])
    cli.main()
    lines = capsys.readouterr().out.splitlines()
    assert json.loads(lines[0])["msg"] == "match_meta"
    assert len(sleeps) > 100  # one pause per new match second


def test_speed_must_be_positive() -> None:
    assert cli.positive_float("2.5") == 2.5
    with pytest.raises(argparse.ArgumentTypeError):
        cli.positive_float("0")
