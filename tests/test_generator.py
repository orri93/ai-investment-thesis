def test_examples_exclude_drafts_and_template(tmp_path, generator_module):
    for name in ("amzn.md", "nvda.md", "pltr-draft.md", "general-thesis.md"):
        (tmp_path / name).write_text(f"content of {name}", encoding="utf-8")
    generator = generator_module.ThesisGenerator.__new__(generator_module.ThesisGenerator)
    generator.examples_dir = tmp_path
    assert sorted(generator.load_examples()) == ["amzn.md", "nvda.md"]
