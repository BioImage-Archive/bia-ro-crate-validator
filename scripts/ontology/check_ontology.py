"""Check BIA's local OWL axioms with pinned ROBOT/OWLAPI and HermiT."""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
import time
import urllib.request
from pathlib import Path

from rdflib import Graph, Literal, URIRef
from rdflib.namespace import OWL, RDF, XSD

ROOT = Path(__file__).resolve().parents[2]
ARTIFACTS = ROOT / "artifacts" / "ontology-consistency"
ONTOLOGY = ROOT / "src/bia_ro_crate/models/linked_data/bia_ontology.ttl"
DECLARATIONS = ROOT / "test/ontology/external-declarations.ttl"
ROBOT_VERSION = "1.9.11"
ROBOT_SHA256 = "53cd275c8e4c0dad1fc2c1c34174876795cd7d6b6926e1444adcbb0cb3c7ab26"
ROBOT_JAR = ARTIFACTS / "tools" / "robot.jar"
JAVA_CHECK = Path(__file__).resolve().with_name("CheckOntology.java")
MAX_INPUT_BYTES = 16 * 1024 * 1024
MAX_DOWNLOAD_BYTES = 128 * 1024 * 1024
JAVA_BUDGET_SECONDS = 60


def read_regular_file(path: Path, limit: int = MAX_INPUT_BYTES) -> bytes:
    """Bound local inputs and refuse non-files before opening pipes/devices."""
    if not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    with path.open("rb") as stream:
        data = stream.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"Input exceeds {limit} bytes: {path}")
    return data


def check_rdf_structure(graph: Graph) -> None:
    """Reject ambiguous expressions and broken lists before permissive OWL parsing.

    These are RDF mapping checks, not reasoning. OWL 2 mappings:
    https://www.w3.org/TR/owl2-mapping-to-rdf/#Parsing_of_Expressions
    """
    list_properties = {
        OWL[name]
        for name in (
            "intersectionOf",
            "unionOf",
            "oneOf",
            "members",
            "distinctMembers",
            "propertyChainAxiom",
            "hasKey",
            "withRestrictions",
            "onProperties",
        )
    }
    restriction_operators = {
        OWL[name]
        for name in (
            "someValuesFrom",
            "allValuesFrom",
            "hasValue",
            "hasSelf",
            "cardinality",
            "minCardinality",
            "maxCardinality",
            "qualifiedCardinality",
            "minQualifiedCardinality",
            "maxQualifiedCardinality",
        )
    }
    single_values = (
        restriction_operators
        | {
            OWL[name]
            for name in (
                "onProperty",
                "onClass",
                "onDataRange",
                "onDatatype",
                "complementOf",
                "datatypeComplementOf",
                "annotatedSource",
                "annotatedProperty",
                "annotatedTarget",
            )
        }
        | (list_properties - {OWL.hasKey, OWL.propertyChainAxiom})
    )
    for predicate in single_values:
        for subject in graph.subjects(predicate, unique=True):
            if len(list(graph.objects(subject, predicate))) != 1:
                raise ValueError(
                    f"OWL expression requires one value: {subject} {predicate}"
                )
    restrictions = set(graph.subjects(RDF.type, OWL.Restriction))
    restrictions.update(s for p in restriction_operators for s in graph.subjects(p))
    for node in restrictions:
        operators = [p for p in restriction_operators if (node, p, None) in graph]
        if len(operators) != 1:
            raise ValueError(f"Expected one restriction operator: {node}")
        operator = operators[0]
        value = graph.value(node, operator)
        if operator == OWL.hasSelf and (
            not isinstance(value, Literal)
            or value.datatype != XSD.boolean
            or value.value is not True
        ):
            raise ValueError(f"owl:hasSelf requires boolean true: {node}")
        if str(operator).endswith(("Cardinality", "#cardinality")):
            if (
                not isinstance(value, Literal)
                or value.datatype != XSD.nonNegativeInteger
                or type(value.value) is not int
                or value.value < 0
            ):
                raise ValueError(
                    f"OWL cardinality requires a non-negative integer: {node}"
                )
            # OWLAPI stores cardinalities in Java int; overflow can become zero.
            if value.value > 2**31 - 1:
                raise ValueError(
                    f"Cardinality exceeds OWLAPI's supported integer range: {node}"
                )

    nodes = set(graph.subjects(RDF.first)) | set(graph.subjects(RDF.rest))
    links = {}
    for node in nodes:
        first, rest = list(graph.objects(node, RDF.first)), list(
            graph.objects(node, RDF.rest)
        )
        if node == RDF.nil or len(first) != 1 or len(rest) != 1:
            raise ValueError(f"Malformed RDF list cell: {node}")
        links[node] = rest[0]
    for predicate in list_properties:
        for head in graph.objects(None, predicate):
            if head != RDF.nil and head not in links:
                raise ValueError(f"Malformed RDF list head: {head}")
    complete = set()
    for head in links:
        path, node = set(), head
        while node != RDF.nil and node not in complete:
            if node in path or node not in links:
                raise ValueError(f"Malformed RDF list tail or cycle: {node}")
            path.add(node)
            node = links[node]
        complete.update(path)


