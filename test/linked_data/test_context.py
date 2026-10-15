from typing import Annotated

import pytest
from pydantic import Field
from pyld import jsonld
from rdflib import Literal, URIRef

from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm
from bia_ro_crate.models.linked_data.ld_context.SimpleJSONLDContext import (
    SimpleJSONLDContext,
)
from bia_ro_crate.models.linked_data.pydantic_ld import FieldContext, ObjectReference
from bia_ro_crate.models.linked_data.pydantic_ld.LDModel import LDModel
from bia_ro_crate.models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel


@pytest.mark.parametrize("compacted", [False, True])
@pytest.mark.parametrize("reverse", [False, True])
def test_generated_context_matches_serialised_aliases_and_reference_forms(
    compacted, reverse
):
    class Record(LDModel):
        target: Annotated[
            str if compacted else ObjectReference,
            FieldContext(
                "urn:field:target",
                is_id_field=True,
                is_reverse_field=reverse,
                container="@set",
            ),
        ] = Field(serialization_alias="destination")

    value = "urn:target" if compacted else {"@id": "urn:target"}
    record = Record(target=value)
    context = SimpleJSONLDContext(
        terms=Record.generate_field_context(compacted, by_alias=True)
    )
    expanded = jsonld.expand(
        {"@context": context.to_dict(), **record.model_dump(by_alias=True)}
    )
    properties = {"urn:field:target": [{"@id": "urn:target"}]}
    assert expanded == [{"@reverse": properties} if reverse else properties]
    assert Record.generate_field_context()[0].field_name == "target"


@pytest.mark.parametrize("prefixes", [None, {}, {"ex": "urn:"}])
def test_standard_context_uses_the_aliases_written_by_ro_crate_models(
    monkeypatch, tmp_path, prefixes
):
    from bia_ro_crate.models import ro_crate_generator_utils as generator

    class Record(ROCrateModel):
        value: Annotated[str, FieldContext("urn:value")] = Field(
            serialization_alias="title"
        )
        model_config = {"model_type": URIRef("urn:Record")}

    monkeypatch.setattr(generator, "MODEL_REGISTRY", {URIRef("urn:Record"): Record})
    record = Record(**{"@id": "urn:one", "@type": "urn:Record", "value": "text"})
    context = generator.generate_standard_bia_context(prefixes)
    if prefixes is not None:
        assert context.prefixes == prefixes
    graph = record.to_graph(context, tmp_path)
    assert (URIRef("urn:one"), URIRef("urn:value"), Literal("text")) in graph


@pytest.mark.parametrize(
    "namespace",
    [
        "https://example.org/",
        "https://example.org/#",
        "https://example.org/ns",
        "urn:example:",
    ],
)
def test_prefix_compaction_preserves_actual_jsonld_expansion(namespace):
    iri = namespace + "value"
    term = ContextTerm(iri, "value")
    context = SimpleJSONLDContext(prefixes={"ex": namespace}, terms=[term])
    expanded = jsonld.expand({"@context": context.to_dict(), "value": "text"})
    assert expanded == [{iri: [{"@value": "text"}]}]


def test_most_specific_prefix_is_independent_of_insertion_order():
    term = ContextTerm("https://example.org/namespace/term", "value")
    prefixes = {"s": "https://example.org/", "longer": "https://example.org/namespace/"}
    for mapping in (prefixes, dict(reversed(prefixes.items()))):
        assert term.to_context_term_dict(mapping) == {"@id": "longer:term"}


def test_compaction_does_not_create_an_authority_or_use_an_invalid_prefix():
    term = ContextTerm("https://example.org/a", "value")
    assert term.to_context_term_dict({"ex": "https:"}) == {"@id": str(term.full_uri)}
    assert term.to_context_term_dict({"bad:name": "https://example.org/"}) == {
        "@id": str(term.full_uri)
    }


