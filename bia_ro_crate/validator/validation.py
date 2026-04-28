import logging
from enum import StrEnum
from pathlib import Path

from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.core.validation import Severity

logger = logging.getLogger("__main__." + __name__)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("rdflib").setLevel(logging.ERROR)


class ValidationResponseMode(StrEnum):
    error = "error"
    report = "report"

def _log_issues(parser: ROCrateParser) -> None:
    logger_by_severity = {level: logger.__getattribute__(str(level).lower()) for level in Severity}

    for issue in parser.issues:
        log_fn = logger_by_severity.get(issue.severity)
        if log_fn is not None:
            log_fn(issue.format_message())


def _report_issues(parser: ROCrateParser) -> dict[str, None | dict[str, list[dict]]]:
    report_by_severity = {str(level): [] for level in Severity}
    highest_error_level = 0

    for issue in parser.issues:
        report_by_severity[str(issue.severity)].append(issue.to_dict())
        if issue.severity > highest_error_level:
            highest_error_level = issue.severity

    report  = {
        "highest_error_level": str(highest_error_level) if highest_error_level else None,
        "issues": report_by_severity
    }

    return report



def bia_roc_validation(ro_crate_directory: Path, validation_mode: ValidationResponseMode = ValidationResponseMode.error):
    ro_crate_parser = ROCrateParser(ro_crate_directory)

    try:
        ro_crate_parser.parse()
        ro_crate_parser.result
    except ExceptionGroup:
        raise SystemExit(1)
    finally:           
        _log_issues(ro_crate_parser)
        if validation_mode == ValidationResponseMode.report:
            return _report_issues(ro_crate_parser)
    