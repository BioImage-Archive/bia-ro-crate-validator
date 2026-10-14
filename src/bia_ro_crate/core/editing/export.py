"""Serialize, reparse and publish metadata and a TSV without overwriting files."""

import csv
import json
import math
import re
import shutil
from numbers import Integral, Real
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from urllib.parse import unquote, urlsplit

import pandas as pd
from rdflib.compare import isomorphic

from bia_ro_crate.core.bia_submission_metadata import BIASubmissionMetadata
from bia_ro_crate.core.parser.osv_metadata_parser import OSVMetadataParser

from .validation import metadata_graph

_METADATA = "ro-crate-metadata.json"
_WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL"} | {
    f"{prefix}{number}" for prefix in ("COM", "LPT") for number in range(1, 10)
}


def _manifest_relative_path(submission: BIASubmissionMetadata) -> Path:
    entity = submission.metadata.get_file_list_entity()
    identifier = entity.id
    uri = urlsplit(identifier)
    if uri.scheme or uri.netloc or "?" in identifier or "#" in identifier:
        raise ValueError("The manifest must have a local relative file identifier")
    if re.search(r"%(?![0-9a-fA-F]{2})", identifier):
        raise ValueError("Malformed percent escape in manifest identifier")
    decoded = unquote(identifier, encoding="utf-8", errors="strict")
    if (
        not decoded
        or any(c in decoded for c in '\\:\x00<>"|?*')
        or any(ord(c) < 32 for c in decoded)
    ):
        raise ValueError("Unsafe manifest filename")
    posix = PurePosixPath(decoded)
    if posix.is_absolute() or ".." in posix.parts or not posix.parts:
        raise ValueError("The manifest must remain inside the output directory")
    for part in posix.parts:
        if (
            part.endswith((".", " "))
            or part.upper().split(".", 1)[0] in _WINDOWS_RESERVED
        ):
            raise ValueError("Manifest filename is not portable")
        if part.casefold() == _METADATA.casefold():
            raise ValueError("Manifest path collides with the metadata filename")
    declared = (entity.model_extra or {}).get("encodingFormat")
    if declared not in (None, "text/tab-separated-values"):
        raise ValueError("This writer supports only TSV file lists")
    return Path(*posix.parts)


def _cell_text(value, *, multivalued: bool) -> str:
    if multivalued:
        if not isinstance(value, list):
            raise ValueError(
                "Multivalued columns must contain lists, including [] for missing values"
            )
        for item in value:
            if not isinstance(item, str) or not item or item != item.strip():
                raise ValueError(
                    "Multivalued identifiers must be nonempty, unpadded strings"
                )
            if any(c in item for c in ",[]\"'\t\r\n\x00"):
                raise ValueError(
                    "List member cannot round-trip through the existing OSV grammar"
                )
        return ",".join(value)
    if value is None or value is pd.NA:
        return ""
    if isinstance(value, str):
        if "\x00" in value:
            raise ValueError("TSV values cannot contain NUL")
        return value
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, Integral):
        return str(value)
    if isinstance(value, Real):
        if math.isnan(value):
            return ""
        if not math.isfinite(value):
            raise ValueError("Infinite TSV values are not supported")
        number = float(value)
        if value != number:
            raise ValueError(
                "File-list number cannot be represented without precision loss"
            )
        return repr(number)
    raise TypeError(f"Unsupported TSV cell type: {type(value).__name__}")


def _serialize_pair(submission: BIASubmissionMetadata, directory: Path) -> Path:
    """Write unvalidated candidate bytes in a caller-owned private staging dir."""
    manifest = _manifest_relative_path(submission)
    destination = directory / manifest
    destination.parent.mkdir(parents=True, exist_ok=True)
    columns = [
        submission.file_list.schema[c] for c in submission.file_list.data.columns
    ]
    with destination.open("x", encoding="utf-8", newline="") as stream:
        writer = csv.writer(stream, delimiter="\t", lineterminator="\n")
        writer.writerow([c.columnName for c in columns])
        for row in submission.file_list.data.itertuples(index=False, name=None):
            writer.writerow(
                [
                    _cell_text(
                        value,
                        multivalued=column.propertyUrl
                        in OSVMetadataParser.DEFAULT_LIST_PROPERTIES,
                    )
                    for column, value in zip(columns, row, strict=True)
                ]
            )
    with (directory / _METADATA).open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(
            submission.metadata.to_dict(),
            stream,
            indent=2,
            ensure_ascii=False,
            allow_nan=False,
        )
        stream.write("\n")
    return manifest


