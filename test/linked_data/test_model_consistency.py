from datetime import date
from decimal import Decimal
from typing import Annotated, Any, Literal, TypeAliasType

import pytest
from pydantic import AnyUrl, BaseModel, ConfigDict, RootModel, create_model
from rdflib import Graph, Namespace
from rdflib.namespace import OWL

from bia_ro_crate.models.linked_data.pydantic_ld import (
    FieldContext,
    ObjectReference,
    OntologyValidationError,
)
from bia_ro_crate.models.linked_data.pydantic_ld.LDModel import LDModel

EX = Namespace("urn:model:")
PREFIXES = """
@prefix : <urn:model:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
"""


def ontology(axioms):
    return Graph().parse(data=PREFIXES + axioms, format="turtle")


def test_all_field_issues_are_reported_without_swallowing_programming_errors():
    class Record(LDModel):
        missing: Annotated[str, FieldContext(EX.missing)]
        wrong_term: Annotated[str, FieldContext(EX.Class)]
        number: Annotated[bool | str | None, FieldContext(EX.number)]

    graph = ontology(
        ":Class a owl:Class . :number a owl:DatatypeProperty; rdfs:range xsd:integer ."
    )
    before = set(graph)
    with pytest.raises(OntologyValidationError) as caught:
        Record.validate_ontology_field_consistency(graph)
    assert len(caught.value.issues) == 4
    for name in ("missing", "wrong_term", "number"):
        assert f"Record.{name}:" in str(caught.value)
    assert not Record.is_valid(graph)
    assert set(graph) == before
    with pytest.raises(TypeError):
        Record.is_valid(None)


@pytest.mark.parametrize(
    ("annotation", "range_iri", "valid"),
    [
        (list[int | None], "xsd:integer", True),
        (bool, "xsd:integer", False),
        (float, "xsd:integer", False),
        (int, "xsd:decimal", True),
        (Decimal, "xsd:decimal", True),
        (float, "xsd:decimal", False),
        (int, "xsd:double", False),
        (AnyUrl, "xsd:string", True),
        (date, "xsd:date", True),
        (str, "rdf:langString", True),
        (ObjectReference, "xsd:string", False),
        (Any, "xsd:string", False),
        (list, "xsd:string", False),
        (str, ":CustomDatatype", False),
    ],
)
def test_literal_value_kinds(annotation, range_iri, valid):
    class Record(LDModel):
        value: Annotated[annotation, FieldContext(EX.value)]

    graph = ontology(f":value a owl:DatatypeProperty; rdfs:range {range_iri} .")
    assert Record.is_valid(graph) is valid
    if annotation is AnyUrl:
        assert isinstance(
            Record(value="https://example.org").model_dump(mode="json")["value"], str
        )


def test_unions_and_inherited_fields_check_each_branch():
    class Parent(LDModel):
        value: Annotated[int | str, FieldContext(EX.value)]

    class Child(Parent):
        optional: Annotated[list[ObjectReference] | None, FieldContext(EX.link)] = None

    graph = ontology(
        ":value a owl:DatatypeProperty; rdfs:range xsd:integer . :link a owl:ObjectProperty ."
    )
    with pytest.raises(OntologyValidationError) as caught:
        Child.validate_ontology_field_consistency(graph)
    assert len(caught.value.issues) == 1
    assert "Child.value:" in caught.value.issues[0]


@pytest.mark.parametrize("reverse", [False, True])
def test_nested_models_respect_inherited_property_orientation(reverse):
    class Child(LDModel):
        model_config = ConfigDict(model_type=EX.Child)

    class Parent(LDModel):
        child: Annotated[list[Child], FieldContext(EX.link, is_reverse_field=reverse)]
        model_config = ConfigDict(model_type=EX.Parent)

    # A reversed inverse has the original orientation. Both inheritance and
    # equivalence must retain the domain/range constraints.
    inverse = ":inverse owl:inverseOf :parent ." if reverse else ""
    target = ":inverse" if reverse else ":parent"
    graph = ontology(f"""
:link a owl:ObjectProperty; rdfs:subPropertyOf :alias .
:alias owl:equivalentProperty {target} .
{inverse}
:parent a owl:ObjectProperty; rdfs:domain :Parent; rdfs:range :Expected .
:Child owl:disjointWith :Expected .
""")
    with pytest.raises(
        OntologyValidationError, match="Parent.child: inferred types are disjoint"
    ):
        Parent.validate_ontology_field_consistency(graph)
    graph.remove((EX.Child, OWL.disjointWith, EX.Expected))
    # Missing Child subClassOf Expected is not a contradiction.
    Parent.validate_ontology_field_consistency(graph)


