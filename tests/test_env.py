from agentguard import config


def test_load_env_reads_values_and_real_env_wins(tmp_path, monkeypatch):
    f = tmp_path / ".env"
    f.write_text('# comment\nAG_A=1\nAG_B="two"\nAG_C=\nAG_D=from_file\n')
    for k in ("AG_A", "AG_B", "AG_C"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("AG_D", "from_shell")
    config.load_env(f)
    import os

    assert os.environ["AG_A"] == "1" and os.environ["AG_B"] == "two"
    assert "AG_C" not in os.environ  # blank placeholders are skipped
    assert os.environ["AG_D"] == "from_shell"
    for k in ("AG_A", "AG_B"):
        monkeypatch.delenv(k, raising=False)


def test_load_env_missing_file_is_fine(tmp_path):
    config.load_env(tmp_path / "nope.env")