def reasoning_input(path: Path, inputs: dict[Path, bytes]) -> str:
    """Validate captured RDF without changing source literal forms or IRI bases."""
    path = path.absolute()
    source = inputs[path].decode("utf-8-sig")
    declarations = inputs[DECLARATIONS].decode("utf-8-sig")
    graph = Graph().parse(data=source, publicID=path.as_uri(), format="turtle")
    external = Graph().parse(
        data=declarations, publicID=DECLARATIONS.absolute().as_uri(), format="turtle"
    )

    ontologies = set(graph.subjects(RDF.type, OWL.Ontology))
    if len(ontologies) != 1 or not all(isinstance(o, URIRef) for o in ontologies):
        raise ValueError("Input must declare exactly one named OWL ontology")
    if path.resolve() == ONTOLOGY.resolve() and ontologies != {URIRef("http://bia/")}:
        raise ValueError("BIA ontology IRI must be http://bia/")
    entities = {
        OWL.Class,
        OWL.ObjectProperty,
        OWL.DatatypeProperty,
        OWL.AnnotationProperty,
    }
    if not any(kind in entities for kind in graph.objects(None, RDF.type)):
        raise ValueError("Input must contain ontology entity declarations")
    if any(graph.triples((None, OWL.imports, None))):
        raise ValueError("OWL imports require a pinned local import policy")
    for subject, predicate, kind in external:
        if (
            not isinstance(subject, URIRef)
            or str(subject).startswith("http://bia/")
            or predicate != RDF.type
            or kind not in entities
        ):
            raise ValueError(
                "External vocabulary may contain only external declarations"
            )

    check_rdf_structure(graph)
    # Keep source lexical forms and relative IRIs intact. Only declaration
    # triples are serialised: full IRIs prevent base/prefix leakage between files.
    declarations = "\n".join(sorted(external.serialize(format="nt").splitlines()))
    return f"@base <{path.as_uri()}> .\n{source}\n{declarations}\n"


def verify_robot(path: Path) -> None:
    """Reject an absent or changed tool before executing Java."""
    if not path.is_file() or path.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise ValueError(f"Expected a bounded regular JAR file: {path}")
    with path.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    if digest != ROBOT_SHA256:
        raise ValueError(f"ROBOT {ROBOT_VERSION} checksum mismatch: {path}")


def install_robot() -> None:
    """Download the release once; publish it only after checksum verification."""
    if ROBOT_JAR.exists():
        verify_robot(ROBOT_JAR)
        return
    ROBOT_JAR.parent.mkdir(parents=True, exist_ok=True)
    url = (
        "https://github.com/ontodev/robot/releases/download/"
        f"v{ROBOT_VERSION}/robot.jar"
    )
    with tempfile.TemporaryDirectory(dir=ROBOT_JAR.parent) as directory:
        download = Path(directory) / "robot.jar"
        deadline = time.monotonic() + 120
        with urllib.request.urlopen(url, timeout=30) as response:
            with download.open("wb") as stream:
                total = 0
                # A single buffered read returns available bytes; read(n) could
                # wait indefinitely for n bytes from a slowly trickling peer.
                while chunk := response.read1(1024 * 1024):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES or time.monotonic() > deadline:
                        raise ValueError("ROBOT download exceeded its size/time budget")
                    stream.write(chunk)
        verify_robot(download)
        download.replace(ROBOT_JAR)


def check_ontology(path: Path) -> None:
    """Reject imports, parse loss and profile violations before DL reasoning.

    External vocabulary receives declarations only. Its full semantics are not
    included; new imports require an explicit, pinned local import policy.
    """
    ARTIFACTS.mkdir(parents=True, exist_ok=True)
    output = Path(tempfile.mkdtemp(prefix="ontology-", dir=ARTIFACTS))
    print(f"Ontology reports: {output}", flush=True)
    report = {
        "status": "IN_PROGRESS",
        "engine": "HermiT",
        "source": str(path.absolute()),
        "stages": [],
    }
    (output / "report.json").write_text(
        json.dumps(report, indent=2) + "\n", encoding="utf-8"
    )
    try:
        _check_ontology(path, output, report)
        report["status"] = "PASS"
    except BaseException as error:
        report["status"] = "FAILED"
        report["error"] = f"{type(error).__name__}: {error}"
        raise
    finally:
        (output / "report.json").write_text(
            json.dumps(report, indent=2) + "\n", encoding="utf-8"
        )
    print("OWL 2 DL profile, consistency and named-class satisfiability passed.")


