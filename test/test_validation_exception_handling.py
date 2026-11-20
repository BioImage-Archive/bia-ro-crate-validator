import pytest

from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.core.validation import Severity
from bia_ro_crate.core.validation.validation_error import ValidationError
from bia_ro_crate.validator import bia_roc_validation


@pytest.mark.parametrize("profile", [None, "bia-submission-v0"])
@pytest.mark.parametrize("mode", ["report", "error"])
def test_unexpected_parser_failure_propagates(tmp_path, monkeypatch, profile, mode):
    def fail(_parser):
        raise RuntimeError("unexpected parser failure")

    monkeypatch.setattr(ROCrateParser, "parse", fail)
    with pytest.raises(RuntimeError, match="unexpected parser failure"):
        bia_roc_validation(tmp_path, mode, profile=profile)


def test_unexpected_exception_group_propagates_even_with_recorded_issues(
    tmp_path, monkeypatch
):
    def fail(parser):
        parser._parse_issues.append(ValidationError("existing issue", Severity.ERROR))
        raise ExceptionGroup("unexpected", [RuntimeError("bug")])

    monkeypatch.setattr(ROCrateParser, "parse", fail)
    with pytest.raises(ExceptionGroup, match="unexpected"):
        bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")


@pytest.mark.parametrize("mode", ["report", "error"])
def test_unexpected_profile_failure_propagates(tmp_path, monkeypatch, mode):
    import bia_ro_crate.validator.profiles.bia_submission_v0 as submission_profile

    def parse(parser):
        parser._result = object()

    class BrokenChecks:
        def __init__(self, _submission):
            pass

        def run(self):
            raise KeyError("unexpected profile failure")

    monkeypatch.setattr(ROCrateParser, "parse", parse)
    monkeypatch.setattr(submission_profile, "SubmissionChecks", BrokenChecks)
    with pytest.raises(KeyError, match="unexpected profile failure"):
        bia_roc_validation(tmp_path, mode, profile="bia-submission-v0")


@pytest.mark.parametrize("profile", [None, "bia-submission-v0"])
def test_recorded_parser_errors_are_reported_or_exit(tmp_path, monkeypatch, profile):
    def fail(parser):
        parser._parse_issues.append(ValidationError("invalid crate", Severity.ERROR))
        parser._raise_errors()

    monkeypatch.setattr(ROCrateParser, "parse", fail)
    report = bia_roc_validation(tmp_path, "report", profile=profile)
    assert report["highest_error_level"] == "ERROR"
    assert report["issues"]["ERROR"][0]["message"] == "invalid crate"
    with pytest.raises(SystemExit) as exc:
        bia_roc_validation(tmp_path, "error", profile=profile)
    assert exc.value.code == 1


def test_profile_parse_input_failure_is_reported(tmp_path, monkeypatch):
    def fail(_parser):
        raise ValueError("invalid input")

    monkeypatch.setattr(ROCrateParser, "parse", fail)
    report = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert report["issues"]["ERROR"][0]["message"] == (
        "Unable to parse the submission: invalid input"
    )


def test_profile_validation_error_is_reported_or_exits(tmp_path, monkeypatch):
    import bia_ro_crate.validator.profiles.bia_submission_v0 as submission_profile

    def parse(parser):
        parser._result = object()

    class InvalidProfile:
        def __init__(self, _submission):
            pass

        def run(self):
            return [ValidationError("invalid profile", Severity.ERROR)]

    monkeypatch.setattr(ROCrateParser, "parse", parse)
    monkeypatch.setattr(submission_profile, "SubmissionChecks", InvalidProfile)
    report = bia_roc_validation(tmp_path, "report", profile="bia-submission-v0")
    assert report["issues"]["ERROR"][0]["message"] == "invalid profile"
    with pytest.raises(SystemExit) as exc:
        bia_roc_validation(tmp_path, "error", profile="bia-submission-v0")
    assert exc.value.code == 1
