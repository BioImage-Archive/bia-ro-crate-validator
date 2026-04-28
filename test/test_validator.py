import logging
from pathlib import Path

import pytest
import pytest_check as check
from cli import bia_ro_crate
from typer.testing import CliRunner

runner = CliRunner()


def get_test_ro_crate_path(accession_id, test_folder="validator") -> Path:
    return Path(__file__).parent / test_folder / "input_ro_crate" / accession_id


@pytest.mark.parametrize(
    "accession_id,expected_result,messages",
    [
        (
            "test_redefined_context",
            1,
            [
                (
                    "At title",
                    "Term has been remapped in context",
                ),
            ],
        ),
        (
            "test_duplicate_entity_id",
            1,
            [
                (
                    "At ro-crate object with @id: https://orcid.org/9999-0001-2222-3333",
                    "Found more than one object with @id",
                ),
            ],
        ),
        (
            "test_invalid_objects",
            1,
            [
                (
                    "At ro-crate object with @id: ./",
                    "is not a valid IRI",
                ),
                (
                    "At ro-crate object with @id: ID with invalid characters such as: ^ %ZZ",
                    "is not a valid IRI",
                ),
                (
                    "At ro-crate object with @id: #dataset",
                    "Input should be a valid dictionary or instance of ObjectReference",
                ),
                (
                    "At ro-crate object with @id: #object_with_mixed_types",
                    "@type of object does not contain exactly 1 BIA classes.",
                ),
                (
                    "At ro-crate object with @id: #object_no_expected_types",
                    "@type of object does not contain exactly 1 BIA classes.",
                ),
            ],
        ),
        (
            "test_id_reference_mismatch",
            1,
            [
                ("Found undefined references", "#non_existant_dataset"),
            ],
        ),
        (
            "test_file_list_missing_path_column",
            1,
            [
                (
                    "At file list file_list.tsv and TableSchema #ts0",
                    "Missing column with required property: http://bia/filePath",
                ),
            ],
        ),
        (
            "test_file_list_roc_id_reference_mismatch",
            1,
            [
                (
                    "In file list, at row: file_a.txt",
                    "#missing_dataset does not exist in ro-crate-metadata.json",
                ),
            ],
        ),
        (
            "test_file_list_self_reference_mismatch",
            1,
            [
                (
                    "In file list, at row: processed_image",
                    "Reference 'missing_input_image' not found in file list.",
                ),
                (
                    "In file list, at row: processed_image",
                    "Reference 'input_file' has no rdf:type, expected 'http://bia/Image'",
                ),
            ],
        ),
        (
            "test_file_list_duplicate_path",
            1,
            [
                (
                    "File list contains multiple references to the same file path.",
                ),
            ],
        ),
        (
            "test_minimal_valid_ro_crate",
            0,
            [],
        ),
    ],
)
def test_ro_crate_context_validation_error_messages(
    accession_id, expected_result, messages, caplog
):
    """
    See parametrisation above for test expectations.

    Structure of test paraters are tuples with:
    - Accesion id of the ro-crate to test
    - Expected result code (0 for no validation issues, 1 otherwise)
    - List of tuples of strings to check in each error message. E.g.

    [
        (
            "At ro-crate object with @id: data2/",
            "@type of object does not contain any BIA classes.",
        ),
        (
            "At ro-crate object with @id: data2/groupedImage/",
            "@type of object contains multiple BIA classes",
        ),
    ]
    Would result in a check that the validator returned 2 messages, and that each message contained all (2) expected substrings
    """

    caplog.set_level(logging.ERROR)

    crate_path = get_test_ro_crate_path(accession_id)

    arguments = ["validate", str(crate_path)]
    result = runner.invoke(bia_ro_crate, arguments)
    assert result.exit_code == expected_result

    captured_messages = [
        (record.levelname, record.message) for record in caplog.records
    ]

    assert len(messages) == len(captured_messages)

    # check that no duplicate messages were created
    unique_error_messages = set(
        severity_message[1] for severity_message in captured_messages
    )
    assert len(unique_error_messages) == len(messages)

    for message_position, captured_message in enumerate(captured_messages):
        severity, error_message = captured_message
        for expected_message_snippet in messages[message_position]:
            check.is_in(expected_message_snippet, error_message)
