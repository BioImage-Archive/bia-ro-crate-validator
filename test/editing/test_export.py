import shutil
from fractions import Fraction
from pathlib import Path

import pandas as pd
import pytest

from bia_ro_crate.core.editing import export
from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm


@pytest.mark.parametrize(
    "fixture", ["test_minimal_valid_ro_crate", "test_typical_ro_crate"]
)
def test_edit_export_and_reparse_preserve_metadata_and_all_column_links(
    fixture, parsed_submission, new_column, tmp_path
):
    if fixture == "test_typical_ro_crate":
        original = parsed_submission
    else:
        parser = ROCrateParser(
            Path(__file__).parents[1] / "validator/input_ro_crate" / fixture
        )
        parser.parse()
        original = parser.result
    before = original.metadata.to_dict()
    editor = original.editor()
    values = [0.25] * len(original.file_list.data)
    editor.add_file_list_column(new_column, values)
    editor.update_entity(
        "./",
        {"name": "Reviewed study", "curationNote": "Retain this note"},
        context_terms=[
            ContextTerm(
                "https://example.org/curation-note",
                "curationNote",
                type_mapping="http://www.w3.org/2001/XMLSchema#string",
            )
        ],
    )
    destination = editor.write_new(tmp_path / "export")
    parser = ROCrateParser(destination)
    parser.parse()
    result = parser.result
    assert result.file_list.data[new_column.id].tolist() == values
    assert result.file_list.schema[new_column.id] == new_column
    assert result.metadata.get_object(new_column.id) == new_column
    table = result.metadata.get_object(
        result.metadata.get_file_list_entity().tableSchema.id
    )
    assert new_column.id in [column.id for column in table.column]
    assert result.metadata.get_object("./").name == "Reviewed study"
    assert result.metadata.get_object("./").curationNote == "Retain this note"
    assert (
        result.metadata.get_context().terms["curationNote"].type_mapping
        == "http://www.w3.org/2001/XMLSchema#string"
    )
    assert original.metadata.to_dict() == before
    assert new_column.id not in original.file_list.schema
    assert {path.name for path in destination.iterdir()} == {
        "file_list.tsv",
        "ro-crate-metadata.json",
    }


@pytest.mark.parametrize("value", ["001", 2**60 + 1, Fraction(1, 3)])
def test_lossy_tsv_conversion_is_rejected_before_publication(
    submission, new_column, value, tmp_path
):
    editor = submission.editor()
    editor.add_file_list_column(
        new_column, [value] + [None] * (len(submission.file_list.data) - 1)
    )
    with pytest.raises(
        ValueError, match="File-list (values changed|number cannot be represented)"
    ):
        editor.write_new(tmp_path / "export")
    assert not list(tmp_path.iterdir())


def test_nullable_boolean_columns_preserve_values_and_missing_cells(
    submission, new_column, tmp_path
):
    column = new_column.model_copy(
        update={
            "id": "#reviewed",
            "columnName": "reviewed",
            "propertyUrl": "https://example.org/reviewed",
        }
    )
    frame = submission.file_list.data
    values = pd.Series(
        [True, False] + [pd.NA] * (len(frame) - 2),
        index=frame.index,
        dtype="boolean",
    )
    editor = submission.editor()
    editor.add_file_list_column(column, values)
    assert editor.snapshot().file_list.data[column.id].dtype == values.dtype
    destination = editor.write_new(tmp_path / "export")
    parser = ROCrateParser(destination)
    parser.parse()
    actual = parser.result.file_list.data[column.id]
    assert actual.iloc[:2].tolist() == [True, False]
    assert actual.iloc[2:].isna().all()


def test_boolean_roundtrip_comparisons_do_not_accept_numeric_substitutes():
    value = pd.Series([True], dtype="boolean").iloc[0]
    assert export._same_value(value, True)
    assert not export._same_value(value, 1)
    assert not export._same_value(1, value)


def test_existing_profile_still_rejects_invalid_metadata(submission, tmp_path):
    editor = submission.editor()
    author = editor.get_entity("./").author[0].id
    editor.update_entity("ro-crate-metadata.json", {"about": {"@id": author}})
    with pytest.raises(ExceptionGroup):
        editor.write_new(tmp_path / "export")
    assert not list(tmp_path.iterdir())


def test_existing_destination_and_source_crate_are_never_modified(submission, tmp_path):
    destination = tmp_path / "existing"
    destination.mkdir()
    sentinel = destination / "sentinel"
    sentinel.write_text("retain")
    editor = submission.editor()
    with pytest.raises(FileExistsError):
        editor.write_new(destination)
    with pytest.raises(ValueError, match="source crate"):
        editor.write_new(submission.metadata.get_base_path() / "export")
    assert sentinel.read_text() == "retain"
    assert list(tmp_path.iterdir()) == [destination]


def test_publication_failure_removes_only_its_owned_output(
    submission, tmp_path, monkeypatch
):
    sentinel = tmp_path / "sentinel"
    sentinel.write_text("retain")
    copy = shutil.copyfileobj
    calls = 0

    def fail_metadata_copy(source, destination):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("disk write failed")
        return copy(source, destination)

    monkeypatch.setattr(export.shutil, "copyfileobj", fail_metadata_copy)
    with pytest.raises(OSError, match="disk write failed"):
        submission.editor().write_new(tmp_path / "export")
    assert calls == 2
    assert sentinel.read_text() == "retain"
    assert list(tmp_path.iterdir()) == [sentinel]


@pytest.mark.parametrize(
    "identifier",
    [
        "%2e%2e/out.tsv",
        "https://example.org/file.tsv",
        "RO-CRATE-METADATA.JSON",
        "CON.tsv",
        "file.tsv#",
    ],
)
def test_manifest_paths_cannot_escape_or_alias_owned_outputs(submission, identifier):
    submission.metadata.get_file_list_entity().id = identifier
    with pytest.raises(ValueError):
        export._manifest_relative_path(submission)
