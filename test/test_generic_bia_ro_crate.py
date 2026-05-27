from bia_ro_crate.core.parser.jsonld_metadata_parser import (
    JSONLDMetadataParser,
)
from bia_ro_crate.models.ro_crate_generator_utils import generate_standard_bia_context
from bia_ro_crate.models.linked_data.ld_context.SimpleJSONLDContext import SimpleJSONLDContext
from rdflib import Graph
from pathlib import Path
import pytest_check as check
import pyld
import json
import requests
from typing import DefaultDict

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


def test_ro_crate_round_trippable():
    ro_crate = (
        Path(__file__).parent
        / "validator"
        / "input_ro_crate"
        / "test_typical_ro_crate"
    )

    with open(ro_crate / "ro-crate-metadata.json", 'r') as f:
        ro_crate_json = json.load(f)


    def strip_nulls_and_empty_lists(obj):
        """
        remove fields with null values or empty lists so JSON-LD compaction/expansion 
        round-tripping ignores missing entries
        """
        if isinstance(obj, dict):
            new = {}
            for k, v in obj.items():
                if v is None:
                    continue
                if isinstance(v, list) and len(v) == 0:
                    continue
                new_val = strip_nulls_and_empty_lists(v)
                new[k] = new_val
            return new
        elif isinstance(obj, list):
            return [strip_nulls_and_empty_lists(v) for v in obj if v is not None and not (isinstance(v, list) and len(v) == 0)]
        else:
            return obj

    ro_crate_json = strip_nulls_and_empty_lists(ro_crate_json)
    context = ro_crate_json["@context"]

    expanded = pyld.jsonld.expand(ro_crate_json)
    re_compacted = pyld.jsonld.compact(expanded, ctx=context, )

    assert isinstance(re_compacted, dict)
        
    def sort_value(val):
        if isinstance(val, list):
            return sorted([sort_value(v) for v in val], key=lambda x: json.dumps(x, sort_keys=True))
        elif isinstance(val, dict):
            return {k: sort_value(v) for k, v in val.items()}
        else:
            return val

    def sort_object(obj):
        return {k: sort_value(v) for k, v in obj.items()}

    def sort_graph(graph):
        """
        Sort everything inside the json-ld for test input and output to make the comparison easier.
        None of the fields should be @list fields, so order does not matter.
        """
        return sorted(
                    [json.dumps(sort_object(obj), sort_keys=True) for obj in graph]
                )

    orig_graph = ro_crate_json.get("@graph", [])
    re_compacted_graph = re_compacted.get("@graph", [])

    orig_objects = sort_graph(orig_graph)
    re_compacted_objects = sort_graph(re_compacted_graph)

    assert re_compacted_objects == orig_objects, "@graph objects do not match by keys/values"


def test_ro_crate_context_does_not_duplicate_term_labels():
    json_ld_context = generate_standard_bia_context()
    prefixless_context = SimpleJSONLDContext(terms=json_ld_context.terms.values())
    standard_context = prefixless_context.to_dict()

    ro_crate_context = json.loads(requests.get("https://w3id.org/ro/crate/1.1/context").content).get("@context", {})

    inverse_map = DefaultDict(set)
    [inverse_map[str(term_map["@id"])].add(term_field_name) for term_field_name, term_map in standard_context.items()]
    [inverse_map[term_map].add(term_field_name) for term_field_name, term_map in ro_crate_context.items()]

    for term_field_name, term_map in standard_context.items():
        ro_crate_context_term = ro_crate_context.get(term_field_name, {})
        term_id = str(term_map.get("@id"))

        if ro_crate_context_term:
            check.assert_equal(term_id, ro_crate_context_term, msg=f"term_field_name remapped from {ro_crate_context_term} to {term_id}")

        field_labels = inverse_map.get(term_id,[])
        check.equal(len(field_labels), 1, msg=f"{term_id} has more than 1 label: {field_labels}")

    
        
        



        