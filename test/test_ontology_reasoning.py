"""Exercise real OWLAPI/HermiT acceptance and failure paths."""

import hashlib
import importlib.util
import io
import json
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


def read_report(result):
    line = next(
        line
        for line in result.stdout.splitlines()
        if line.startswith("Ontology reports: ")
    )
    return json.loads(
        (Path(line.removeprefix("Ontology reports: ")) / "report.json").read_text()
    )


def prepare_input(checker, path):
    inputs = {
        p: checker.read_regular_file(p) for p in (path.absolute(), checker.DECLARATIONS)
    }
    return checker.reasoning_input(path, inputs)


def test_bia_ontology_is_in_dl_consistent_and_coherent():
    result = run_check()
    assert result.returncode == 0, result.stdout + result.stderr
    assert read_report(result)["status"] == "PASS"


@pytest.mark.parametrize(
    ("axioms", "error"),
    [
        (":A rdfs:subClassOf :B . :individual a owl:NamedIndividual, :A .", None),
        (
            ":A owl:disjointWith :B . :individual a owl:NamedIndividual, :A, :B .",
            "inconsistent",
        ),
        (
            ":A rdfs:subClassOf :B ; owl:disjointWith :B .",
            "unsatisfiable",
        ),
        (":A owl:subClassOf :B .", "could not be parsed"),
        (
            "<http://org.semanticweb.owlapi/error#Error1> a owl:Class . "
            ":A rdfs:subClassOf [a owl:Restriction; owl:someValuesFrom :B] .",
            "profile failed",
        ),
        (
            ":p a owl:ObjectProperty . :A rdfs:subClassOf [a owl:Restriction; "
            "owl:onProperty :p; owl:someValuesFrom :A,:B] .",
            "requires one value",
        ),
        (
            ":p a owl:ObjectProperty . :A rdfs:subClassOf [a owl:Restriction; "
            "owl:onProperty :p; owl:someValuesFrom :A; owl:allValuesFrom :B] .",
            "one restriction operator",
        ),
        (
            ":A owl:equivalentClass [a owl:Class; "
            "owl:unionOf [rdf:first :A; rdf:rest [rdf:first :B]]] .",
            "malformed rdf list",
        ),
        (
            ":A owl:equivalentClass [a owl:Class; owl:unionOf _:cycle] . "
            "_:cycle rdf:first :A; rdf:rest _:cycle .",
            "malformed rdf list",
        ),
        (
            ":p a owl:DatatypeProperty . :q a owl:DatatypeProperty . "
            ":A owl:hasKey (:p), (:q) .",
            None,
        ),
        (
            ":p a owl:ObjectProperty . :A rdfs:subClassOf ["
            'owl:onProperty :p; owl:hasSelf "false"^^xsd:boolean] .',
            "hasself requires boolean true",
        ),
        (
            ":p a owl:ObjectProperty, owl:FunctionalProperty . "
            ":individual a owl:NamedIndividual, :A . "
            ":A rdfs:subClassOf [a owl:Restriction; owl:onProperty :p; "
            'owl:minCardinality "2147483648"^^xsd:nonNegativeInteger] .',
            "cardinality exceeds owlapi",
        ),
        (
            ":p a owl:ObjectProperty . :individual a owl:NamedIndividual, :A, :B . "
            ":A rdfs:subClassOf [a owl:Restriction; "
            'owl:onProperty :p; owl:hasSelf "true"^^xsd:boolean] . '
            ":B rdfs:subClassOf [a owl:Restriction; "
            'owl:onProperty :p; owl:hasSelf "1"^^xsd:boolean] .',
            None,
        ),
        (
            ":A rdfs:subClassOf [ a owl:Restriction ; owl:someValuesFrom :B ] .",
            "profile failed",
        ),
        (":A rdfs:subClassOf <urn:external:Missing> .", "profile failed"),
        (
            ":property a owl:DatatypeProperty, owl:ObjectProperty .",
            "profile failed",
        ),
        (
            ":property a owl:DatatypeProperty, owl:InverseFunctionalProperty .",
            "profile failed",
        ),
        (
            ":property a owl:DatatypeProperty ; rdfs:range xsd:integer . "
            ':individual a owl:NamedIndividual ; :property "not an integer" .',
            "inconsistent",
        ),
        (
            ":unknown a rdfs:Datatype . "
            ":property a owl:DatatypeProperty ; rdfs:range :unknown . "
            ':individual a owl:NamedIndividual ; :property "value"^^:unknown .',
            "profile failed",
        ),
        (
            ":property a owl:DatatypeProperty ; rdfs:range xsd:boolean . "
            ':individual a owl:NamedIndividual ; :property "not-a-boolean"^^xsd:boolean .',
            "literals failed",
        ),
        (
            ":property a owl:DatatypeProperty . "
            ':individual a owl:NamedIndividual ; :property "0x1.0p1"^^xsd:float .',
            "literals failed",
        ),
        (
            ":property a owl:DatatypeProperty . "
            ':individual a owl:NamedIndividual ; :property "1.0f"^^xsd:float .',
            "literals failed",
        ),
        (
            ":property a owl:DatatypeProperty . "
            ':individual a owl:NamedIndividual ; :property "1.0d"^^xsd:double .',
            "literals failed",
        ),
        (
            ":property a owl:DatatypeProperty . :individual a owl:NamedIndividual ; "
            ':property "1.25"^^xsd:float, "1e-9"^^xsd:double, '
            '"true"^^xsd:boolean, "false"^^xsd:boolean, "1"^^xsd:boolean, "0"^^xsd:boolean .',
            None,
        ),
        (":A a owl:NamedIndividual .", None),
        (
            ":role a owl:ObjectProperty . :A rdfs:subClassOf [ a owl:Restriction ; "
            "owl:onProperty :role ; owl:someValuesFrom :B ] . "
            ":individual a owl:NamedIndividual, :A .",
            None,
        ),
        (
            ":property a owl:DatatypeProperty, owl:FunctionalProperty . "
            ":individual a owl:NamedIndividual ; :property 1, 2 .",
            "inconsistent",
        ),
        (
            ":Union a owl:Class ; owl:equivalentClass [ a owl:Class ; owl:unionOf ( :A :B ) ] . "
            ":NotA a owl:Class ; owl:equivalentClass [ a owl:Class ; owl:complementOf :A ] . "
            ":NotB a owl:Class ; owl:equivalentClass [ a owl:Class ; owl:complementOf :B ] . "
            ":individual a owl:NamedIndividual, :Union, :NotA, :NotB .",
            "inconsistent",
        ),
        (
            ":role a owl:ObjectProperty, owl:TransitiveProperty . "
            ":A rdfs:subClassOf [ a owl:Restriction ; owl:onProperty :role ; "
            'owl:maxCardinality "1"^^xsd:nonNegativeInteger ] .',
            "profile failed",
        ),
        (
            # This valid lexical form exceeds the pinned engine's date range.
            # Its reasoning failure must not become a successful check.
            ":property a owl:DatatypeProperty ; rdfs:range xsd:dateTime . "
            ':individual a owl:NamedIndividual ; :property "10000-01-01T00:00:00Z"^^xsd:dateTime .',
            "reason failed",
        ),
        (
            ":ontology owl:imports <https://example.invalid/not-pinned> .",
            "imports require a pinned local import policy",
        ),
    ],
    ids=[
        "consistent",
        "inconsistent",
        "unsatisfiable-class",
        "unparsed-triple",
        "parser-error-class-cannot-hide-malformed-input",
        "ambiguous-restriction-filler",
        "ambiguous-restriction-operator",
        "unterminated-list",
        "cyclic-list",
        "independent-keys",
        "false-self-restriction",
        "cardinality-engine-overflow",
        "valid-self-restrictions",
        "malformed-restriction",
        "undeclared-external-term",
        "property-punning",
        "inverse-functional-data-property",
        "datatype-clash",
        "unsupported-datatype",
        "invalid-boolean-lexical-form",
        "invalid-hex-float",
        "invalid-float-suffix",
        "invalid-double-suffix",
        "valid-native-literal-forms",
        "class-individual-punning",
        "open-world-existential",
        "functional-data-clash",
        "union-complement-clash",
        "non-dl-cardinality",
        "engine-date-limit",
        "uncontrolled-import",
    ],
)
def test_reasoning_boundary(tmp_path, axioms, error):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES + axioms, encoding="utf-8")
    result = run_check("--input", ontology)
    if error is None:
        assert result.returncode == 0, result.stdout + result.stderr
    else:
        assert result.returncode != 0
        assert error in (result.stdout + result.stderr).lower()
        report = read_report(result)
        assert report["status"] == "FAILED"
        if error in {"inconsistent", "unsatisfiable"}:
            assert report["stages"][-1]["name"] == "reason"
            assert all(stage["returncode"] == 0 for stage in report["stages"][:-1])
        if error in {"profile failed", "literals failed"}:
            assert report["stages"][-1]["name"] == error.split()[0]
            assert all(stage["returncode"] == 0 for stage in report["stages"][:-1])
        if error in {
            "requires one value",
            "one restriction operator",
            "malformed rdf list",
            "hasself requires boolean true",
            "cardinality exceeds owlapi",
        }:
            assert report["stages"] == []
        if "org.semanticweb.owlapi/error#" in axioms:
            assert "OWL parsing error:" in result.stderr
        if "owl:maxCardinality" in axioms:
            assert "Use of non-simple property in a restriction" in result.stderr


