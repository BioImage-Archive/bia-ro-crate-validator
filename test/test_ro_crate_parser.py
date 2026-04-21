from pathlib import Path

import pytest

from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser


def get_test_ro_crate_path(accession_id: str, test_folder: str = "validator") -> Path:
    return Path(__file__).parent / test_folder / "input_ro_crate" / accession_id


def test_ro_crate_parser_accepts_metadata_entity_referenced_from_file_list() -> None:
    parser = ROCrateParser(
        get_test_ro_crate_path("test_file_list_metadata_reference_connects_entity")
    )

    parser.parse()
    parser.result

    whole_crate_messages = [
        issue.message
        for issue in parser.issues
        if "across ro-crate-metadata.json and file list references" in issue.message
    ]

    assert not any("#specimen_1" in message for message in whole_crate_messages)


def test_ro_crate_parser_rejects_missing_metadata_entity_referenced_from_file_list() -> None:
    parser = ROCrateParser(
        get_test_ro_crate_path("test_file_list_missing_metadata_reference")
    )

    with pytest.raises(ExceptionGroup):
        parser.parse()

    assert any(
        "#missing_specimen does not exist in ro-crate-metadata.json"
        in issue.message
        for issue in parser.issues
    )
