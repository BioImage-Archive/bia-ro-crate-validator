import logging
from pathlib import Path

import pytest
import pytest_check as check
from pyld import jsonld
from typer.testing import CliRunner

from bia_ro_crate.cli import bia_ro_crate

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
                    "At accessionId",
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
                ("File list contains multiple references to the same file path.",),
            ],
        ),
        (
            "test_no_file_list",
            1,
            [("does not include", "file_list.tsv")],
        ),
        (
            "test_minimal_valid_ro_crate",
            0,
            [],
        ),
        (
            "test_typical_ro_crate",
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


def test_parser_preserves_coercions_and_container_profiles(tmp_path):
    from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser

    source = {
        "@type": {"@container": "@set"},
        "author": {
            "@id": "http://schema.org/author",
            "@type": "@id",
            "@container": "@set",
        },
        "links": {"@id": "urn:links", "@type": "@id", "@container": ["@set", "@index"]},
    }
    data = {
        "@type": ["urn:Record"],
        "author": ["urn:author"],
        "links": {"group": "urn:target"},
    }
    parsed = JSONLDMetadataParser(tmp_path)._parse_context(source)
    assert jsonld.expand({"@context": parsed.to_dict(), **data}) == jsonld.expand(
        {"@context": source, **data}
    )
    term = parsed.terms["links"]
    detached = term.to_context_term_dict()
    detached["@container"].append("@graph")
    assert set(term.container) == {"@index", "@set"}


@pytest.mark.parametrize(
    "source",
    [
        {"@language": "en", "label": "urn:label"},
        {"@base": None, "label": "urn:label"},
        {"label": {"@id": "urn:label", "@language": "en"}},
        {"label": {"@id": "urn:label", "@context": {"nested": "urn:nested"}}},
        {"label": None},
    ],
)
def test_parser_rejects_unrepresentable_contexts_instead_of_losing_meaning(
    tmp_path, source
):
    from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser

    with pytest.raises(ExceptionGroup) as caught:
        JSONLDMetadataParser(tmp_path)._parse_context(source)
    assert any("Unsupported context" in str(error) for error in caught.value.exceptions)


@pytest.mark.parametrize("settings", [{"@type": "@id"}, {"@container": "@list"}])
def test_parser_rejects_prefix_value_semantics_it_cannot_preserve(tmp_path, settings):
    from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser

    source = {"ex": {"@id": "urn:example:", "@prefix": True, **settings}}
    assert jsonld.expand({"@context": source, "ex": ["urn:target"]})
    with pytest.raises(ExceptionGroup) as caught:
        JSONLDMetadataParser(tmp_path)._parse_context(source)
    assert any("Unsupported context" in str(error) for error in caught.value.exceptions)


@pytest.mark.parametrize(
    "definition", [{"@id": "urn:replacement:", "@prefix": True}, "@type"]
)
def test_prefixes_and_keyword_aliases_cannot_remap_bia_properties(tmp_path, definition):
    from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser

    with pytest.raises(ExceptionGroup) as caught:
        JSONLDMetadataParser(tmp_path)._parse_context({"name": definition})
    assert any(
        "Term has been remapped" in str(error) for error in caught.value.exceptions
    )
