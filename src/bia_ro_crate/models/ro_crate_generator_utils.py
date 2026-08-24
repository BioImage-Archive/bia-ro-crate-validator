
from rdflib import URIRef

from bia_ro_crate.models.linked_data.ld_context.SimpleJSONLDContext import (
    SimpleJSONLDContext,
)
from bia_ro_crate.models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel
from bia_ro_crate.models.model_registry import MODEL_REGISTRY


def get_standard_bia_context_prefixes() -> dict[str, str]:
    bia_context_prefixes = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "schema": "http://schema.org/",
        "dc": "http://purl.org/dc/terms/",
        "bia": "http://bia/",
        "csvw": "http://www.w3.org/ns/csvw#",
    }
    return bia_context_prefixes


def generate_standard_bia_context(prefixes: dict | None = None)-> SimpleJSONLDContext:
    class_map = get_all_ro_crate_classes()

    context = SimpleJSONLDContext(prefixes=get_standard_bia_context_prefixes(), force_type_container=True)

    for ldclass in class_map.values():
        for field_term in ldclass.generate_field_context():
            context.add_term(field_term)

    return context


def generate_embeded_bia_context(prefixes: dict | None = None) -> dict:
    bia_specific_context = generate_standard_bia_context(prefixes)
    context = {
        "@context": [
            "https://w3id.org/ro/crate/1.1/context",
            bia_specific_context.to_dict()
        ]
    }
    return context

   

def get_all_ro_crate_classes() -> dict[URIRef, type[ROCrateModel]]:
    return MODEL_REGISTRY
