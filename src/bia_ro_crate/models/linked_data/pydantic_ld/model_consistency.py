"""Static checks for Pydantic field declarations against an RDF vocabulary.

Named subclasses, equivalent classes, disjoint classes and property inheritance
are supported. Encountered anonymous/complex class expressions and unsupported
mapped annotations are diagnostics, not evidence of compatibility. Supply an
already validated ontology: this is not an OWL syntax/profile validator. No
graph is mutated or vocabulary fetched.
"""

from collections import deque
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from enum import Enum
from itertools import combinations_with_replacement
from types import UnionType
from typing import Annotated, Literal, TypeAliasType, Union, get_args, get_origin
from urllib.parse import urlsplit

from pydantic import AnyUrl, BaseModel, RootModel
from rdflib import BNode, Graph, URIRef
from rdflib.namespace import OWL, RDF, RDFS, XSD

from bia_ro_crate.models.linked_data.pydantic_ld.FieldContext import FieldContext


class OntologyValidationError(ValueError):
    """All declaration problems found during a model's recursive inspection."""

    def __init__(self, issues: list[str]):
        self.issues = tuple(dict.fromkeys(issues))
        super().__init__("Ontology/model inconsistencies:\n" + "\n".join(self.issues))


@dataclass(frozen=True)
class OntologyIssue:
    path: str
    message: str
    code: str
    severity: str = "error"


@dataclass(frozen=True)
class OntologyConsistencyReport:
    """Scoped diagnostics, including gaps that a boolean result cannot convey."""

    issues: tuple[OntologyIssue, ...]

    @property
    def errors(self) -> tuple[OntologyIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "error")

    @property
    def notices(self) -> tuple[OntologyIssue, ...]:
        return tuple(issue for issue in self.issues if issue.severity == "notice")

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_for_errors(self) -> None:
        if self.errors:
            raise OntologyValidationError(
                [f"{issue.path}: {issue.message}" for issue in self.errors]
            )


MAX_MODEL_STATES = 10_000
_INTEGER_BOUNDS = {
    "integer": (None, None),
    "nonNegativeInteger": (0, None),
    "positiveInteger": (1, None),
    "nonPositiveInteger": (None, 0),
    "negativeInteger": (None, -1),
    **{
        name: (-(2 ** (bits - 1)), 2 ** (bits - 1) - 1)
        for name, bits in (("byte", 8), ("short", 16), ("int", 32), ("long", 64))
    },
    **{
        name: (0, 2**bits - 1)
        for name, bits in (
            ("unsignedByte", 8),
            ("unsignedShort", 16),
            ("unsignedInt", 32),
            ("unsignedLong", 64),
        )
    },
}
_TEXT_TYPES = {
    XSD[name]
    for name in ("string", "normalizedString", "token", "language", "Name", "NCName")
}


def _alternatives(annotation, *, in_collection=False):
    """Yield value annotations, unwrapping collections, unions and literals."""
    origin, args = get_origin(annotation), get_args(annotation)
    if origin is Annotated:
        yield from _alternatives(args[0], in_collection=in_collection)
    elif origin in (Union, UnionType):
        for arg in args:
            yield from _alternatives(arg, in_collection=in_collection)
    elif origin in (list, set, frozenset, tuple):
        if in_collection or not args:
            yield annotation
        else:
            for arg in args:
                if arg is not Ellipsis:
                    yield from _alternatives(arg, in_collection=True)
    elif origin is Literal:
        for value in args:
            yield from _alternatives(type(value))
    elif isinstance(annotation, type) and issubclass(annotation, Enum):
        for member in annotation:
            yield from _alternatives(type(member.value))
    elif annotation is not type(None):
        yield annotation


def _literal_kind(annotation):
    # bool must precede int; Python's subclass relationship is not RDF typing.
    for python_type, kind in (
        (bool, "boolean"),
        (int, "integer"),
        (float, "float"),
        (Decimal, "decimal"),
        (datetime, "dateTime"),
        (date, "date"),
        (time, "time"),
        (timedelta, "duration"),
        (str, "text"),
        (AnyUrl, "text"),
    ):
        if isinstance(annotation, type) and issubclass(annotation, python_type):
            return kind
    return None


