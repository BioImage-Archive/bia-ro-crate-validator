import json
import shutil
from pathlib import Path

import pytest
from rdflib import RDF, Graph, URIRef

from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser
from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.core.validation.severity import Severity


@pytest.mark.parametrize(
    "predicates", [(RDF.first,), (RDF.rest,), (RDF.first, RDF.rest)]
)
def test_ambiguous_collections_stop_before_profile_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, predicates: tuple[URIRef, ...]
) -> None:
    shutil.copytree(
        get_test_ro_crate_path("test_minimal_valid_ro_crate"),
        tmp_path,
        dirs_exist_ok=True,
    )
    path = tmp_path / "ro-crate-metadata.json"
    metadata = json.loads(path.read_text(encoding="utf-8"))
    metadata["@graph"].append(
        {
            "@id": "#list",
            **{
                str(predicate): [{"@id": "./"}, {"@id": "file_list.tsv"}]
                for predicate in reversed(predicates)
            },
        }
    )
    path.write_text(json.dumps(metadata), encoding="utf-8")

    def unexpected_profile_validation(*args):
        pytest.fail("An ambiguous collection reached profile validation")

    monkeypatch.setattr(
        JSONLDMetadataParser, "_base_ro_crate_validation", unexpected_profile_validation
    )
    parser = ROCrateParser(tmp_path)
    with pytest.raises(ExceptionGroup, match="Validation failed"):
        parser.parse()
    assert [
        issue.message for issue in parser.issues if issue.severity is Severity.ERROR
    ] == [
        f"Ambiguous RDF collection: multiple values for {predicate}."
        for predicate in predicates
    ]


@pytest.mark.parametrize("predicate", [RDF.first, RDF.rest])
def test_repeated_identical_collection_arcs_are_allowed(
    tmp_path: Path, predicate: URIRef
) -> None:
    graph = Graph()
    triple = (URIRef("urn:cell"), predicate, URIRef("urn:value"))
    graph.add(triple)
    graph.add(triple)
    parser = JSONLDMetadataParser(tmp_path)
    parser._rdf_collection_validation(graph)
    assert not parser.issues


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
