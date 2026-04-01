import json
from pathlib import Path

from rdflib import Graph

BIA_ONTOLOGY_FILE_PATH = Path(__file__).parent / "bia_ontology.ttl"
BIA_CONTEXT_PATH = Path(__file__).parent / "bia_ro_crate_context.jsonld"


def load_bia_ontology() -> Graph:
    graph = Graph()
    graph.parse(BIA_ONTOLOGY_FILE_PATH)
    return graph


def load_bia_context() -> dict[str, dict[str, str | dict[str, str]]]:

    with open(BIA_CONTEXT_PATH, "r") as context_file:
        context = json.loads(context_file.read())

    return context
