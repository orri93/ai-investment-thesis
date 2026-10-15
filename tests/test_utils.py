import os
from pathlib import Path

import pytest

import utils


def test_extract_json_object_handles_plain_fenced_and_embedded_json():
    assert utils.extract_json_object('{"a": 1}') == '{"a": 1}'
    assert utils.extract_json_object('```json\n{"a": 1}\n```') == '{"a": 1}'
    assert utils.extract_json_object('Here you go: {"a": {"b": 2}} done') == '{"a": {"b": 2}}'


def test_extract_json_object_raises_without_object():
    with pytest.raises(ValueError):
        utils.extract_json_object("no json here")


def test_pretty_json_formats_or_passes_through():
    assert utils.pretty_json('{"a":1}') == '{\n  "a": 1\n}'
    assert utils.pretty_json("not json") == "not json"


def test_first_content_line_skips_headings_and_blanks():
    assert utils.first_content_line("# Title\n\n## Sub\nBody line\nMore") == "Body line"
    assert utils.first_content_line("# Only heading") == "(no content)"


def test_ticker_from_thesis_path():
    assert utils.ticker_from_thesis_path(Path("thesis/amzn.md")) == "AMZN"


def test_write_text_atomic_writes_and_leaves_no_temp_files(tmp_path):
    target = tmp_path / "nested" / "log.md"
    utils.write_text_atomic(target, "first\n")
    utils.write_text_atomic(target, "second\n")
    assert target.read_text(encoding="utf-8") == "second\n"
    assert [p.name for p in target.parent.iterdir()] == ["log.md"]


def test_write_text_atomic_keeps_original_when_replace_fails(tmp_path, monkeypatch):
    target = tmp_path / "log.md"
    target.write_text("original", encoding="utf-8")

    def failing_replace(src, dst):
        raise OSError("disk full")

    monkeypatch.setattr(utils.os, "replace", failing_replace)
    with pytest.raises(OSError):
        utils.write_text_atomic(target, "new content")
    assert target.read_text(encoding="utf-8") == "original"
    assert [p.name for p in tmp_path.iterdir()] == ["log.md"]


def test_report_unexpected_error_prints_traceback_only_when_verbose(capsys):
    try:
        raise KeyError("boom")
    except KeyError as exc:
        utils.report_unexpected_error(exc, verbose=False)
        quiet = capsys.readouterr().err
        utils.report_unexpected_error(exc, verbose=True)
        verbose = capsys.readouterr().err
    assert "Unexpected error: 'boom'" in quiet and "Traceback" not in quiet and "--verbose" in quiet
    assert "Traceback (most recent call last)" in verbose


def test_load_environment_reads_env_file_without_overriding(tmp_path, monkeypatch):
    env_file = tmp_path / ".env"
    env_file.write_text("AIT_TEST_FROM_FILE=file\nAIT_TEST_PRESET=file\n", encoding="utf-8")
    monkeypatch.delenv("AIT_TEST_FROM_FILE", raising=False)
    monkeypatch.setenv("AIT_TEST_PRESET", "environment")

    utils.load_environment(env_file)

    assert os.environ["AIT_TEST_FROM_FILE"] == "file"
    assert os.environ["AIT_TEST_PRESET"] == "environment"
    monkeypatch.delenv("AIT_TEST_FROM_FILE")
