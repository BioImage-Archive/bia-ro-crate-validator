"""Regression tests for the Python checker and its Java/OWLAPI/HermiT worker.

The bundled ontology itself is checked in test_ontology.py.
"""

import hashlib
import importlib.util
import io
import subprocess
import sys
from pathlib import Path

import pytest
from rdflib import Graph, URIRef
from rdflib.namespace import OWL, RDF

ROOT = Path(__file__).resolve().parents[1]
CHECK = ROOT / "scripts/ontology/check_ontology.py"
PREFIXES = """
@prefix : <urn:reasoning-test:> .
@prefix owl: <http://www.w3.org/2002/07/owl#> .
@prefix rdfs: <http://www.w3.org/2000/01/rdf-schema#> .
@prefix rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#> .
@prefix xsd: <http://www.w3.org/2001/XMLSchema#> .
:ontology a owl:Ontology .
:A a owl:Class .
:B a owl:Class .
"""


def run_check(*arguments):
    return subprocess.run(
        [sys.executable, str(CHECK), *map(str, arguments)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        timeout=150,
    )


def prepare_input(checker, path):
    inputs = {
        p: checker.read_regular_file(p) for p in (path.absolute(), checker.DECLARATIONS)
    }
    return checker.reasoning_input(path, inputs)


@pytest.mark.parametrize(
    ("axioms", "error"),
    [
        pytest.param(
            ":p a owl:ObjectProperty . :A rdfs:subClassOf [a owl:Restriction; "
            "owl:onProperty :p; owl:someValuesFrom :B] . "
            ":individual a owl:NamedIndividual, :A .",
            None,
            id="consistent",
        ),
        pytest.param(
            ":A owl:disjointWith :B . :individual a owl:NamedIndividual, :A, :B .",
            "inconsistent",
            id="inconsistent",
        ),
        pytest.param(
            ":A rdfs:subClassOf :B ; owl:disjointWith :B .",
            "unsatisfiable",
            id="unsatisfiable-class",
        ),
        pytest.param(
            ":A owl:subClassOf :B .", "could not be parsed", id="unparsed-triple"
        ),
        pytest.param(
            "<http://org.semanticweb.owlapi/error#Error1> a owl:Class . "
            ":A rdfs:subClassOf [a owl:Restriction; owl:someValuesFrom :B] .",
            "owl parsing error",
            id="parser-error-class-cannot-hide-malformed-input",
        ),
        pytest.param(
            ":A rdfs:subClassOf <urn:external:Missing> .",
            "profile violations",
            id="undeclared-external-term",
        ),
        pytest.param(
            ":property a owl:DatatypeProperty, owl:InverseFunctionalProperty .",
            "profile violations",
            id="inverse-functional-data-property",
        ),
        pytest.param(
            ":property a owl:DatatypeProperty ; rdfs:range xsd:integer . "
            ':individual a owl:NamedIndividual ; :property "not an integer" .',
            "inconsistent",
            id="datatype-clash",
        ),
        pytest.param(
            ":property a owl:DatatypeProperty ; rdfs:range xsd:boolean . "
            ':individual a owl:NamedIndividual ; :property "not-a-boolean"^^xsd:boolean .',
            "not a valid value",
            id="invalid-boolean-lexical-form",
        ),
    ],
)
def test_checker_detects_reasoning_and_conversion_failures(tmp_path, axioms, error):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES + axioms, encoding="utf-8")
    result = run_check("--input", ontology)
    if error is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert error in (result.stdout + result.stderr).lower()


