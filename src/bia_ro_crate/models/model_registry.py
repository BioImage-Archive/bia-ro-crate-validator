from rdflib import URIRef

from bia_ro_crate.models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel

MODEL_REGISTRY: dict[URIRef, type[ROCrateModel]] = {}

def register_ro_crate_class(ro_crate_class :type[ROCrateModel]) -> type[ROCrateModel]:
    MODEL_REGISTRY[ro_crate_class.model_config["model_type"]] = ro_crate_class
    return ro_crate_class