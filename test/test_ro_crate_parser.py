import json
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
from pyld import jsonld
from rdflib import URIRef

from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser
from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm
from bia_ro_crate.models.linked_data.ld_context.SimpleJSONLDContext import (
    SimpleJSONLDContext,
)
from bia_ro_crate.validator.validation import ValidationResponseMode, bia_roc_validation


def get_test_ro_crate_path(accession_id: str, test_folder: str = "validator") -> Path:
    return Path(__file__).parent / test_folder / "input_ro_crate" / accession_id


def test_parser_preserves_utf8_metadata_and_relative_references(tmp_path):
    directory = tmp_path / "crate"
    shutil.copytree(get_test_ro_crate_path("test_minimal_valid_ro_crate"), directory)
    path = directory / "ro-crate-metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    study = next(entity for entity in metadata["@graph"] if entity["@id"] == "./")
    study["name"] = "Microscopy μ — 细胞"
    path.write_text(json.dumps(metadata, ensure_ascii=False), encoding="utf-8")

    parser = ROCrateParser(directory)
    parser.parse()

    assert parser.result.metadata.get_object("./").name == study["name"]


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


def test_context_reconstruction_preserves_jsonld_expansion(tmp_path):
    context = {
        "@type": {"@container": "@set"},
        "Example": "https://example.org/Example",
        "name": {"@id": URIRef("http://schema.org/name")},
        "ex": {"@id": "https://example.org/base", "@prefix": True},
        "http": {"@id": "https://example.org/", "@prefix": True},
        "prefixed": "ex:value",
        "literal": {"@id": "https://example.org/literal", "@type": "@json"},
        "reference": {"@id": "https://example.org/reference", "@type": "@id"},
        "integer": {
            "@id": "https://example.org/integer",
            "@type": "http://www.w3.org/2001/XMLSchema#integer",
        },
        "unordered": {"@id": "https://example.org/unordered", "@container": "@set"},
        "ordered": {"@id": "https://example.org/ordered", "@container": "@list"},
        "indexed": {
            "@id": "https://example.org/indexed",
            "@container": ["@set", "@index"],
        },
        "reverse": {"@reverse": "https://example.org/reverse"},
    }
    entity = {
        "@id": "https://example.org/entity",
        "@type": ["Example", "ex:Type"],
        "prefixed": "retain",
        "name": "Retained name",
        "literal": {"nested": [1, 2]},
        "reference": "#target",
        "integer": 7,
        "unordered": ["a", "b"],
        "ordered": ["b", "a"],
        "indexed": {"first": "a", "second": "b"},
        "reverse": {"@id": "#target"},
    }
    parsed = JSONLDMetadataParser(tmp_path)._parse_context(context)
    assert parsed.resolve_iri("name") == URIRef("http://schema.org/name")
    assert parsed.resolve_iri("http://schema.org/name") == URIRef("http://schema.org/name")
    assert parsed.resolve_iri("ex:value") == URIRef("https://example.org/basevalue")
    assert parsed.resolve_iri("https://example.org/direct") == URIRef(
        "https://example.org/direct"
    )
    assert parsed.resolve_iri("undefined") is None
    assert parsed.to_dict()["@type"] == {"@container": "@set"}
    actual = jsonld.expand(
        {"@context": json.loads(json.dumps(parsed.to_dict())), "@graph": [entity]}
    )
    expected = jsonld.expand(
        json.loads(json.dumps({"@context": context, "@graph": [entity]}))
    )
    # PyLD's cache can retain RDFLib IRI strings; compare their JSON values.
    assert json.loads(json.dumps(actual)) == json.loads(json.dumps(expected))


@pytest.mark.parametrize(
    "context",
    [
        {"@language": "en"},
        {"@base": None},
        {"@propagate": False},
        {"disabled": None},
        {"ex": {"@id": "https://example.org/", "@prefix": True, "@type": "@id"}},
        {
            "value": {
                "@id": "https://example.org/value",
                "@context": {"nested": "https://example.org/nested"},
            }
        },
    ],
)
def test_unrepresentable_context_semantics_are_rejected(tmp_path, context):
    parser = JSONLDMetadataParser(tmp_path)
    with pytest.raises(ExceptionGroup):
        parser._parse_context(context)
    assert any("Unsupported context" in issue.message for issue in parser.issues)


@pytest.mark.parametrize(
    "definition",
    [
        {"@reverse": "http://schema.org/name"},
        "@id",
        {"@id": "https://example.org/", "@prefix": True},
    ],
)
def test_model_properties_cannot_be_remapped_by_any_declaration(tmp_path, definition):
    parser = JSONLDMetadataParser(tmp_path)
    with pytest.raises(ExceptionGroup):
        parser._parse_context({"name": definition})
    assert any("Term has been remapped" in issue.message for issue in parser.issues)


