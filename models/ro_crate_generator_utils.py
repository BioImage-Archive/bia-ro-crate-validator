import inspect

from models import ro_crate_models
from models.linked_data.ld_context.SimpleJSONLDContext import (
    SimpleJSONLDContext,
)
from models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel
from rdflib import URIRef


def get_standard_bia_context_prefixes() -> dict[str, str]:
    bia_context_prefixes = {
        "rdf": "http://www.w3.org/1999/02/22-rdf-syntax-ns#",
        "schema": "http://schema.org/",
        "dc": "http://purl.org/dc/terms/",
        "bia": "http://bia/",
        "csvw": "http://www.w3.org/ns/csvw#",
    }
    return bia_context_prefixes


def generate_standard_bia_context() -> SimpleJSONLDContext:

    class_map = get_all_ro_crate_classes()

    context = SimpleJSONLDContext(prefixes=get_standard_bia_context_prefixes())

    for ldclass in class_map.values():
        for field_term in ldclass.generate_field_context():
            context.add_term(field_term)

    return context


def get_all_ro_crate_classes() -> dict[URIRef, type[ROCrateModel]]:
    ro_crate_pydantic_models = {
        ro_crate_class.model_config["model_type"]: ro_crate_class
        for name, ro_crate_class in inspect.getmembers(
            ro_crate_models,
            lambda member: (
                inspect.isclass(member)
                and member.__module__ == "models.ro_crate_models"
                and issubclass(member, ROCrateModel)
            ),
        )
    }
    return ro_crate_pydantic_models