@pytest.mark.parametrize(
    ("axioms", "error"),
    [
        pytest.param(
            ":p a owl:ObjectProperty . :A rdfs:subClassOf [a owl:Restriction; "
            "owl:onProperty :p; owl:someValuesFrom :A,:B] .",
            "requires one value",
            id="ambiguous-restriction-filler",
        ),
        pytest.param(
            ":p a owl:ObjectProperty . :A rdfs:subClassOf [a owl:Restriction; "
            "owl:onProperty :p; owl:someValuesFrom :A; owl:allValuesFrom :B] .",
            "one restriction operator",
            id="ambiguous-restriction-operator",
        ),
        pytest.param(
            ":A owl:equivalentClass [a owl:Class; "
            "owl:unionOf [rdf:first :A; rdf:rest [rdf:first :B]]] .",
            "malformed rdf list",
            id="unterminated-list",
        ),
        pytest.param(
            ":A owl:equivalentClass [a owl:Class; owl:unionOf _:cycle] . "
            "_:cycle rdf:first :A; rdf:rest _:cycle .",
            "malformed rdf list",
            id="cyclic-list",
        ),
        pytest.param(
            ":p a owl:ObjectProperty . :A rdfs:subClassOf ["
            'owl:onProperty :p; owl:hasSelf "false"^^xsd:boolean] .',
            "hasself requires boolean true",
            id="false-self-restriction",
        ),
        pytest.param(
            ":p a owl:ObjectProperty, owl:FunctionalProperty . "
            ":individual a owl:NamedIndividual, :A . "
            ":A rdfs:subClassOf [a owl:Restriction; owl:onProperty :p; "
            'owl:minCardinality "2147483648"^^xsd:nonNegativeInteger] .',
            "cardinality exceeds owlapi",
            id="cardinality-engine-overflow",
        ),
        pytest.param(
            ":ontology owl:imports <https://example.invalid/not-pinned> .",
            "imports require a pinned local import policy",
            id="uncontrolled-import",
        ),
    ],
)
def test_malformed_rdf_is_rejected_before_java(checker, tmp_path, axioms, error):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES + axioms, encoding="utf-8")
    with pytest.raises(ValueError, match=f"(?i){error}"):
        prepare_input(checker, ontology)


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("ontology_check", CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "source",
    [
        pytest.param("", id="empty"),
        pytest.param(PREFIXES.split(":A a owl:Class .")[0], id="header-only"),
        pytest.param(PREFIXES + ":other a owl:Ontology .", id="multiple-ontologies"),
    ],
)
def test_empty_or_ambiguous_ontology_is_rejected(checker, tmp_path, source):
    path = tmp_path / "ontology.ttl"
    path.write_text(source, encoding="utf-8")
    with pytest.raises(
        ValueError, match="must declare exactly one|entity declarations"
    ):
        prepare_input(checker, path)


def test_rdf_checks_accept_shared_list_tails_and_supported_restrictions(checker):
    """Check syntax without making the solver materialise billions of witnesses."""
    graph = Graph().parse(
        data=PREFIXES + """
:A owl:unionOf _:first . :B owl:unionOf _:second .
_:first rdf:first :A; rdf:rest _:tail .
_:second rdf:first :B; rdf:rest _:tail .
_:tail rdf:first :A; rdf:rest rdf:nil .
:role a owl:ObjectProperty .
:A rdfs:subClassOf [a owl:Restriction; owl:onProperty :role;
    owl:maxCardinality "2147483647"^^xsd:nonNegativeInteger] .
""",
        format="turtle",
    )
    checker.check_rdf_structure(graph)


@pytest.mark.parametrize("newline", ["\n", "\r\n"], ids=["lf", "crlf"])
def test_java_input_preserves_lexical_forms_and_relative_iris(
    checker, tmp_path, newline
):
    path = tmp_path / "ontology.ttl"
    source = (
        PREFIXES + ':p a owl:DatatypeProperty . <individual> :p "01"^^xsd:integer .'
    )
    source_bytes = source.replace("\n", newline).encode("utf-8")
    path.write_bytes(source_bytes)
    prepared = prepare_input(checker, path)
    assert source_bytes in prepared.encode("utf-8")
    merged = Graph().parse(data=prepared, format="turtle")
    assert set(merged.subjects(URIRef("urn:reasoning-test:p"), None)) == {
        URIRef((tmp_path / "individual").as_uri())
    }


def test_external_declarations_keep_their_own_iri_base(checker, monkeypatch, tmp_path):
    source = tmp_path / "ontology.ttl"
    source.write_text(
        "@base <http://bia/> .\n"
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n"
        "<> a owl:Ontology . <Source> a owl:Class .\n"
    )
    support = tmp_path / "external.ttl"
    support.write_text(
        "@prefix owl: <http://www.w3.org/2002/07/owl#> .\n" "<External> a owl:Class .\n"
    )
    monkeypatch.setattr(checker, "DECLARATIONS", support)
    prepared = prepare_input(checker, source)
    merged = Graph().parse(data=prepared, format="turtle")
    assert set(merged.subjects(RDF.type, OWL.Class)) == {
        URIRef("http://bia/Source"),
        URIRef((tmp_path / "External").as_uri()),
    }


