"""Model, context and relationship checks for editor-owned submissions."""

import json
import math
from collections.abc import Iterable
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit

from rdflib import RDF, BNode, Graph, URIRef

from bia_ro_crate.core.bia_submission_metadata import BIASubmissionMetadata
from bia_ro_crate.core.parser.tsv_metadata_parser import TSVMetadataParser
from bia_ro_crate.models import ro_crate_models as models
from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm
from bia_ro_crate.models.linked_data.ld_context.SimpleJSONLDContext import (
    SimpleJSONLDContext,
)
from bia_ro_crate.models.linked_data.ontology_terms import BIA, DUBLINCORE
from bia_ro_crate.models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel


def _absolute_iri(value: object) -> bool:
    return (
        isinstance(value, str)
        and bool(urlsplit(value).scheme)
        and not any(c.isspace() or ord(c) < 32 for c in value)
    )


def merge_context_terms(
    context: SimpleJSONLDContext, terms: Iterable[ContextTerm]
) -> None:
    for term in terms:
        if not isinstance(term, ContextTerm):
            raise TypeError("context_terms must contain ContextTerm instances")
        if term.field_name in context.prefixes or term.field_name.startswith("@"):
            raise ValueError(
                f"Context term collides with a prefix/keyword: {term.field_name}"
            )
        previous = context.terms.get(term.field_name)
        if previous is not None and previous != term:
            raise ValueError(f"Context mapping conflict: {term.field_name}")
        context.add_term(deepcopy(term))


def _ensure_model_terms(submission: BIASubmissionMetadata) -> None:
    context = submission.metadata.get_context()
    for entity in submission.metadata.get_objects():
        for term in type(entity).generate_field_context():
            previous = context.terms.get(term.field_name)
            if previous is None:
                merge_context_terms(context, [term])
            elif previous.full_uri != term.full_uri or bool(
                previous.is_reverse
            ) != bool(term.is_reverse):
                raise ValueError(f"Model property is remapped: {term.field_name}")


def _validate_context(context: SimpleJSONLDContext) -> None:
    for prefix, iri in context.prefixes.items():
        if prefix.startswith("@") or not _absolute_iri(str(iri)):
            raise ValueError(f"Unsupported context prefix: {prefix}")
        if prefix in context.terms:
            raise ValueError(f"Context prefix/term collision: {prefix}")
    for name, term in context.terms.items():
        if name != term.field_name or name.startswith("@"):
            raise ValueError(f"Unsupported context term key: {name}")
        if not _absolute_iri(str(term.full_uri)):
            raise ValueError(f"Context term requires an absolute IRI: {name}")
        if term.container not in (None, "@set", "@list"):
            raise ValueError(f"Unsupported container for safe editing: {name}")
        if term.type_mapping not in (
            None,
            "@id",
            "@vocab",
            "@json",
        ) and not _absolute_iri(term.type_mapping):
            raise ValueError(f"Unsupported type mapping: {name}")
    for key, mapping in getattr(context, "_special_mappings", {}).items():
        allowed = key == "@type" and mapping == {"@container": "@set"}
        allowed |= not key.startswith("@") and mapping in (
            {"@id": "@id"},
            {"@id": "@type"},
            {"@id": "@type", "@container": "@set"},
        )
        if not allowed or key in context.terms or key in context.prefixes:
            raise ValueError(f"Unsupported special context mapping: {key}")


def _mapped(name: str, context: SimpleJSONLDContext) -> bool:
    if name in context.terms:
        return True
    if ":" in name:
        prefix = name.split(":", 1)[0]
        return prefix in context.prefixes or _absolute_iri(name)
    return False


def _check_flat_value(value: Any, *, json_literal: bool = False) -> None:
    if json_literal:
        return  # Keys inside @json values are data, not JSON-LD properties.
    if isinstance(value, list):
        for item in value:
            _check_flat_value(item)
    elif isinstance(value, dict):
        if set(value) == {"@id"} and isinstance(value["@id"], str):
            return
        if "@value" in value and set(value) <= {
            "@value",
            "@language",
            "@type",
            "@direction",
            "@index",
        }:
            return
        if set(value) == {"@list"}:
            _check_flat_value(value["@list"])
            return
        raise ValueError(
            "Nested objects need an explicit @json mapping or a flat @id reference"
        )


def _check_json_values(value: Any) -> None:
    # Pydantic's JSON mode replaces non-finite floats with null. Reject them
    # before that conversion can silently discard a supplied metadata value.
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite metadata numbers cannot be preserved in JSON")
    if isinstance(value, dict):
        if any(not isinstance(key, str) for key in value):
            raise ValueError("Metadata object keys must be strings")
        for item in value.values():
            _check_json_values(item)
    elif isinstance(value, (list, tuple)):
        for item in value:
            _check_json_values(item)


def validate_entity(entity: ROCrateModel) -> ROCrateModel:
    if not isinstance(entity, ROCrateModel):
        raise TypeError("Expected an ROCrateModel")
    # model_validate(instance) can trust a previously mutated model. Validate
    # its data instead, including nested references, extras, and required fields.
    payload = deepcopy(entity.model_dump(mode="python", by_alias=True))
    _check_json_values(payload)
    return type(entity).model_validate(payload)