def test_named_properties_are_not_compacted_using_the_blank_node_marker():
    context = SimpleJSONLDContext(
        prefixes={"_": "urn:namespace:"},
        terms=[ContextTerm("urn:namespace:value", "value")],
    )
    assert jsonld.expand({"@context": context.to_dict(), "value": "text"}) == [
        {"urn:namespace:value": [{"@value": "text"}]}
    ]


@pytest.mark.parametrize(
    "define",
    [
        lambda context: context.add_type_container("@graph", True),
        lambda context: context.add_id_rename("@future"),
        lambda context: context.add_term(ContextTerm("urn:value", "@future")),
        lambda context: context.add_prefix("@base", "urn:namespace:"),
    ],
    ids=["type-alias", "id-alias", "property-term", "prefix"],
)
def test_context_definitions_cannot_override_reserved_keywords(define):
    context = SimpleJSONLDContext()
    with pytest.raises(ValueError, match="Reserved context term"):
        define(context)
    assert context.to_dict() == {}


def test_context_equality_includes_reference_reverse_and_container_semantics():
    same = [
        ContextTerm("urn:p", "p", type_mapping="@id", container="@set")
        for _ in range(2)
    ]
    assert same[0] == same[1] and hash(same[0]) == hash(same[1])
    equivalent = ContextTerm("urn:p", "p", type_mapping="@id", container=["@set"])
    assert same[0] == equivalent and hash(same[0]) == hash(equivalent)
    for other in (
        ContextTerm("urn:p", "p", container="@set"),
        ContextTerm("urn:p", "p", type_mapping="@id"),
        ContextTerm(
            "urn:p", "p", type_mapping="@id", container="@set", is_reverse=True
        ),
    ):
        assert same[0] != other


@pytest.mark.parametrize("alias", ["same", "", "@id"])
def test_invalid_serialisation_aliases_cannot_overwrite_terms(alias):
    class Record(LDModel):
        first: Annotated[str, FieldContext("urn:first")] = Field(
            serialization_alias=alias
        )
        second: Annotated[str, FieldContext("urn:second")] = Field(
            serialization_alias=alias
        )

    with pytest.raises(ValueError, match="conflicting context term"):
        Record.generate_field_context(by_alias=True)


@pytest.mark.parametrize("excluded", [False, True])
def test_unmapped_aliases_cannot_overwrite_mapped_values(excluded):
    class Record(LDModel):
        value: Annotated[str, FieldContext("urn:value")] = Field(
            serialization_alias="same"
        )
        other: str = Field(serialization_alias="same", exclude=excluded)

    record = Record(value="retained", other="overwritten")
    if not excluded:
        assert record.model_dump(by_alias=True) == {"same": "overwritten"}
        with pytest.raises(ValueError, match="conflicting context term"):
            Record.generate_field_context(by_alias=True)
    else:
        context = SimpleJSONLDContext(
            terms=Record.generate_field_context(by_alias=True)
        )
        assert jsonld.expand(
            {"@context": context.to_dict(), **record.model_dump(by_alias=True)}
        ) == [{"urn:value": [{"@value": "retained"}]}]


def test_excluded_mapped_fields_cannot_conflict_with_serialised_aliases():
    class Record(LDModel):
        hidden: Annotated[str, FieldContext("urn:hidden")] = Field(
            serialization_alias="value", exclude=True
        )
        visible: Annotated[str, FieldContext("urn:visible")] = Field(
            serialization_alias="value"
        )

    record = Record(hidden="hidden", visible="retained")
    context = SimpleJSONLDContext(terms=Record.generate_field_context(by_alias=True))
    assert jsonld.expand(
        {"@context": context.to_dict(), **record.model_dump(by_alias=True)}
    ) == [{"urn:visible": [{"@value": "retained"}]}]
    assert [term.field_name for term in Record.generate_field_context()] == ["visible"]