@pytest.mark.parametrize(
    "declarations",
    [
        pytest.param(
            "<http://bia/Invented> a <http://www.w3.org/2002/07/owl#Class> .",
            id="fabricated-bia-declaration",
        ),
        pytest.param(
            "<urn:external:A> <http://www.w3.org/2002/07/owl#disjointWith> <urn:external:B> .",
            id="external-logical-axiom",
        ),
    ],
)
def test_external_support_cannot_add_bia_terms_or_axioms(
    checker, monkeypatch, tmp_path, declarations
):
    path = tmp_path / "ontology.ttl"
    path.write_text(PREFIXES, encoding="utf-8")
    support = tmp_path / "external.ttl"
    support.write_text(declarations, encoding="utf-8")
    monkeypatch.setattr(checker, "DECLARATIONS", support)
    with pytest.raises(ValueError, match="only external declarations"):
        prepare_input(checker, path)


@pytest.mark.parametrize("cached", [False, True], ids=["download", "cached-tool"])
def test_unverified_tool_is_never_installed_or_reused(
    checker, monkeypatch, tmp_path, cached
):
    jar = tmp_path / "tools" / "robot.jar"
    monkeypatch.setattr(checker, "ROBOT_JAR", jar)
    if cached:
        jar.parent.mkdir()
        jar.write_bytes(b"changed tool")

    def download(*args, **kwargs):
        assert not cached, "A changed cached executable must fail without downloading"
        return io.BytesIO(b"changed tool")

    monkeypatch.setattr(checker.urllib.request, "urlopen", download)
    with pytest.raises(ValueError, match="checksum mismatch"):
        checker.install_robot()
    assert jar.exists() == cached
    if cached:
        assert jar.read_bytes() == b"changed tool"
    else:
        assert list(jar.parent.iterdir()) == []


@pytest.mark.parametrize("times_out", [False, True], ids=["missing-output", "timeout"])
def test_incomplete_java_run_cannot_pass(
    checker, monkeypatch, tmp_path, capsys, times_out
):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES, encoding="utf-8")
    reports = tmp_path / "reports"
    monkeypatch.setattr(checker, "ARTIFACTS", reports)

    def incomplete(command, **kwargs):
        if times_out:
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(checker.subprocess, "run", incomplete)
    error = subprocess.TimeoutExpired if times_out else RuntimeError
    with pytest.raises(error, match=None if times_out else "without reason.txt"):
        checker.check_ontology(ontology)
    assert "named-class satisfiability passed" not in capsys.readouterr().out


def test_java_uses_captured_inputs(checker, monkeypatch, tmp_path):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES, encoding="utf-8")
    worker = tmp_path / "CheckOntology.java"
    worker.write_bytes(checker.JAVA_CHECK.read_bytes())
    monkeypatch.setattr(checker, "JAVA_CHECK", worker)
    reports = tmp_path / "reports"
    monkeypatch.setattr(checker, "ARTIFACTS", reports)
    run = checker.subprocess.run

    def change_originals(command, **kwargs):
        ontology.write_text("invalid Turtle", encoding="utf-8")
        worker.write_text("invalid Java", encoding="utf-8")
        return run(command, **kwargs)

    monkeypatch.setattr(checker.subprocess, "run", change_originals)
    checker.check_ontology(ontology)
    output = next(reports.iterdir())
    assert (output / "reason.txt").is_file()
    assert (output / "source.ttl").read_text() == PREFIXES
    manifest = (output / "inputs.sha256").read_bytes()
    # Windows-produced manifests must also be checkable by Unix tools.
    assert b"\r" not in manifest
    hashes = {}
    for line in manifest.decode("utf-8").splitlines():
        digest, name = line.split("  ", 1)
        hashes[name] = digest
    assert hashes == {
        name: hashlib.sha256((output / name).read_bytes()).hexdigest()
        for name in (
            "source.ttl",
            "external-declarations.ttl",
            "CheckOntology.java",
            "input.ttl",
        )
    }


def test_non_file_and_oversized_inputs_are_rejected(checker, tmp_path):
    with pytest.raises(ValueError, match="regular file"):
        checker.read_regular_file(tmp_path)
    ontology = tmp_path / "oversized.ttl"
    ontology.write_bytes(b"12345")
    with pytest.raises(ValueError, match="exceeds"):
        checker.read_regular_file(ontology, limit=4)
