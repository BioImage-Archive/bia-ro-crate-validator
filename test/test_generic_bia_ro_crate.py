from bia_ro_crate.core.parser.jsonld_metadata_parser import (
    JSONLDMetadataParser,
)
from rdflib import Graph
from pathlib import Path
import pytest_check as check


def test_parser_to_graph_equivalent():
    ro_crate = (
        Path(__file__).parent
        / "validator"
        / "input_ro_crate"
        / "test_typical_ro_crate"
    )

    parser = JSONLDMetadataParser(ro_crate)
    parser.parse()
    metadata = parser.result
    metadata_graph = metadata.to_graph()

    direct_graph = Graph()
    direct_graph.parse(
        ro_crate / "ro-crate-metadata.json",
        format="json-ld",
    )

    assert len(metadata_graph) == len(direct_graph)
    for statement in metadata_graph:
        direct_statement = list(direct_graph.triples(statement))
        check.equal(len(direct_statement), 1, msg=f"{statement}")