@pytest.fixture
def checker():
    spec = importlib.util.spec_from_file_location("ontology_check", CHECK)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize(
    "source",
    ["", PREFIXES.split(":A a owl:Class .")[0], PREFIXES + ":other a owl:Ontology ."],
    ids=["empty", "header-only", "multiple-ontologies"],
)
def test_empty_or_ambiguous_ontology_is_rejected(
    checker, monkeypatch, tmp_path, source
):
    path = tmp_path / "ontology.ttl"
    path.write_text(source, encoding="utf-8")
    monkeypatch.setattr(checker, "ARTIFACTS", tmp_path / "reports")
    with pytest.raises(
        ValueError, match="must declare exactly one|entity declarations"
    ):
        checker.check_ontology(path)
    report_path = next((tmp_path / "reports").glob("*/report.json"))
    report = json.loads(report_path.read_text())
    assert report["status"] == "FAILED" and report["stages"] == []
    assert report["inputs"][str(path)] == hashlib.sha256(path.read_bytes()).hexdigest()
    assert (report_path.parent / "source.ttl").read_bytes() == path.read_bytes()


def test_mapping_checks_allow_shared_tails_and_the_cardinality_boundary(checker):
    """Check syntax without making the solver materialise billions of witnesses."""
    graph = Graph().parse(
        data=PREFIXES + """
:p a owl:DatatypeProperty . :q a owl:DatatypeProperty . :r a owl:DatatypeProperty .
:A owl:hasKey _:first, _:second .
_:first rdf:first :p; rdf:rest _:tail .
_:second rdf:first :q; rdf:rest _:tail .
_:tail rdf:first :r; rdf:rest rdf:nil .
:role a owl:ObjectProperty .
:A rdfs:subClassOf [a owl:Restriction; owl:onProperty :role;
    owl:maxCardinality "2147483647"^^xsd:nonNegativeInteger] .
""",
        format="turtle",
    )
    checker.check_rdf_structure(graph)


