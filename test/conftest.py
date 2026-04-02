from pathlib import Path

import pytest
from rdflib.graph import Graph


@pytest.fixture(scope="session")
def bia_ontology():
    bia_ontology = Graph()
    bia_ontology.parse(
        str(
            Path(__file__).parents[1]
            / "bia_ro_crate"
            / "models"
            / "linked_data"
            / "bia_ontology.ttl"
        )
    )

    return bia_ontology


@pytest.fixture(scope="session")
def related_ontologies():
    rdf = Graph()
    rdf.parse("https://www.w3.org/1999/02/22-rdf-syntax-ns#")

    schema = Graph()
    schema.parse("https://schema.org/version/latest/schemaorg-current-http.ttl")

    dc = Graph()
    dc.parse(
        "https://www.dublincore.org/specifications/dublin-core/dcmi-terms/dublin_core_terms.ttl"
    )

    dwc = Graph()
    dwc.parse("http://rs.tdwg.org/dwc/terms.ttl")

    dwciri = Graph()
    dwciri.parse("http://rs.tdwg.org/dwc/iri.ttl")

    csvw = Graph()
    csvw.parse("http://www.w3.org/ns/csvw#")

    return schema + dc + rdf + csvw


@pytest.fixture()
def path_to_example_ro_crate(request: pytest.FixtureRequest) -> Path:
    return (
        Path(__file__).parents[1]
        / "models"
        / "mock_ro_crate"
        / request.param
    )
