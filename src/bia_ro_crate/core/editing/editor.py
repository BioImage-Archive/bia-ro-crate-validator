"""Copy-on-edit operations across submission metadata and its file list."""

from collections.abc import Iterable, Mapping
from contextlib import contextmanager
from copy import deepcopy
from pathlib import Path
from typing import Any

import pandas as pd
from pandas.api.types import is_object_dtype

from bia_ro_crate.core.bia_submission_metadata import BIASubmissionMetadata
from bia_ro_crate.models import ro_crate_models as models
from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm
from bia_ro_crate.models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel

from .validation import validate_entity, validate_submission


def _copy_series(series: pd.Series) -> pd.Series:
    if is_object_dtype(series.dtype):
        return pd.Series(
            [deepcopy(value) for value in series],
            index=deepcopy(series.index),
            name=series.name,
            dtype=object,
        )
    return series.copy(deep=True)


def _copy_submission(submission: BIASubmissionMetadata) -> BIASubmissionMetadata:
    if not submission.file_list.data.columns.is_unique:
        raise ValueError("Duplicate dataframe column IDs")
    result = deepcopy(submission)
    # DataFrame.__deepcopy__ does NOT recursively copy Python objects in cells.
    for column in result.file_list.data.columns:
        if is_object_dtype(result.file_list.data[column].dtype):
            result.file_list.data[column] = _copy_series(result.file_list.data[column])
    return result


class SubmissionEditor:
    """Edit an isolated submission, validating each change before accepting it.

    Use transaction() for mutually dependent edits, snapshot() for a detached
    checked copy, and write_new() for parser/profile-validated metadata export.
    """

    def __init__(self, submission: BIASubmissionMetadata) -> None:
        self._state = _copy_submission(submission)
        self._revision = 0
        self._defer_relationships = False
        self._check(self._state)

    def _check(self, state: BIASubmissionMetadata) -> None:
        validate_submission(state, references=not self._defer_relationships)

    def _accept(self, state: BIASubmissionMetadata) -> None:
        self._check(state)
        self._state = state
        self._revision += 1

    def get_entity(self, entity_id: str) -> ROCrateModel:
        """Return a detached entity; changes require an explicit editing operation."""
        entity = self._state.metadata.get_object(entity_id)
        if entity is None:
            raise KeyError(entity_id)
        return deepcopy(entity)

    def add_entity(
        self, entity: ROCrateModel, *, context_terms: Iterable[ContextTerm] = ()
    ) -> None:
        """Add a validated entity and its explicit context mappings together."""
        candidate = _copy_submission(self._state)
        candidate.metadata.get_context().add_terms(context_terms)
        candidate.metadata.add_entity(validate_entity(entity))
        self._accept(candidate)

    def update_entity(
        self,
        entity_id: str,
        changes: Mapping[str, Any],
        *,
        context_terms: Iterable[ContextTerm] = (),
    ) -> None:
        """Replace fields without changing identity or dropping unmapped extras."""
        if not isinstance(changes, Mapping):
            raise TypeError("changes must be a field/value mapping")
        if set(changes) & {"@id", "id", "@type", "type"}:
            raise ValueError("Changing entity identity/type is not supported")
        candidate = _copy_submission(self._state)
        entity = candidate.metadata.get_object(entity_id)
        if entity is None:
            raise KeyError(entity_id)
        if isinstance(entity, models.FileList) and "tableSchema" in changes:
            raise ValueError("Schema reassignment needs a dedicated migration")
        if isinstance(entity, models.TableSchema) and "column" in changes:
            raise ValueError("Use add_file_list_column to change the selected schema")
        payload = entity.model_dump(mode="python", by_alias=True)
        payload.update(deepcopy(dict(changes)))
        updated = type(entity).model_validate(payload)
        candidate.metadata.get_context().add_terms(context_terms)
        candidate.metadata.update_entity(updated)
        if entity_id in candidate.file_list.schema:
            candidate.file_list.schema[entity_id] = updated
        self._accept(candidate)

    def add_file_list_column(
        self,
        column: models.Column,
        data: list | pd.Series,
        *,
        context_terms: Iterable[ContextTerm] = (),
    ) -> None:
        """Add data, schema, Column and TableSchema links as one checked edit.

        Lists are positional; Series must have the same unique row labels.
        Caller-owned models and nested cell values are copied.
        """
        if not isinstance(column, models.Column):
            raise TypeError("column must be a Column")
        if not isinstance(data, (list, pd.Series)):
            raise TypeError("data must be a positional list or an index-aligned Series")
        candidate = _copy_submission(self._state)
        column = validate_entity(column)
        frame = candidate.file_list.data
        if len(data) != len(frame):
            raise ValueError(f"New column has {len(data)} rows; expected {len(frame)}")
        if column.id in candidate.metadata.get_object_lookup():
            raise ValueError(f"Entity with id {column.id} already exists")
        if column.columnName in candidate.file_list.get_column_names().values():
            raise ValueError(f"Column name already exists: {column.columnName}")
        if isinstance(data, pd.Series):
            if not frame.index.is_unique or not data.index.is_unique:
                raise ValueError("Series alignment requires unique row labels")
            if len(data.index.difference(frame.index)) or len(
                frame.index.difference(data.index)
            ):
                raise ValueError("Series row labels do not match the dataframe")
            values = _copy_series(data.reindex(frame.index))
        else:
            # Avoid implicit float inference losing integer precision in mixed lists.
            values = pd.Series(deepcopy(data), index=frame.index, dtype=object)
        candidate.metadata.get_context().add_terms(context_terms)
        candidate.file_list.add_column(column, values)
        candidate.metadata.add_entity(column)
        table_id = candidate.metadata.get_file_list_entity().tableSchema.id
        table = candidate.metadata.get_object(table_id)
        payload = table.model_dump(mode="python", by_alias=True)
        payload["column"].append({"@id": column.id})
        candidate.metadata.update_entity(type(table).model_validate(payload))
        self._accept(candidate)

    @contextmanager
    def transaction(self):
        """Commit an isolated group or leave the parent editor unchanged."""
        if self._defer_relationships:
            raise ValueError("Nested transactions are not supported")
        child = SubmissionEditor(self._state)
        child._defer_relationships = True
        revision = self._revision
        try:
            yield child
            result = child.snapshot()
            if self._revision != revision:
                raise RuntimeError(
                    "Parent editor changed while the transaction was open"
                )
            self._state = result
            self._revision += 1
        finally:
            child._defer_relationships = False

    def snapshot(self) -> BIASubmissionMetadata:
        """Return a detached, checked copy; full profile validation runs on export."""
        result = _copy_submission(self._state)
        validate_submission(result)
        return result

    def write_new(self, destination: Path | str) -> Path:
        """Validate and export metadata plus one TSV into a new directory.

        Payload files are excluded. The parent must be trusted and single-writer;
        publication is exclusive but not crash-atomic. Lossy or invalid data is
        rejected before output creation. A cleanup failure is attached to the
        original publication error.
        """
        from .export import write_submission

        return write_submission(self.snapshot(), Path(destination))