def test_parser_preserves_coercions_and_container_profiles(tmp_path):
    from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser

    source = {
        "@type": {"@container": "@set"},
        "author": {
            "@id": "http://schema.org/author",
            "@type": "@id",
            "@container": "@set",
        },
        "links": {"@id": "urn:links", "@type": "@id", "@container": ["@set", "@index"]},
    }
    data = {
        "@type": ["urn:Record"],
        "author": ["urn:author"],
        "links": {"group": "urn:target"},
    }
    parsed = JSONLDMetadataParser(tmp_path)._parse_context(source)
    assert jsonld.expand({"@context": parsed.to_dict(), **data}) == jsonld.expand(
        {"@context": source, **data}
    )
    term = parsed.terms["links"]
    detached = term.to_context_term_dict()
    detached["@container"].append("@graph")
    assert set(term.container) == {"@index", "@set"}


def test_term_definitions_are_immutable_and_detached_from_container_inputs():
    from dataclasses import FrozenInstanceError

    containers = ["@set"]
    term = ContextTerm("urn:p", "p", container=containers)
    terms = {term}
    containers.append("@index")
    assert term in terms and term.to_context_term_dict()["@container"] == ["@set"]
    with pytest.raises(FrozenInstanceError):
        term.type_mapping = "@id"


@pytest.mark.parametrize(
    ("container", "reverse"),
    [
        ("@bogus", False),
        (["@list", "@set"], False),
        ("@list", True),
    ],
)
def test_invalid_container_settings_are_rejected_before_document_generation(
    container, reverse
):
    class Record(LDModel):
        target: Annotated[
            str,
            FieldContext("urn:target", container=container, is_reverse_field=reverse),
        ]

    with pytest.raises(ValueError, match="Invalid JSON-LD container"):
        Record.generate_field_context()


@pytest.mark.parametrize(
    "source",
    [
        {"@language": "en", "label": "urn:label"},
        {"@base": None, "label": "urn:label"},
        {"label": {"@id": "urn:label", "@language": "en"}},
        {"label": {"@id": "urn:label", "@context": {"nested": "urn:nested"}}},
        {"label": None},
    ],
)
def test_parser_rejects_unrepresentable_contexts_instead_of_losing_meaning(
    tmp_path, source
):
    from bia_ro_crate.core.parser.jsonld_metadata_parser import JSONLDMetadataParser

    with pytest.raises(ExceptionGroup) as caught:
        JSONLDMetadataParser(tmp_path)._parse_context(source)
    assert any("Unsupported context" in str(error) for error in caught.value.exceptions)


def test_context_merge_preserves_keyword_settings_and_rejects_conflicts():
    first = SimpleJSONLDContext(
        terms=[ContextTerm("urn:link", "link", type_mapping="@id")],
        force_type_container=True,
    )
    second = SimpleJSONLDContext(renamed_id_key="identifier")
    merged = first.merge(second)
    document = {
        "identifier": "urn:subject",
        "@type": ["urn:Record"],
        "link": "urn:target",
    }
    assert jsonld.expand({"@context": merged.to_dict(), **document}) == [
        {
            "@id": "urn:subject",
            "@type": ["urn:Record"],
            "urn:link": [{"@id": "urn:target"}],
        }
    ]
    exported = merged.to_dict()
    exported["@type"]["@container"] = "@list"
    assert first.to_dict()["@type"]["@container"] == "@set"
    conflict = SimpleJSONLDContext(terms=[ContextTerm("urn:other", "link")])
    with pytest.raises(ValueError, match="Context definition conflict"):
        first.merge(conflict)
    with pytest.raises(ValueError, match="Context definition conflict"):
        SimpleJSONLDContext(
            terms=[ContextTerm("urn:first", "same"), ContextTerm("urn:second", "same")]
        )
    same_prefix = SimpleJSONLDContext(prefixes={"ex": "urn:"}).merge(
        SimpleJSONLDContext(prefixes={"ex": URIRef("urn:")})
    )
    assert same_prefix.prefixes == {"ex": "urn:"}