def _check_ontology(path: Path, output: Path, report: dict) -> None:
    verify_robot(ROBOT_JAR)
    executable = "java.exe" if os.name == "nt" else "java"
    java_home = os.environ.get("JAVA_HOME")
    java = (
        str(Path(java_home) / "bin" / executable)
        if java_home
        else shutil.which(executable)
    )
    if not java or not Path(java).is_file():
        raise RuntimeError("JDK 17 or newer is required for the ontology check")
    java = str(Path(java).resolve())
    inputs = {}
    report["inputs"] = {}
    for input_path, name in (
        (path.absolute(), "source.ttl"),
        (DECLARATIONS, "external-declarations.ttl"),
        (JAVA_CHECK, "CheckOntology.java"),
    ):
        data = read_regular_file(input_path)
        inputs[input_path] = data
        (output / name).write_bytes(data)
        report["inputs"][str(input_path)] = hashlib.sha256(data).hexdigest()
    source = reasoning_input(path, inputs)
    snapshot = output / "input.ttl"
    snapshot.write_text(source, encoding="utf-8", newline="")
    original = snapshot.read_bytes()
    report["effective_input_sha256"] = hashlib.sha256(original).hexdigest()
    report["robot_sha256"] = ROBOT_SHA256
    report["java"] = java
    prefix = [java, "-Xmx1G", "-Dfile.encoding=UTF-8"]
    native = prefix + [
        "--class-path",
        str(ROBOT_JAR),
        "--source",
        "17",
        str(JAVA_CHECK),
    ]
    commands = {"version": prefix + ["-jar", str(ROBOT_JAR), "--version"]}
    for stage in ("literals", "profile", "reason"):
        commands[stage] = native + [str(snapshot), stage, str(output)]
    environment = os.environ.copy()
    for key in (
        "JAVA_TOOL_OPTIONS",
        "JDK_JAVA_OPTIONS",
        "_JAVA_OPTIONS",
        "ROBOT_JAVA_ARGS",
    ):
        environment.pop(key, None)
    deadline = time.monotonic() + JAVA_BUDGET_SECONDS
    for stage, command in commands.items():
        verify_robot(ROBOT_JAR)
        if snapshot.read_bytes() != original or any(
            read_regular_file(p) != data for p, data in inputs.items()
        ):
            raise RuntimeError("Ontology/checker inputs changed during validation")
        record = {"name": stage, "command": command}
        report["stages"].append(record)
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(command, JAVA_BUDGET_SECONDS)
        with (output / f"{stage}.log").open("w", encoding="utf-8") as log:
            result = subprocess.run(
                command,
                stdout=log,
                stderr=subprocess.STDOUT,
                timeout=remaining,
                check=False,
                cwd=output,
                stdin=subprocess.DEVNULL,
                env=environment,
            )
        record["returncode"] = result.returncode
        if result.returncode != 0:
            profile = output / "profile.txt"
            raise RuntimeError(
                f"{stage} failed (exit {result.returncode}):\n"
                + (output / f"{stage}.log").read_text(encoding="utf-8")
                + (profile.read_text(encoding="utf-8") if profile.exists() else "")
            )
        expected = {
            "profile": output / "profile.txt",
            "reason": output / "reason.txt",
        }.get(stage, output / f"{stage}.log")
        if not expected.is_file() or expected.stat().st_size == 0:
            raise RuntimeError(f"{stage} returned zero without required output")
        if (
            stage == "version"
            and f"ROBOT version {ROBOT_VERSION}"
            not in expected.read_text(encoding="utf-8").splitlines()
        ):
            raise RuntimeError("Unexpected ROBOT version output")
    verify_robot(ROBOT_JAR)
    if snapshot.read_bytes() != original or any(
        read_regular_file(p) != data for p, data in inputs.items()
    ):
        raise RuntimeError("Ontology/checker inputs changed during validation")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--install", action="store_true", help="install pinned ROBOT only"
    )
    parser.add_argument("--input", type=Path, default=ONTOLOGY)
    args = parser.parse_args()
    if args.install:
        install_robot()
    else:
        check_ontology(args.input)