def test_recursive_models_check_contextual_types_without_looping():
    class Node(LDModel):
        child: Annotated["Node | None", FieldContext(EX.child)] = None
        value: Annotated[str, FieldContext(EX.value)] = "value"
        model_config = ConfigDict(model_type=EX.Node)

    Node.model_rebuild()
    graph = ontology("""
:Node rdfs:subClassOf :Base .
:child a owl:ObjectProperty; rdfs:range :Incompatible .
:Base owl:disjointWith :Incompatible .
:value a owl:DatatypeProperty; rdfs:range xsd:string .
""")
    with pytest.raises(OntologyValidationError) as caught:
        Node.validate_ontology_field_consistency(graph)
    assert any(
        "Node.child:" in issue and "disjoint" in issue for issue in caught.value.issues
    )
    graph.remove((EX.Base, OWL.disjointWith, EX.Incompatible))
    assert Node.is_valid(graph)


def test_unmapped_nested_models_are_still_inspected():
    class Child(BaseModel):
        value: Annotated[str, FieldContext(EX.missing)]

    class Parent(LDModel):
        child: dict[str, list[Child]]

    with pytest.raises(OntologyValidationError, match=r"Parent.child\[\*\].value:"):
        Parent.validate_ontology_field_consistency(Graph())


def test_unresolved_model_annotations_have_an_actionable_diagnostic():
    Record = create_model("Record", __base__=LDModel, child=("MissingModel", ...))

    with pytest.raises(
        OntologyValidationError, match="Record: unresolved model annotation"
    ):
        Record.validate_ontology_field_consistency(Graph())


def test_scalar_root_models_are_not_assumed_to_be_node_objects():
    class Record(LDModel):
        child: Annotated[RootModel[str], FieldContext(EX.child)]

    with pytest.raises(OntologyValidationError, match="Record.child: RootModel"):
        Record.validate_ontology_field_consistency(
            ontology(":child a owl:ObjectProperty .")
        )


def test_inferred_domains_and_all_disjoint_classes():
    class Record(LDModel):
        first: Annotated[str | None, FieldContext(EX.first)] = None
        second: Annotated[str, FieldContext(EX.second)]

    graph = ontology("""
:first a owl:DatatypeProperty; rdfs:domain :Left .
:second a owl:DatatypeProperty; rdfs:domain :Right .
:Left owl:equivalentClass :Alias .
:Alias rdfs:subClassOf :Ancestor .
[] a owl:AllDisjointClasses; owl:members (:Ancestor :Right) .
""")
    with pytest.raises(OntologyValidationError, match="inferred types are disjoint"):
        Record.validate_ontology_field_consistency(graph)


@pytest.mark.parametrize(
    "axioms",
    [
        ":Thing rdfs:subClassOf owl:Nothing .",
        ":Thing owl:disjointWith :Thing .",
        ":Thing owl:equivalentClass [owl:unionOf (:Left :Right)] .",
        ":Thing owl:complementOf :Left .",
        "[] a owl:AllDisjointClasses; owl:members [rdf:first :Thing] .",
    ],
)
def test_impossible_or_unsupported_class_constraints_are_not_silently_accepted(axioms):
    class Record(LDModel):
        model_config = ConfigDict(model_type=EX.Thing)

    assert not Record.is_valid(ontology(axioms))


def test_reference_and_property_kind_mismatches():
    class Record(LDModel):
        scalar: Annotated[str, FieldContext(EX.object)]
        identifier: Annotated[int, FieldContext(EX.object, is_id_field=True)]
        reverse: Annotated[
            ObjectReference, FieldContext(EX.data, is_reverse_field=True)
        ]

    graph = ontology(":object a owl:ObjectProperty . :data a owl:DatatypeProperty .")
    with pytest.raises(OntologyValidationError) as caught:
        Record.validate_ontology_field_consistency(graph)
    message = str(caught.value)
    assert "Record.scalar:" in message and "object property requires" in message
    assert "Record.identifier: ID fields require" in message
    assert "Record.reverse: cannot reverse datatype" in message


def test_explicit_and_compacted_reference_forms():
    class Record(LDModel):
        explicit: Annotated[ObjectReference, FieldContext(EX.object)]
        compact: Annotated[str, FieldContext(EX.object, is_id_field=True)]

    assert Record.is_valid(ontology(":object a owl:ObjectProperty ."))


@pytest.mark.parametrize(
    "characteristic",
    ["TransitiveProperty", "SymmetricProperty", "InverseFunctionalProperty"],
)
def test_object_property_characteristics_cannot_accept_literal_fields(characteristic):
    class Record(LDModel):
        value: Annotated[str, FieldContext(EX.value)]

    with pytest.raises(OntologyValidationError, match="object property requires"):
        Record.validate_ontology_field_consistency(
            ontology(f":value a owl:{characteristic} .")
        )


