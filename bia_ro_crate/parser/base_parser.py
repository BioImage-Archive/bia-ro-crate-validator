from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from ..validation import Severity, ValidationError


class Parser[ParsedType](ABC):
    """Generic parser for any kind of file needed to be parsed in an ro-crate."""

    _result: ParsedType | None
    _ro_crate_root: Path
    _parse_issues: list[ValidationError]

    def __init__(
        self, ro_crate_root: Path | str, *, context: Any | None = None
    ) -> None:
        self._result = None
        self._ro_crate_root = Path(ro_crate_root)
        self._parse_issues = []
        super().__init__()

    @abstractmethod
    def parse(self, target: Path | str | None):
        # TODO update this path to always be relative to the root of the ro-crate for consistency
        raise NotImplementedError

    @property
    def result(self) -> ParsedType:
        if self._result is None:
            raise RuntimeError("parse() must be called prior to accessing result")
        self._raise_errors()
        return self._result

    def _raise_errors(self):
        fatal_errors = [
            e.to_exception() for e in self._parse_issues if e.severity is Severity.ERROR
        ]
        if len(fatal_errors) > 0:
            raise ExceptionGroup("Validation failed.", fatal_errors)
