from typer.testing import CliRunner

from bia_ro_crate.cli import bia_ro_crate


def test_unknown_profile_rejected():
    result = CliRunner().invoke(bia_ro_crate, ["validate", ".", "--profile", "unknown"])
    assert result.exit_code != 0
    assert "unknown" in result.output

    result = CliRunner().invoke(bia_ro_crate, ["validate", ".", "--profile", "minimal"])
    assert result.exit_code != 0


def test_cli_passes_selected_profile(tmp_path, monkeypatch):
    import bia_ro_crate.cli as cli

    calls = []
    monkeypatch.setattr(
        cli, "bia_roc_validation", lambda path, **kwargs: calls.append((path, kwargs))
    )
    runner = CliRunner()
    assert runner.invoke(bia_ro_crate, ["validate", str(tmp_path)]).exit_code == 0
    assert (
        runner.invoke(
            bia_ro_crate, ["validate", str(tmp_path), "--profile", "bia-submission-v0"]
        ).exit_code
        == 0
    )
    assert [call[1]["profile"] for call in calls] == [None, "bia-submission-v0"]
