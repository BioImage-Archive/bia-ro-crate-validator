import logging
from pathlib import Path

from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.core.validation.severity import Severity

logger = logging.getLogger("__main__." + __name__)
logging.getLogger().setLevel(logging.INFO)
logging.getLogger("rdflib").setLevel(logging.ERROR)


def _log_non_fatal_issues(parser: ROCrateParser) -> None:
    logger_by_severity = {
        Severity.WARNING: logger.warning,
        Severity.INFO: logger.info,
        Severity.DEBUG: logger.debug,
    }

    for issue in parser.issues:
        log_fn = logger_by_severity.get(issue.severity)
        if log_fn is not None:
            log_fn(issue.format_message())


def bia_roc_validation(ro_crate_directory: Path):
    ro_crate_parser = ROCrateParser(ro_crate_directory)
    try:
        ro_crate_parser.parse()
        ro_crate_parser.result
    except ExceptionGroup as validationExceptionGroup:
        _log_non_fatal_issues(ro_crate_parser)
        for exception in validationExceptionGroup.exceptions:
            logger.error(exception)
        raise SystemExit(1)

    _log_non_fatal_issues(ro_crate_parser)