def _nested_declarations(annotation):
    """Find models and opaque aliases without inventing relations for wrappers."""
    if isinstance(annotation, TypeAliasType) or (
        isinstance(annotation, type) and issubclass(annotation, BaseModel)
    ):
        yield annotation
    else:
        origin, args = get_origin(annotation), get_args(annotation)
        if origin is Annotated:
            yield from _nested_declarations(args[0])
        elif isinstance(origin, type) and issubclass(origin, Mapping):
            if len(args) == 2:
                yield from _nested_declarations(args[1])
        elif origin is not Literal:
            for arg in args:
                yield from _nested_declarations(arg)


def _datatype_kinds(datatype):
    if datatype in (RDFS.Literal, RDFS.Resource):
        return {
            "text",
            "boolean",
            "integer",
            "float",
            "decimal",
            "date",
            "dateTime",
            "time",
            "duration",
        }
    if datatype in _TEXT_TYPES | {RDF.langString, XSD.anyURI}:
        return {"text"}
    if datatype == XSD.decimal:
        return {"integer", "decimal"}
    if datatype in (XSD.float, XSD.double):
        return {"float"}
    if str(datatype).startswith(str(XSD)):
        name = str(datatype)[len(str(XSD)) :]
        if name in _INTEGER_BOUNDS:
            return {"integer"}
        if name == "dateTimeStamp":
            return {"dateTime"}
        if name in {"boolean", "date", "dateTime", "time", "duration"}:
            return {name}
    if datatype == URIRef("http://schema.org/URL"):
        return {"text"}
    return None