def test_unsupported_context_is_an_error_in_public_report_mode(tmp_path):
    source = tmp_path / "input"
    shutil.copytree(get_test_ro_crate_path("test_minimal_valid_ro_crate"), source)
    path = source / "ro-crate-metadata.json"
    data = json.loads(path.read_text())
    data["@context"].append({"@language": "en"})
    path.write_text(json.dumps(data))
    report = bia_roc_validation(source, ValidationResponseMode.report)
    assert report["highest_error_level"] == "ERROR"
    assert any(
        "Unsupported context" in issue["message"] for issue in report["issues"]["ERROR"]
    )


def test_context_term_equality_and_hashing_include_jsonld_semantics():
    uri = "https://example.org/value"
    plain = ContextTerm(uri, "value")
    typed = ContextTerm(uri, "value", type_mapping="@id")
    indexed = ContextTerm(uri, "value", container=["@set", "@index"])
    equivalent = ContextTerm(uri, "value", container=["@set", "@index"])
    assert plain != typed
    assert indexed == equivalent
    assert hash(indexed) == hash(equivalent)
    assert len({plain, typed, indexed, equivalent}) == 3


def test_context_merge_and_serialization_do_not_borrow_mutable_definitions():
    term = ContextTerm(
        "https://example.org/value", "value", container=["@set", "@index"]
    )
    original = SimpleJSONLDContext(
        prefixes={"ex": "https://example.org/"},
        terms=[term],
        force_type_container=True,
        renamed_id_key="identifier",
    )
    extra = SimpleJSONLDContext(terms=[ContextTerm("https://example.org/note", "note")])
    before = deepcopy(original.to_dict())
    merged = original.merge(extra)
    assert original.merge().to_dict() == before
    merged_before = deepcopy(merged.to_dict())
    entity = {
        "identifier": "https://example.org/entity",
        "@type": "ex:Type",
        "value": {"first": "retain"},
        "note": "Additional note",
    }
    assert jsonld.expand(
        {
            **entity,
            "@context": json.loads(json.dumps(merged_before)),
        }
    ) == jsonld.expand(
        {
            **entity,
            "@context": json.loads(json.dumps({**before, **extra.to_dict()})),
        }
    )
    serialized = merged.to_dict()
    serialized["@type"]["@container"] = "@list"
    serialized["value"]["@container"].append("@list")
    assert merged.to_dict() == merged_before
    standalone = term.to_context_term_dict()
    standalone["@container"].append("@list")
    assert original.to_dict() == before
    merged.terms["value"].container.append("@list")
    merged.terms["note"].type_mapping = "@id"
    assert original.to_dict() == before
    assert extra.terms["note"].type_mapping is None


@pytest.mark.parametrize(
    "incoming",
    [
        SimpleJSONLDContext(prefixes={"ex": "https://different.example/"}),
        SimpleJSONLDContext(
            terms=[
                ContextTerm("https://example.org/value", "value", type_mapping="@id")
            ]
        ),
        SimpleJSONLDContext(rename_type_key="identifier"),
        SimpleJSONLDContext(prefixes={"value": "https://example.org/"}),
    ],
)
def test_context_merge_conflicts_leave_both_inputs_unchanged(incoming):
    original = SimpleJSONLDContext(
        prefixes={"ex": "https://example.org/"},
        terms=[ContextTerm("https://example.org/value", "value")],
        renamed_id_key="identifier",
    )
    before, incoming_before = deepcopy(original.to_dict()), deepcopy(incoming.to_dict())
    with pytest.raises(ValueError, match="Context definition conflict"):
        original.merge(incoming)
    assert original.to_dict() == before
    assert incoming.to_dict() == incoming_before


def test_context_term_additions_are_atomic_and_detached():
    context = SimpleJSONLDContext(
        prefixes={"ex": "https://example.org/"}, renamed_id_key="identifier"
    )
    term = ContextTerm("https://example.org/value", "value", container="@set")
    context.add_terms([term, term])
    before = deepcopy(context.to_dict())
    term.container = "@list"
    assert context.to_dict() == before
    for conflict in [
        term,
        ContextTerm(term.full_uri, "ex"),
        ContextTerm(term.full_uri, "identifier"),
    ]:
        with pytest.raises(ValueError, match="Context definition conflict"):
            context.add_terms(
                [ContextTerm("https://example.org/note", "note"), conflict]
            )
        assert context.to_dict() == before
    with pytest.raises(ValueError, match="Context definition conflict"):
        context.add_terms(
            [
                ContextTerm("https://example.org/a", "duplicate"),
                ContextTerm("https://example.org/b", "duplicate"),
            ]
        )
    assert context.to_dict() == before
