import pytest
import pytest_check as check
from bia_ro_crate.models.linked_data.ontology_terms import (
    BIA,
    CSVW,
    DARWINCORE,
    DARWINCOREIRI,
    DUBLINCORE,
    SCHEMA,
)
from rdflib import Namespace, URIRef
from rdflib.graph import Graph
from rdflib.namespace import OWL, RDF, RDFS, XSD

# TODO: Add a full owl consistency check using an owl reasoner,
# Note our metaclasses have issues with the python version of owlready2, (to do with python class inheritance, rather than ontology)
# So may need to use a java reasoner (e.g. Pellet or Hermit)


def test_bia_terms_have_sensible_type(bia_ontology: Graph):

    # Check terms in our ontology are an instance of Class, Property, or Ontology, but not any two disjoint classes in this list
    for subject in bia_ontology.subjects(None, None):
        subject_types = list(bia_ontology.objects(subject, RDF.type))

        assert (
            (OWL.Ontology in subject_types)
            ^ (OWL.ObjectProperty in subject_types)
            ^ (OWL.DatatypeProperty in subject_types)
            ^ (OWL.AnnotationProperty in subject_types or RDFS.Class in subject_types)
            ^ (OWL.Class in subject_types or RDFS.Class in subject_types)
        )


def test_bia_properties_use_defined_terms(
    bia_ontology: Graph, related_ontologies: Graph
):

    combined_ontology = bia_ontology + related_ontologies

    all_classes = set(combined_ontology.subjects(RDF.type, OWL.Class)) | set(
        combined_ontology.subjects(RDF.type, RDFS.Class)
    )
    # We use IAO's information content entity (IAO_0000030) as the domain for some classes
    all_classes.add(URIRef("http://purl.obolibrary.org/obo/IAO_0000030"))

    all_properties = (
        set(combined_ontology.subjects(RDF.type, OWL.ObjectProperty))
        | set(combined_ontology.subjects(RDF.type, OWL.DatatypeProperty))
        | set(combined_ontology.subjects(RDF.type, OWL.AnnotationProperty))
        | set(combined_ontology.subjects(RDF.type, RDF.Property))
    )

    # check property domain and ranges are things that exist
    for subject in bia_ontology.subjects(RDF.type, OWL.ObjectProperty):
        domain = list(bia_ontology.objects(subject, RDFS.domain))
        range = list(bia_ontology.objects(subject, RDFS.range))

        for d in domain:
            assert d in all_classes

        for r in range:
            assert r in all_classes

        super_properties = set(bia_ontology.objects(subject, RDFS.subPropertyOf))

        if len(super_properties) > 0:
            for super_property in super_properties:
                assert super_property in all_properties

                assert OWL.DatatypeProperty not in set(
                    combined_ontology.objects(super_property, RDF.type)
                )

    for subject in bia_ontology.subjects(RDF.type, OWL.DatatypeProperty):
        domain = list(bia_ontology.objects(subject, RDFS.domain))
        range = list(bia_ontology.objects(subject, RDFS.range))

        for d in domain:
            assert d in all_classes

        # Note, other types might be valid, but I would be surprised if we used any more than these
        for r in range:
            assert r in [
                XSD.string,
                RDF.langString,
                XSD.integer,
                XSD.double,
                XSD.float,
                XSD.decimal,
                XSD.dateTime,
                XSD.date,
                URIRef("http://schema.org/URL"),
            ]

        super_properties = set(bia_ontology.objects(subject, RDFS.subPropertyOf))

        if len(super_properties) > 0:
            for super_property in super_properties:
                assert super_property in all_properties

                assert OWL.ObjectProperty not in set(
                    combined_ontology.objects(super_property, RDF.type)
                )


def test_bia_terms_have_label_and_comment(bia_ontology: Graph):
    for subject in bia_ontology.subjects(None, None):
        # Skip the ontology itself
        if subject == URIRef("http://bia/"):
            continue

        labels = set(bia_ontology.objects(subject, RDFS.label))
        comments = set(bia_ontology.objects(subject, RDFS.comment))

        assert len(labels) > 0
        assert len(comments) > 0


def test_bia_namespace_terms(bia_ontology: Graph):
    bia_terms = list(
        term for term in bia_ontology.subjects(unique=True) if isinstance(term, URIRef)
    )

    for attribute in dir(BIA):
        if not attribute.startswith("_") and isinstance(attribute, URIRef):
            check.is_in(attribute, bia_terms, msg=f"{attribute} not in BIA ontology")


@pytest.mark.parametrize(
    ("python_terms", "ontology_url"),
    (
        (SCHEMA, "https://schema.org/version/latest/schemaorg-current-http.ttl"),
        (DARWINCORE, "http://rs.tdwg.org/dwc/terms.ttl"),
        (DARWINCOREIRI, "http://rs.tdwg.org/dwc/iri.ttl"),
        (CSVW, "http://www.w3.org/ns/csvw#"),
        (
            DUBLINCORE,
            "https://www.dublincore.org/specifications/dublin-core/dcmi-terms/dublin_core_terms.ttl",
        ),
    ),
)
def test_other_namespace_terms(python_terms: Namespace, ontology_url: str):
    ontology = Graph()
    ontology.parse(ontology_url)
    defined_terms = list(
        term for term in ontology.subjects(unique=True) if isinstance(term, URIRef)
    )

    for attribute in dir(python_terms):
        if not attribute.startswith("_") and isinstance(attribute, URIRef):
            check.is_true(
                attribute in defined_terms, msg=f"{attribute} not in {ontology_url}"
            )