def test_duplicate_context_metadata_is_not_ignored():
    class Record(LDModel):
        value: Annotated[str, FieldContext(EX.first), FieldContext(EX.second)]

    with pytest.raises(OntologyValidationError, match="multiple FieldContexts"):
        Record.validate_ontology_field_consistency(Graph())
    with pytest.raises(ValueError, match="multiple FieldContexts"):
        Record.generate_field_context()


def test_reference_subclasses_do_not_hide_their_own_declarations():
    class TypedReference(ObjectReference):
        extra: Annotated[str, FieldContext(EX.missing)]

    class Parent(LDModel):
        child: Annotated[TypedReference, FieldContext(EX.child)]

    with pytest.raises(OntologyValidationError, match="Parent.child.extra:"):
        Parent.validate_ontology_field_consistency(
            ontology(":child a owl:ObjectProperty .")
        )


def test_null_only_fields_do_not_infer_a_nonexistent_property_assertion():
    class Record(LDModel):
        absent: Annotated[Literal[None], FieldContext(EX.absent)] = None
        model_config = ConfigDict(model_type=EX.Record)

    graph = ontology(
        ":absent a owl:DatatypeProperty; rdfs:domain :Other . :Record owl:disjointWith :Other ."
    )
    assert Record.is_valid(graph)


def test_inverse_links_declare_node_properties_even_without_redundant_type_triples():
    class Record(LDModel):
        wrong: Annotated[str, FieldContext(EX.inverse)]

    with pytest.raises(OntologyValidationError, match="object property requires"):
        Record.validate_ontology_field_consistency(
            ontology(":original owl:inverseOf :inverse .")
        )


def test_local_models_and_missing_external_vocabulary_use_the_real_ontology(
    bia_ontology,
):
    from bia_ro_crate.models.ro_crate_models import (
        CreationProcess,
        Publication,
        Specimen,
    )

    for model in (CreationProcess, Specimen):
        report = model.ontology_consistency_report(bia_ontology)
        assert report.ok
        assert any(item.code == "REFERENCE_TARGET_UNCHECKED" for item in report.notices)
    # The bundled ontology does not define Schema.org name. Missing external
    # vocabulary must remain visible; no declarations are invented to hide it.
    report = Publication.ontology_consistency_report(bia_ontology)
    assert any(
        item.code == "MISSING_PROPERTY" and item.path == "Publication.name"
        for item in report.errors
    )


@pytest.mark.parametrize(
    ("annotation", "ranges", "valid"),
    [
        (float, "xsd:decimal, xsd:float", False),
        (float, "xsd:float, xsd:double", False),
        (str, "xsd:string, rdf:langString", False),
        (int, "xsd:positiveInteger, xsd:negativeInteger", False),
        (int, "xsd:negativeInteger, xsd:unsignedInt", False),
        (int, "xsd:byte, xsd:unsignedByte", True),
    ],
)
def test_conjunctive_datatype_ranges_require_a_nonempty_intersection(
    annotation, ranges, valid
):
    class Record(LDModel):
        value: Annotated[annotation, FieldContext(EX.value)]

    report = Record.ontology_consistency_report(
        ontology(f":value a owl:DatatypeProperty; rdfs:range {ranges} .")
    )
    assert report.ok is valid
    assert any(item.code == "DISJOINT_DATATYPES" for item in report.errors) is not valid


@pytest.mark.parametrize(
    ("declared", "axioms"),
    [
        ("relative", ""),
        ("urn:invalid space", ""),
        ("http://www.w3.org/2001/XMLSchema#string", ""),
        (EX.Literal, ":Literal a rdfs:Datatype ."),
        (EX.Record, ":Record owl:disjointWith owl:Thing ."),
        (EX.Record, ":Record owl:disjointWith rdfs:Resource ."),
    ],
)
def test_named_model_types_must_be_resource_classes(declared, axioms):
    class Record(LDModel):
        model_config = ConfigDict(model_type=declared)

    assert not Record.is_valid(ontology(axioms))


def test_node_ranges_cannot_be_custom_datatypes():
    class Record(LDModel):
        child: Annotated[ObjectReference, FieldContext(EX.child)]

    report = Record.ontology_consistency_report(
        ontology(
            ":child a owl:ObjectProperty; rdfs:range :Data . :Data a rdfs:Datatype ."
        )
    )
    assert not report.ok and any(
        "datatype range" in item.message for item in report.errors
    )


def test_range_declarations_establish_a_property_without_a_redundant_type():
    class Record(LDModel):
        value: Annotated[int, FieldContext(EX.value)]

    graph = ontology(":value rdfs:range xsd:integer .")
    assert Record.is_valid(graph)