def test_java_input_preserves_lexical_forms_and_relative_iris(checker, tmp_path):
    path = tmp_path / "ontology.ttl"
    source = (
        PREFIXES + ':p a owl:DatatypeProperty . <individual> :p "01"^^xsd:integer .'
    )
    path.write_text(source, encoding="utf-8")
    prepared = prepare_input(checker, path)
    assert source in prepared
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
        "<http://bia/Invented> a <http://www.w3.org/2002/07/owl#Class> .",
        "<urn:external:A> <http://www.w3.org/2002/07/owl#disjointWith> <urn:external:B> .",
    ],
    ids=["fabricated-bia-declaration", "external-logical-axiom"],
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


@pytest.mark.parametrize("property_name", ["orcid", "rorid"])
@pytest.mark.parametrize(
    ("shared_identifier", "assert_different", "consistent"),
    [(True, True, False), (False, True, True), (True, False, True)],
    ids=["conflicting-identities", "distinct-identifiers", "shared-identity"],
)
def test_bia_identifier_keys(
    tmp_path, property_name, shared_identifier, assert_different, consistent
):
    source = ROOT / "src/bia_ro_crate/models/linked_data/bia_ontology.ttl"
    second = "identifier-one" if shared_identifier else "identifier-two"
    assertions = f"""
@prefix test: <urn:identifier-test:> .
test:one a owl:NamedIndividual, bia:Contributor ; bia:{property_name} "identifier-one" .
test:two a owl:NamedIndividual, bia:Contributor ; bia:{property_name} "{second}" .
"""
    if assert_different:
        assertions += "test:one owl:differentFrom test:two ."
    ontology = tmp_path / "identifiers.ttl"
    ontology.write_text(
        source.read_text(encoding="utf-8") + assertions, encoding="utf-8"
    )
    result = run_check("--input", ontology)
    assert (result.returncode == 0) == consistent, result.stdout + result.stderr
    if not consistent:
        assert "reason failed" in result.stderr
        assert "inconsistent" in result.stderr


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


