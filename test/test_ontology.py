import gzip
import subprocess
import sys
from inspect import get_annotations
from io import BytesIO
from pathlib import Path
from urllib.request import urlopen

import pytest
import pytest_check as check
from rdflib import Namespace, URIRef
from rdflib.graph import Graph
from rdflib.namespace import OWL, RDF, RDFS, XSD

from bia_ro_crate.models.linked_data.ontology_terms import (
    BIA,
    CSVW,
    DARWINCORE,
    DARWINCOREIRI,
    DUBLINCORE,
    SCHEMA,
)


def local_bia_terms(ontology: Graph):
    return {
        term
        for term in ontology.subjects(unique=True)
        if isinstance(term, URIRef) and str(term).startswith("http://bia/")
    }


def test_bia_terms_have_sensible_type(bia_ontology: Graph):
    property_types = {OWL.ObjectProperty, OWL.DatatypeProperty, OWL.AnnotationProperty}
    for subject in local_bia_terms(bia_ontology):
        types = set(bia_ontology.objects(subject, RDF.type))
        kinds = {
            OWL.Class if kind == RDFS.Class else kind
            for kind in types
            & (property_types | {OWL.Ontology, OWL.Class, RDFS.Class, RDF.Property})
        }
        # A generic property declaration can accompany a specific OWL property.
        if kinds & property_types:
            kinds.discard(RDF.Property)
        assert len(kinds) == 1, subject


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
    for subject in local_bia_terms(bia_ontology):
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

    for name, annotation in get_annotations(BIA).items():
        if annotation is URIRef and not name.startswith("_"):
            term = BIA[name]
            check.is_in(term, bia_terms, msg=f"{term} not in BIA ontology")


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
def test_other_namespace_terms(
    python_terms: Namespace, ontology_url: str, schema_ontology_loader
):
    if python_terms is SCHEMA:
        ontology = schema_ontology_loader(ontology_url)
    else:
        ontology = Graph().parse(ontology_url)
    defined_terms = list(
        term for term in ontology.subjects(unique=True) if isinstance(term, URIRef)
    )

    for name, annotation in get_annotations(python_terms).items():
        if annotation is URIRef and not name.startswith("_"):
            term = python_terms[name]
            check.is_true(term in defined_terms, msg=f"{term} not in {ontology_url}")


@pytest.mark.parametrize("compressed", [False, True])
def test_schema_loader_accepts_plain_and_gzip_turtle(
    schema_ontology_loader, monkeypatch, compressed
):
    data = b"<Thing> a <http://www.w3.org/2002/07/owl#Class> ."
    if compressed:
        data = gzip.compress(data)
    monkeypatch.setattr("urllib.request.urlopen", lambda *args, **kwargs: BytesIO(data))
    graph = schema_ontology_loader("https://example.org/vocab/schema.ttl")
    assert set(graph) == {
        (URIRef("https://example.org/vocab/Thing"), RDF.type, OWL.Class)
    }


def test_bia_ontology_is_in_dl_consistent_and_coherent():
    """Check the bundled ontology; checker regressions live in test_check_ontology."""
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run(
        [sys.executable, str(root / "scripts/ontology/check_ontology.py")],
        cwd=root,
        capture_output=True,
        text=True,
        timeout=150,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_external_declarations_match_source_vocabularies(related_ontologies):
    """Check local OWL roles reference real classes/properties, without importing axioms."""
    root = Path(__file__).resolve().parents[1]
    declarations = Graph().parse(root / "test/ontology/external-declarations.ttl")
    iao_url = "https://purl.obolibrary.org/obo/iao.owl"
    with urlopen(iao_url, timeout=30) as response:
        iao = Graph().parse(data=response.read(), format="xml", publicID=iao_url)
    vocabulary = related_ontologies + iao
    classes = {OWL.Class, RDFS.Class}
    properties = {
        RDF.Property,
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        OWL.AnnotationProperty,
    }
    for term, predicate, kind in declarations:
        expected = classes if kind == OWL.Class else properties
        assert predicate == RDF.type and kind in classes | properties
        assert set(vocabulary.objects(term, RDF.type)) & expected, term