def test_model_inspection_is_read_only_and_reports_coverage(monkeypatch):
    class Record(LDModel):
        pass

    def forbidden_rebuild(*args, **kwargs):
        pytest.fail("Inspection must not evaluate annotations or rebuild model schemas")

    monkeypatch.setattr(Record, "model_rebuild", forbidden_rebuild)
    report = Record.ontology_consistency_report(Graph())
    assert report.ok
    assert {item.code for item in report.notices} == {"NO_MAPPED_FIELDS"}


def test_worklist_deduplicates_shared_subgraphs_and_limits_incomplete_runs(monkeypatch):
    from bia_ro_crate.models.linked_data.pydantic_ld import model_consistency

    child = create_model("Leaf", __base__=LDModel)
    for depth in range(12):
        child = create_model(
            f"TreeDepth{depth}", __base__=LDModel, left=(child, ...), right=(child, ...)
        )
    monkeypatch.setattr(model_consistency, "MAX_MODEL_STATES", 13)
    assert child.ontology_consistency_report(Graph()).ok
    monkeypatch.setattr(model_consistency, "MAX_MODEL_STATES", 2)
    report = child.ontology_consistency_report(Graph())
    assert not report.ok and any(
        item.code == "MODEL_STATE_LIMIT" for item in report.errors
    )


def test_shared_child_is_checked_again_under_a_different_parent_range():
    class Child(LDModel):
        model_config = ConfigDict(model_type=EX.Child)

    class Parent(LDModel):
        good: Annotated[Child, FieldContext(EX.good)]
        bad: Annotated[Child, FieldContext(EX.bad)]

    graph = ontology(
        ":good a owl:ObjectProperty; rdfs:range :Child . :bad a owl:ObjectProperty; rdfs:range :Other . :Child owl:disjointWith :Other ."
    )
    report = Parent.ontology_consistency_report(graph)
    assert any(
        item.path == "Parent.bad" and "disjoint" in item.message
        for item in report.errors
    )


@pytest.mark.parametrize(
    "axioms",
    [
        ":value a owl:ObjectProperty; owl:propertyChainAxiom (:p :q) .",
        ":value a owl:ObjectProperty; rdfs:subPropertyOf [owl:inverseOf :p] .",
    ],
)
def test_unsupported_property_expressions_do_not_silently_pass(axioms):
    class Record(LDModel):
        value: Annotated[ObjectReference, FieldContext(EX.value)]

    report = Record.ontology_consistency_report(ontology(axioms))
    assert not report.ok
    assert any(item.code.startswith("UNSUPPORTED_PROPERTY") for item in report.errors)


def test_nested_lists_are_not_flattened_into_a_supported_list_annotation():
    class Record(LDModel):
        values: Annotated[list[list[str]], FieldContext(EX.values)]

    assert not Record.is_valid(ontology(":values a owl:DatatypeProperty ."))


@pytest.mark.parametrize("wrapper", [lambda t: t, lambda t: dict[str, list[t]]])
def test_unmapped_type_aliases_do_not_hide_nested_model_declarations(wrapper):
    class Child(LDModel):
        value: Annotated[str, FieldContext(EX.missing)]

    alias = TypeAliasType("ChildAlias", Child)
    parent = create_model("Parent", __base__=LDModel, child=(wrapper(alias), ...))
    report = parent.ontology_consistency_report(Graph())
    assert not report.ok
    assert any(
        item.code == "UNSUPPORTED_ANNOTATION" and item.path == "Parent.child"
        for item in report.errors
    )


@pytest.mark.parametrize("reverse", [False, True])
def test_symmetric_superproperties_constrain_both_ends(reverse):
    class Child(LDModel):
        model_config = ConfigDict(model_type=EX.Child)

    class Parent(LDModel):
        child: Annotated[Child, FieldContext(EX.link, is_reverse_field=reverse)]

    graph = ontology("""
:link a owl:ObjectProperty; rdfs:subPropertyOf :symmetric .
:symmetric a owl:SymmetricProperty; rdfs:domain :Parent .
:Child owl:disjointWith :Parent .
""")
    assert not Parent.is_valid(graph)
    graph.remove((EX.Child, OWL.disjointWith, EX.Parent))
    assert Parent.is_valid(graph)


@pytest.mark.parametrize("range_iri", ["xsd:string", "rdf:List"])
def test_list_containers_do_not_apply_head_ranges_to_items(range_iri):
    class Record(LDModel):
        values: Annotated[list[str], FieldContext(EX.values, container="@list")]

    report = Record.ontology_consistency_report(
        ontology(f":values a rdf:Property; rdfs:range {range_iri} .")
    )
    assert not report.ok
    assert {item.code for item in report.errors} == {"UNSUPPORTED_CONTAINER"}