def _validate_structure(submission: BIASubmissionMetadata) -> None:
    metadata, file_list = submission.metadata, submission.file_list
    objects = metadata.get_object_lookup()
    for key, entity in list(objects.items()):
        if key != entity.id:
            raise ValueError(f"Graph key does not match object @id: {key}")
        objects[key] = validate_entity(entity)

    _ensure_model_terms(submission)
    context = metadata.get_context()
    _validate_context(context)
    for entity in metadata.get_objects():
        payload = entity.model_dump(mode="json", by_alias=True)
        types = (
            payload["@type"]
            if isinstance(payload["@type"], list)
            else [payload["@type"]]
        )
        if any(not _mapped(label, context) for label in types):
            raise ValueError(f"Unmapped @type label on {entity.id}")
        for name, value in payload.items():
            if name in ("@id", "@type"):
                continue
            if not _mapped(name, context):
                raise ValueError(
                    f"Unmapped field {name!r} on {entity.id}; supply a ContextTerm"
                )
            term = context.terms.get(name)
            _check_flat_value(
                value, json_literal=bool(term and term.type_mapping == "@json")
            )
    json.dumps(metadata.to_dict(), allow_nan=False)

    entity = metadata.get_file_list_entity()
    if not isinstance(entity, models.FileList) or file_list.ro_crate_id != entity.id:
        raise ValueError("File-list identity disagrees with the metadata graph")
    if sum(isinstance(o, models.FileList) for o in metadata.get_objects()) != 1:
        raise ValueError("Safe editing currently supports exactly one file list")
    table = metadata.get_object(entity.tableSchema.id)
    if not isinstance(table, models.TableSchema):
        raise ValueError("File-list tableSchema must reference a TableSchema")
    ids = [ref.id for ref in table.column]
    if len(ids) != len(set(ids)) or set(ids) != set(file_list.schema):
        raise ValueError("TableSchema columns and FileList.schema disagree")
    if not file_list.data.columns.is_unique or set(file_list.data.columns) != set(ids):
        raise ValueError("Dataframe columns and the selected schema must match exactly")
    names = []
    for column_id in ids:
        column = metadata.get_object(column_id)
        if not isinstance(column, models.Column):
            raise ValueError(f"Schema entry is not a Column: {column_id}")
        current = file_list.schema[column_id]
        if column_id != current.id or current.model_dump(
            mode="json", by_alias=True
        ) != column.model_dump(mode="json", by_alias=True):
            raise ValueError(
                f"Graph and file-list column definitions disagree: {column_id}"
            )
        if not column.columnName or any(c in column.columnName for c in "\t\r\n\x00"):
            raise ValueError(f"Invalid TSV column name: {column.columnName!r}")
        names.append(column.columnName)
        file_list.schema[column_id] = column
    if len(names) != len(set(names)):
        raise ValueError("Duplicate column names are not safe to serialize")


def metadata_graph(
    submission: BIASubmissionMetadata, base_path: Path | None = None
) -> Graph:
    base = (base_path or submission.metadata.get_base_path()).absolute()
    return Graph().parse(
        data=json.dumps(submission.metadata.to_dict(), allow_nan=False),
        format="json-ld",
        publicID=(base / "ro-crate-metadata.json").as_uri(),
    )


def _validate_relationships(submission: BIASubmissionMetadata) -> None:
    graph = metadata_graph(submission)
    subjects = set(graph.subjects())
    base_uri = (
        submission.metadata.get_base_path().absolute() / "ro-crate-metadata.json"
    ).as_uri()
    entity_subjects = set()
    for entity in submission.metadata.get_objects():
        subject = (
            BNode(entity.id[2:])
            if entity.id.startswith("_:")
            else URIRef(urljoin(base_uri, entity.id))
        )
        if subject in entity_subjects:
            raise ValueError(f"Entity IDs resolve to the same RDF subject: {entity.id}")
        entity_subjects.add(subject)
        if (subject, RDF.type, entity.get_model_type()) not in graph:
            raise ValueError(f"Context does not preserve the model type of {entity.id}")
    missing = set()
    for _, predicate, target in graph:
        if predicate in (RDF.type, DUBLINCORE.conformsTo):
            continue
        if predicate == RDF.rest and target == RDF.nil:
            continue
        if isinstance(target, (URIRef, BNode)) and target not in subjects:
            missing.add(str(target))
    if missing:
        raise ValueError(f"Undefined metadata references: {', '.join(sorted(missing))}")

    # Reuse the repository's actual file-list reference/type rules, rather than
    # introducing a second guessed relationship taxonomy.
    parser = TSVMetadataParser(submission.metadata)
    columns = parser._get_schema()
    data = submission.file_list.data.rename(
        columns=submission.file_list.get_column_names()
    )
    path_columns = [c for c in columns.values() if c.propertyUrl == str(BIA.filePath)]
    if len(path_columns) != 1:
        raise ValueError("Safe editing requires exactly one file-path column")
    paths = data[path_columns[0].columnName]
    if any(not isinstance(v, str) or not v for v in paths):
        raise ValueError("File paths must be nonempty strings")
    parser._validate_unique_file_paths(data, columns)
    parser._validate_reference_columns(data, columns)


def validate_submission(
    submission: BIASubmissionMetadata, *, references: bool = True
) -> None:
    """Revalidate models and complete context/schema links in an owned copy."""
    _validate_structure(submission)
    if references:
        _validate_relationships(submission)