def test_timed_out_stage_cannot_report_success(checker, monkeypatch, tmp_path, capsys):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES, encoding="utf-8")
    monkeypatch.setattr(checker, "ARTIFACTS", tmp_path / "reports")

    def timeout(command, **kwargs):
        raise subprocess.TimeoutExpired(command, kwargs["timeout"])

    monkeypatch.setattr(checker.subprocess, "run", timeout)
    with pytest.raises(subprocess.TimeoutExpired):
        checker.check_ontology(ontology)
    assert "passed" not in capsys.readouterr().out


def test_bia_ontology_identity_is_checked(checker, monkeypatch, tmp_path):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES, encoding="utf-8")
    monkeypatch.setattr(checker, "ONTOLOGY", ontology)
    with pytest.raises(ValueError, match="BIA ontology IRI"):
        prepare_input(checker, ontology)


def test_zero_exit_without_profile_output_is_not_success(
    checker, monkeypatch, tmp_path
):
    """This process emulator tests evidence handling, not Java reasoning."""
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES)
    monkeypatch.setattr(checker, "ARTIFACTS", tmp_path / "reports")

    def no_output(command, **kwargs):
        if "--version" in command:
            kwargs["stdout"].write(f"ROBOT version {checker.ROBOT_VERSION}\n")
        elif "--class-path" in command:
            kwargs["stdout"].write("Raw Turtle literal validation passed.\n")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(checker.subprocess, "run", no_output)
    with pytest.raises(
        RuntimeError, match="profile returned zero without required output"
    ):
        checker.check_ontology(ontology)
    report = json.loads(next((tmp_path / "reports").glob("*/report.json")).read_text())
    assert report["status"] == "FAILED"


def test_changing_input_between_stages_is_rejected(checker, monkeypatch, tmp_path):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES)
    monkeypatch.setattr(checker, "ARTIFACTS", tmp_path / "reports")
    real_run = checker.subprocess.run

    def change_source(command, **kwargs):
        result = real_run(command, **kwargs)
        ontology.write_text(PREFIXES + ":A owl:disjointWith :B .")
        return result

    monkeypatch.setattr(checker.subprocess, "run", change_source)
    with pytest.raises(RuntimeError, match="inputs changed"):
        checker.check_ontology(ontology)
    report = json.loads(next((tmp_path / "reports").glob("*/report.json")).read_text())
    assert report["status"] == "FAILED"
    assert [stage["name"] for stage in report["stages"]] == ["version"]


def test_inherited_jvm_options_cannot_change_the_check(checker, monkeypatch, tmp_path):
    ontology = tmp_path / "ontology.ttl"
    ontology.write_text(PREFIXES)
    monkeypatch.setattr(checker, "ARTIFACTS", tmp_path / "reports")
    variables = (
        "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "_JAVA_OPTIONS",
        "ROBOT_JAVA_ARGS",
    )
    for variable in variables:
        monkeypatch.setenv(variable, "-not-a-valid-jvm-option")
    real_run = checker.subprocess.run

    def clean_environment(command, **kwargs):
        assert all(variable not in kwargs["env"] for variable in variables)
        return real_run(command, **kwargs)

    monkeypatch.setattr(checker.subprocess, "run", clean_environment)
    checker.check_ontology(ontology)


def test_non_file_and_oversized_inputs_are_rejected(checker, tmp_path):
    with pytest.raises(ValueError, match="regular file"):
        checker.read_regular_file(tmp_path)
    ontology = tmp_path / "oversized.ttl"
    ontology.write_bytes(b"12345")
    with pytest.raises(ValueError, match="exceeds"):
        checker.read_regular_file(ontology, limit=4)