def _same_value(left, right) -> bool:
    if isinstance(left, list) or isinstance(right, list):
        return (
            isinstance(left, list)
            and isinstance(right, list)
            and len(left) == len(right)
            and all(_same_value(a, b) for a, b in zip(left, right, strict=True))
        )
    left_missing = (
        left is None
        or left is pd.NA
        or (
            isinstance(left, Real)
            and not isinstance(left, Integral)
            and math.isnan(left)
        )
    )
    right_missing = (
        right is None
        or right is pd.NA
        or (
            isinstance(right, Real)
            and not isinstance(right, Integral)
            and math.isnan(right)
        )
    )
    if left_missing or right_missing:
        return left_missing and right_missing
    if isinstance(left, bool) != isinstance(right, bool):
        return False
    # Convert numpy scalar numbers to Python scalars BEFORE comparing: numpy
    # can coerce a large integer to a rounded float and report false equality.
    if isinstance(left, Integral):
        left = int(left)
    elif isinstance(left, Real):
        left = float(left)
    if isinstance(right, Integral):
        right = int(right)
    elif isinstance(right, Real):
        right = float(right)
    return bool(left == right)


def _assert_roundtrip(
    expected: BIASubmissionMetadata, actual: BIASubmissionMetadata, base: Path
) -> None:
    expected_objects = {
        e.id: e.model_dump(by_alias=True, mode="json")
        for e in expected.metadata.get_objects()
    }
    actual_objects = {
        e.id: e.model_dump(by_alias=True, mode="json")
        for e in actual.metadata.get_objects()
    }
    if expected_objects != actual_objects:
        raise ValueError("Metadata objects changed during serialize/reparse")
    if expected.file_list.ro_crate_id != actual.file_list.ro_crate_id:
        raise ValueError("File-list identity changed during serialize/reparse")
    expected_schema = {
        k: v.model_dump(by_alias=True, mode="json")
        for k, v in expected.file_list.schema.items()
    }
    actual_schema = {
        k: v.model_dump(by_alias=True, mode="json")
        for k, v in actual.file_list.schema.items()
    }
    if expected_schema != actual_schema:
        raise ValueError("File-list schema changed during serialize/reparse")
    # TSV does not store pandas index labels or dtypes. Compare shape and
    # ordered column IDs here, then exact logical cell values below.
    if (
        expected.file_list.data.shape != actual.file_list.data.shape
        or not expected.file_list.data.columns.equals(actual.file_list.data.columns)
    ):
        raise ValueError("File-list values changed during serialize/reparse")
    for expected_row, actual_row in zip(
        expected.file_list.data.itertuples(index=False, name=None),
        actual.file_list.data.itertuples(index=False, name=None),
        strict=True,
    ):
        if any(
            not _same_value(a, b) for a, b in zip(expected_row, actual_row, strict=True)
        ):
            raise ValueError("File-list values changed during serialize/reparse")
    if not isomorphic(metadata_graph(expected, base), metadata_graph(actual, base)):
        raise ValueError("JSON-LD graph meaning changed during serialize/reparse")


def _publish_pair(staging: Path, manifest: Path, destination: Path) -> None:
    # Exclusive directory creation: an existing directory, file, or symlink is
    # an error. Trusted, single-writer parent directory is a precondition.
    destination.mkdir(exist_ok=False)
    try:
        for relative in (manifest, Path(_METADATA)):
            output = destination / relative
            output.parent.mkdir(parents=True, exist_ok=True)
            with (staging / relative).open("rb") as src, output.open("xb") as dst:
                shutil.copyfileobj(src, dst)
    except BaseException as error:
        try:
            shutil.rmtree(destination)
        except OSError as cleanup_error:
            error.add_note(
                f"Could not remove incomplete output {destination}: {cleanup_error}"
            )
        raise


def write_submission(submission: BIASubmissionMetadata, destination: Path) -> Path:
    """Reparse an editor-owned snapshot and publish only a lossless result.

    Validation can load remote resources. The destination parent must be trusted;
    existing destinations and paths within the source crate are rejected.
    """
    destination = destination.absolute()
    if destination.exists() or destination.is_symlink():
        raise FileExistsError(destination)
    source = submission.metadata.get_base_path().resolve()
    if destination.resolve().is_relative_to(source):
        raise ValueError("Output must not modify the source crate tree")
    if not destination.parent.is_dir():
        raise FileNotFoundError(destination.parent)
    _manifest_relative_path(submission)
    # Import lazily, but never substitute a stub or omit the profile validator.
    from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser

    with TemporaryDirectory(prefix=".bia-edit-", dir=destination.parent) as directory:
        staging = Path(directory)
        manifest = _serialize_pair(submission, staging)
        parser = ROCrateParser(staging)
        parser.parse()
        reparsed = parser.result
        _assert_roundtrip(submission, reparsed, destination)
        _publish_pair(staging, manifest, destination)
    return destination