class _Inspector:
    """Own the facts, diagnostics and bounded worklist for one inspection."""

    def __init__(self, graph: Graph, reference: type[BaseModel]):
        self.graph = graph
        self.reference = reference
        self.issues = []
        self.queue = deque()
        self.visited = set()

    def issue(self, path, message, code="INCOMPATIBLE_DECLARATION", *, notice=False):
        item = OntologyIssue(path, message, code, "notice" if notice else "error")
        if item not in self.issues:
            self.issues.append(item)

    def is_datatype(self, term):
        return (
            term == RDFS.Literal
            or str(term).startswith(str(XSD))
            or term in {RDF.langString, OWL.real, OWL.rational}
            or (term, RDF.type, RDFS.Datatype) in self.graph
        )

    def class_closure(self, seeds):
        result, pending = set(), sorted(
            set(seeds) | {OWL.Thing, RDFS.Resource}, key=str
        )
        while pending:
            term = pending.pop()
            if term in result:
                continue
            result.add(term)
            pending.extend(self.graph.objects(term, RDFS.subClassOf))
            pending.extend(self.graph.objects(term, OWL.equivalentClass))
            pending.extend(self.graph.subjects(OWL.equivalentClass, term))
        return result

    def check_classes(self, seeds, path):
        inferred = self.class_closure(seeds)
        for term in sorted(inferred, key=str):
            if isinstance(term, BNode) or any(
                (term, predicate, None) in self.graph
                for predicate in (
                    OWL.unionOf,
                    OWL.intersectionOf,
                    OWL.complementOf,
                    OWL.disjointUnionOf,
                    OWL.oneOf,
                    OWL.onProperty,
                    OWL.onDatatype,
                    OWL.withRestrictions,
                )
            ):
                self.issue(
                    path,
                    "complex class expressions require an OWL reasoner",
                    "UNSUPPORTED_CLASS_EXPRESSION",
                )
            elif not isinstance(term, URIRef):
                self.issue(path, "inferred class must be an IRI")
            if term == OWL.Nothing:
                self.issue(path, "inferred type is owl:Nothing")
            if self.is_datatype(term):
                self.issue(path, f"node type cannot be a literal datatype: {term}")
            if (
                isinstance(term, URIRef)
                and (term, None, None) not in self.graph
                and term not in {OWL.Thing, OWL.Nothing, RDFS.Resource}
            ):
                self.issue(
                    path,
                    f"no class axioms supplied for {term}",
                    "MISSING_CLASS_AXIOMS",
                    notice=True,
                )
        for left, right in combinations_with_replacement(sorted(inferred, key=str), 2):
            if frozenset((left, right)) in self.disjoint:
                self.issue(path, f"inferred types are disjoint: {left} and {right}")
        return inferred

    def property_info(self, context, path):
        try:
            context.to_context_term("property")
        except (ValueError, TypeError) as error:
            self.issue(path, str(error), "INVALID_FIELD_CONTEXT")
            return None
        containers = (
            {context.container}
            if isinstance(context.container, str)
            else set(context.container or ())
        )
        if containers not in (set(), {"@set"}):
            self.issue(
                path,
                "list/indexed/language/graph containers require an explicit mapping policy",
                "UNSUPPORTED_CONTAINER",
            )
            return None
        # Track orientation while following inverse and equivalent properties.
        pending = [(context.uri, context.is_reverse_field)]
        seen, kinds, domains, ranges = set(), set(), set(), set()
        incoming_links = any(
            (None, predicate, context.uri) in self.graph
            for predicate in (RDFS.subPropertyOf, OWL.equivalentProperty, OWL.inverseOf)
        )
        if (context.uri, None, None) not in self.graph and not incoming_links:
            self.issue(
                path, f"context URI is not defined: {context.uri}", "MISSING_PROPERTY"
            )
            return None
        while pending:
            prop, reverse = pending.pop()
            if (prop, reverse) in seen:
                continue
            seen.add((prop, reverse))
            if not isinstance(prop, URIRef):
                self.issue(
                    path,
                    "anonymous property expressions require an OWL reasoner",
                    "UNSUPPORTED_PROPERTY_EXPRESSION",
                )
                continue
            if (prop, None, None) not in self.graph:
                self.issue(
                    path,
                    f"no related-property axioms supplied for {prop}",
                    "MISSING_PROPERTY_AXIOMS",
                    notice=True,
                )
            if (prop, OWL.propertyChainAxiom, None) in self.graph:
                self.issue(
                    path,
                    "property-chain axioms require an OWL reasoner",
                    "UNSUPPORTED_PROPERTY_AXIOM",
                )
            if any(
                (prop, URIRef(namespace + name), None) in self.graph
                for namespace in ("http://schema.org/", "https://schema.org/")
                for name in ("domainIncludes", "rangeIncludes")
            ):
                self.issue(
                    path,
                    "Schema.org includes-statements are advisory, not hard domain/range constraints",
                    "ADVISORY_CONSTRAINTS",
                    notice=True,
                )
            types = set(self.graph.objects(prop, RDF.type))
            # A symmetric superproperty constrains both ends of each assertion.
            if OWL.SymmetricProperty in types:
                pending.append((prop, not reverse))
            if types & {
                OWL.TransitiveProperty,
                OWL.SymmetricProperty,
                OWL.AsymmetricProperty,
                OWL.ReflexiveProperty,
                OWL.IrreflexiveProperty,
                OWL.InverseFunctionalProperty,
            }:
                kinds.add(OWL.ObjectProperty)
            if OWL.FunctionalProperty in types:
                kinds.add(RDF.Property)
            inverses = set(self.graph.objects(prop, OWL.inverseOf)) | set(
                self.graph.subjects(OWL.inverseOf, prop)
            )
            if inverses:
                kinds.add(OWL.ObjectProperty)
            if (prop, RDFS.subPropertyOf, None) in self.graph or (
                None,
                RDFS.subPropertyOf,
                prop,
            ) in self.graph:
                kinds.add(RDF.Property)
            # These vocabulary statements also entail rdf:Property in RDFS;
            # a redundant explicit declaration is not required.
            if (
                any(
                    (prop, predicate, None) in self.graph
                    for predicate in (RDFS.domain, RDFS.range, OWL.equivalentProperty)
                )
                or (None, OWL.equivalentProperty, prop) in self.graph
            ):
                kinds.add(RDF.Property)
            if reverse and OWL.DatatypeProperty in types:
                self.issue(path, f"cannot reverse datatype property {prop}")
            kinds.update(types)
            domains.update(
                self.graph.objects(prop, RDFS.range if reverse else RDFS.domain)
            )
            ranges.update(
                self.graph.objects(prop, RDFS.domain if reverse else RDFS.range)
            )
            pending.extend(
                (p, reverse) for p in self.graph.objects(prop, RDFS.subPropertyOf)
            )
            pending.extend(
                (p, reverse) for p in self.graph.objects(prop, OWL.equivalentProperty)
            )
            pending.extend(
                (p, reverse) for p in self.graph.subjects(OWL.equivalentProperty, prop)
            )
            pending.extend((p, not reverse) for p in inverses)
        if not kinds & {
            OWL.ObjectProperty,
            OWL.DatatypeProperty,
            OWL.AnnotationProperty,
            RDF.Property,
        }:
            self.issue(path, f"context URI is not a property: {context.uri}")
        if OWL.ObjectProperty in kinds and OWL.DatatypeProperty in kinds:
            self.issue(
                path,
                f"conflicting object/datatype property declarations: {context.uri}",
            )
        return kinds, domains, ranges

    def check_literal_ranges(self, ranges, path):
        # Representation kinds alone cannot detect empty datatype intersections.
        # OWL 2 makes float/double/decimal value spaces pairwise disjoint.
        spaces, lower, upper = set(), [], []
        for term in ranges:
            name = str(term).removeprefix(str(XSD))
            if name in _INTEGER_BOUNDS:
                spaces.add("decimal")
                lo, hi = _INTEGER_BOUNDS[name]
                if lo is not None:
                    lower.append(lo)
                if hi is not None:
                    upper.append(hi)
            elif term in _TEXT_TYPES:
                spaces.add("text")
            elif term == XSD.dateTimeStamp:
                spaces.add(str(XSD.dateTime))
            elif term in {
                XSD.decimal,
                XSD.float,
                XSD.double,
                XSD.boolean,
                XSD.date,
                XSD.dateTime,
                XSD.time,
                XSD.duration,
                XSD.anyURI,
                RDF.langString,
            }:
                spaces.add("decimal" if term == XSD.decimal else str(term))
        if len(spaces) > 1 or lower and upper and max(lower) > min(upper):
            self.issue(
                path,
                "conjunctive datatype ranges have no common value",
                "DISJOINT_DATATYPES",
            )
        if not ranges:
            self.issue(
                path,
                "no hard range supplied; only value shape is checked",
                "NO_RANGE",
                notice=True,
            )
        elif ranges - {
            XSD.string,
            XSD.integer,
            XSD.boolean,
            RDFS.Literal,
            RDFS.Resource,
        }:
            self.issue(
                path,
                "literal lexical forms, bounds, language and serialisation remain unchecked",
                "LITERAL_VALUES_UNCHECKED",
                notice=True,
            )

    def visit(self, current, incoming, path):
        if issubclass(current, RootModel):
            self.issue(
                path,
                "RootModel serialisation requires an explicit node/literal mapping",
                "UNSUPPORTED_ROOT_MODEL",
            )
            return
        if not current.__pydantic_complete__:
            self.issue(
                path,
                "unresolved model annotation; call model_rebuild() before inspection",
                "UNRESOLVED_MODEL",
            )
            return
        contexts = {}
        seeds = set(incoming)
        declared = current.model_config.get("model_type")
        if declared is not None:
            if type(declared) not in (str, URIRef):
                self.issue(path, "model_type must be an absolute named class IRI")
            else:
                try:
                    if not urlsplit(declared).scheme:
                        raise ValueError("relative IRI")
                    URIRef(declared).n3()
                except Exception:
                    self.issue(path, "model_type must be an absolute named class IRI")
                else:
                    seeds.add(URIRef(declared))
        mapped_here = 0
        for name, field in current.model_fields.items():
            metadata = [m for m in field.metadata if isinstance(m, FieldContext)]
            if len(metadata) > 1:
                self.issue(f"{path}.{name}", "multiple FieldContexts")
                continue
            if metadata:
                mapped_here += 1
                info = self.property_info(metadata[0], f"{path}.{name}")
                if info:
                    contexts[name] = metadata[0], info
                    if list(_alternatives(field.annotation)):
                        seeds.update(info[1])
        if not mapped_here:
            self.issue(
                path,
                "no FieldContext fields; only class and nested-model checks apply",
                "NO_MAPPED_FIELDS",
                notice=True,
            )
        self.check_classes(seeds, path)
        for name, field in current.model_fields.items():
            field_path = f"{path}.{name}"
            context, info = contexts.get(name, (None, None))
            nested_seen = set()
            literal_ranges_checked = False
            for annotation in dict.fromkeys(_alternatives(field.annotation)):
                nested = isinstance(annotation, type) and issubclass(
                    annotation, BaseModel
                )
                is_reference = annotation is self.reference
                if info:
                    kinds, _, ranges = info
                    node = (
                        nested
                        or context.is_id_field
                        and (_literal_kind(annotation) == "text")
                    )
                    if context.is_id_field and not node:
                        self.issue(
                            field_path, "ID fields require strings or node models"
                        )
                    if OWL.ObjectProperty in kinds and not node:
                        self.issue(
                            field_path,
                            "object property requires a reference or nested model",
                        )
                    if OWL.DatatypeProperty in kinds and node:
                        self.issue(field_path, "datatype property cannot contain nodes")
                    if context.is_reverse_field and not node:
                        self.issue(field_path, "reverse property requires nodes")
                    if node:
                        if not nested or is_reference:
                            self.check_classes(ranges, field_path)
                        if any(self.is_datatype(term) for term in ranges):
                            self.issue(field_path, "node property has a datatype range")
                    else:
                        if not literal_ranges_checked:
                            self.check_literal_ranges(ranges, field_path)
                            literal_ranges_checked = True
                        kind = _literal_kind(annotation)
                        if kind is None:
                            self.issue(
                                field_path,
                                f"unsupported value annotation: {annotation}",
                                "UNSUPPORTED_ANNOTATION",
                            )
                        for datatype in sorted(ranges, key=str):
                            allowed = _datatype_kinds(datatype)
                            if allowed is None:
                                self.issue(
                                    field_path,
                                    f"unsupported datatype range: {datatype}",
                                    "UNSUPPORTED_DATATYPE",
                                )
                            elif kind is not None and kind not in allowed:
                                self.issue(
                                    field_path,
                                    f"{annotation} is incompatible with {datatype}",
                                )
                    if node and (not nested or issubclass(annotation, self.reference)):
                        self.issue(
                            field_path,
                            "reference target was not resolved or type-checked",
                            "REFERENCE_TARGET_UNCHECKED",
                            notice=True,
                        )
                if nested and not is_reference:
                    nested_seen.add(annotation)
                    self.queue.append(
                        (
                            annotation,
                            frozenset(info[2]) if info else frozenset(),
                            field_path,
                        )
                    )
            for child in dict.fromkeys(_nested_declarations(field.annotation)):
                if isinstance(child, TypeAliasType):
                    if not info:
                        self.issue(
                            field_path,
                            "type-alias traversal is outside the supported fragment",
                            "UNSUPPORTED_ANNOTATION",
                        )
                elif child not in nested_seen and child is not self.reference:
                    self.queue.append((child, frozenset(), f"{field_path}[*]"))

    def load_disjointness(self, model):
        self.disjoint = set()
        for left, right in self.graph.subject_objects(OWL.disjointWith):
            self.disjoint.add(frozenset((left, right)))
        for node in self.graph.subjects(RDF.type, OWL.AllDisjointClasses):
            heads = list(self.graph.objects(node, OWL.members))
            if len(heads) != 1:
                self.issue(
                    model.__name__, "AllDisjointClasses requires one members list"
                )
                continue
            members, seen, cell = [], set(), heads[0]
            while cell != RDF.nil:
                first, rest = list(self.graph.objects(cell, RDF.first)), list(
                    self.graph.objects(cell, RDF.rest)
                )
                if cell in seen or len(first) != 1 or len(rest) != 1:
                    break
                seen.add(cell)
                members.append(first[0])
                cell = rest[0]
            if cell != RDF.nil:
                self.issue(model.__name__, "malformed disjoint-classes list")
                continue
            if len(members) < 2 or not all(
                isinstance(member, URIRef) for member in members
            ):
                self.issue(
                    model.__name__,
                    "disjoint-classes lists require at least two named classes",
                )
                continue
            for index, left in enumerate(members):
                for right in members[index + 1 :]:
                    self.disjoint.add(frozenset((left, right)))

    def inspect(self, model):
        self.queue.append((model, frozenset(), model.__name__))
        if (None, OWL.imports, None) in self.graph:
            self.issue(
                model.__name__,
                "Import closure is caller-supplied; no imports were fetched",
                "IMPORT_CLOSURE_UNCHECKED",
                notice=True,
            )
        self.load_disjointness(model)
        while self.queue:
            current, incoming, path = self.queue.popleft()
            key = current, incoming
            if key in self.visited:
                continue
            if len(self.visited) >= MAX_MODEL_STATES:
                self.issue(
                    path,
                    "model-context limit reached; inspection is incomplete",
                    "MODEL_STATE_LIMIT",
                )
                break
            self.visited.add(key)
            self.visit(current, incoming, path)
        issues = tuple(
            sorted(
                self.issues,
                key=lambda item: (item.path, item.severity, item.code, item.message),
            )
        )
        return OntologyConsistencyReport(issues)


def inspect_model(
    model: type[BaseModel], graph: Graph, reference: type[BaseModel]
) -> OntologyConsistencyReport:
    """Inspect declared value kinds and named implications without evaluating code.

    Every non-null annotation branch is checked, including optional fields. This
    can flag incompatible combinations that an instance avoids by omitting a
    field. Missing subclass links are allowed under RDF's open-world semantics.
    Custom serialisers/validators and lexical/facet checks remain separate.
    """
    if not isinstance(graph, Graph):
        raise TypeError("ontology must be an RDFLib Graph")
    return _Inspector(graph, reference).inspect(model)
