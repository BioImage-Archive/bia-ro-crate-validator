import json
from datetime import date
from pathlib import Path

import pytest
from pydantic import ValidationError
from rdflib import Literal, URIRef

from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser
from bia_ro_crate.models import ro_crate_models as models
from bia_ro_crate.models.linked_data.ontology_terms import DUBLINCORE, SCHEMA
from bia_ro_crate.models.ro_crate_generator_utils import (
    generate_embeded_bia_context,
    generate_standard_bia_context,
)

FIXTURES = Path(__file__).parent / "validator" / "input_ro_crate"
STUDY = next(
    entity
    for entity in json.loads(
        (
            FIXTURES / "test_minimal_valid_ro_crate" / "ro-crate-metadata.json"
        ).read_text()
    )["@graph"]
    if entity["@id"] == "./"
)
PROTOCOLS = [
    models.Protocol,
    models.SpecimenImagingPreparationProtocol,
    models.ImageAcquisitionProtocol,
    models.AnnotationMethod,
    models.ImageAnalysisMethod,
    models.ImageCorrelationMethod,
]


def protocol(model, **fields):
    supplied = {
        "@id": "#protocol",
        "@type": str(model.get_model_type()),
        "name": "Protocol",
        "description": "Full procedure",
    }
    if model is models.ImageAcquisitionProtocol:
        supplied["imagingInstrumentDescription"] = "Microscope"
    return model.model_validate(supplied | fields)


def test_study_dates_keep_native_types_and_iso_json_without_changing_input():
    supplied = STUDY | {"datePublished": "2024-02-29", "dateModified": "2024-03-01"}
    before = json.loads(json.dumps(supplied))
    study = models.Study.model_validate(supplied)
    assert study.datePublished == date(2024, 2, 29)
    assert type(study.datePublished) is date
    assert study.dateModified == date(2024, 3, 1)
    assert type(study.dateModified) is date
    dumped = json.loads(study.model_dump_json(by_alias=True))
    assert dumped["datePublished"] == "2024-02-29"
    assert dumped["dateModified"] == "2024-03-01"
    assert supplied == before


@pytest.mark.parametrize("field", ["datePublished", "dateModified"])
@pytest.mark.parametrize("value", ["2023-02-29", "2024-02-29T01:00:00Z"])
def test_invalid_or_inexact_study_dates_are_not_silently_truncated(field, value):
    with pytest.raises(ValidationError) as error:
        models.Study.model_validate(STUDY | {field: value})
    assert error.value.errors()[0]["loc"] == (field,)


def test_publication_date_is_required_but_modification_date_is_optional():
    for fields in [STUDY, STUDY | {"dateModified": None}]:
        study = models.Study.model_validate(fields)
        assert study.dateModified is None
        assert study.model_dump(mode="json")["dateModified"] is None
        assert "dateModified" not in study.model_dump(exclude_none=True)
    for fields in [
        {key: value for key, value in STUDY.items() if key != "datePublished"},
        STUDY | {"datePublished": None},
    ]:
        with pytest.raises(ValidationError):
            models.Study.model_validate(fields)


@pytest.mark.parametrize("model", PROTOCOLS, ids=lambda model: model.__name__)
def test_protocol_abstract_is_optional_text_and_preserves_description_and_extensions(
    model,
):
    assert "abstract" in model.model_fields
    assert protocol(model).abstract is None
    assert protocol(model, abstract=None).abstract is None
    text = "Overview | μm\nA second line <literal>"
    item = protocol(model, abstract=text, customTerm={"preserved": True})
    assert item.abstract == text
    assert item.description == "Full procedure"
    assert item.model_dump()["customTerm"] == {"preserved": True}
    with pytest.raises(ValidationError):
        protocol(model, abstract={"unexpected": "object"})
    with pytest.raises(ValidationError):
        protocol(model, description=None)


def test_model_graphs_use_exact_predicates_and_literal_date_and_abstract_values(
    tmp_path,
):
    context = generate_standard_bia_context()
    study = models.Study.model_validate(STUDY | {"dateModified": "2024-02-29"})
    graph = study.to_graph(context, tmp_path)
    assert list(graph.objects(predicate=SCHEMA.dateModified)) == [Literal("2024-02-29")]
    assert list(graph.objects(predicate=SCHEMA.datePublished)) == [
        Literal(str(study.datePublished))
    ]
    item = protocol(models.AnnotationMethod, abstract="Summary | μm")
    graph = item.to_graph(context, tmp_path)
    assert list(graph.objects(predicate=DUBLINCORE.abstract)) == [
        Literal("Summary | μm")
    ]
    assert not list(graph.objects(predicate=URIRef("http://schema.org/abstract")))


def test_generated_packaged_and_fixture_contexts_contain_the_same_field_definitions():
    generated = json.loads(json.dumps(generate_embeded_bia_context()))
    packaged = (
        Path(models.__file__).parent / "linked_data" / "bia_ro_crate_context.jsonld"
    )
    assert json.loads(packaged.read_text()) == generated
    expected = {
        "dateModified": {"@id": "schema:dateModified"},
        "abstract": {"@id": "dc:abstract"},
    }
    for path in FIXTURES.glob("*/ro-crate-metadata.json"):
        context = json.loads(path.read_text())["@context"][1]
        for field, definition in expected.items():
            assert context[field] == definition, f"{path}: {field}"


def test_full_parser_retains_dates_and_protocol_summaries():
    parser = JSONLDMetadataParser(FIXTURES / "test_typical_ro_crate")
    parser.parse()
    metadata = parser.result
    study = metadata.get_object("./")
    assert type(study.datePublished) is date
    serialized = metadata.to_dict()
    root = next(entity for entity in serialized["@graph"] if entity["@id"] == "./")
    assert root["datePublished"] == str(study.datePublished)
    assert study.dateModified == date(2023, 9, 6)
    assert (
        metadata.get_object("#Annotation%20Method").abstract
        == "Cell boundary annotation."
    )
    assert metadata.get_object("#Imaging%20Method").abstract == "Microscopy"
    assert root["dateModified"] == "2023-09-06"
