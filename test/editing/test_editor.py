import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from bia_ro_crate.models import ro_crate_models as models
from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm


def test_column_addition_updates_all_representations_without_aliasing(
    submission, new_column
):
    original = submission.metadata.to_dict()
    editor = submission.editor()
    values = [2**60 + 1] + [None] * (len(submission.file_list.data) - 1)
    expected = values.copy()
    editor.add_column(new_column, values)
    values[0] = 0
    new_column.columnName = "caller mutation"
    result = editor.snapshot()
    identifier = "#voxel-x"
    assert result.file_list.data[identifier].tolist() == expected
    assert result.file_list.data[identifier].dtype == object
    assert result.file_list.schema[identifier].columnName == "voxel_x"
    assert result.metadata.get_object(identifier) == result.file_list.schema[identifier]
    table_id = result.metadata.get_file_list_entity().tableSchema.id
    assert result.metadata.get_object(table_id).column[-1].id == identifier
    assert_frame_equal(
        result.file_list.data.drop(columns=identifier), submission.file_list.data
    )
    assert submission.metadata.to_dict() == original
    assert identifier not in submission.file_list.schema
    list_column = submission.file_list.get_column_id_by_property(
        "http://bia/associatedAnnotationMethod"
    )
    row = next(i for i, value in result.file_list.data[list_column].items() if value)
    result.file_list.data.at[row, list_column].append("detached")
    assert (
        editor.snapshot().file_list.data.at[row, list_column]
        != result.file_list.data.at[row, list_column]
    )
    entity = editor.get_entity(identifier)
    entity.columnName = "detached"
    assert editor.get_entity(identifier).columnName == "voxel_x"


def test_series_alignment_and_column_definition_stay_consistent(submission, new_column):
    editor = submission.editor()
    frame = submission.file_list.data
    values = pd.Series(range(len(frame)), index=frame.index[::-1], dtype="int64")
    editor.add_column(new_column, values)
    editor.update_entity(new_column.id, {"columnName": "measurement"})
    result = editor.snapshot()
    assert (
        result.file_list.data[new_column.id].tolist()
        == values.reindex(frame.index).tolist()
    )
    assert result.file_list.data[new_column.id].dtype == values.dtype
    assert result.file_list.schema[new_column.id].columnName == "measurement"
    assert result.metadata.get_object(new_column.id).columnName == "measurement"


@pytest.mark.parametrize(
    "operation",
    [
        "length",
        "labels",
        "collision",
        "identity",
        "schema",
        "model",
        "mapping",
        "reference",
    ],
)
def test_rejected_edits_preserve_the_whole_submission(
    submission, new_column, operation
):
    editor = submission.editor()
    before = editor.snapshot()
    with pytest.raises((ValueError, TypeError)):
        if operation == "length":
            editor.add_column(new_column, [])
        elif operation == "labels":
            editor.add_column(
                new_column,
                pd.Series(
                    range(len(before.file_list.data)),
                    index=range(100, 100 + len(before.file_list.data)),
                ),
            )
        elif operation == "collision":
            editor.add_column(
                new_column.model_copy(update={"id": "./"}),
                [0] * len(before.file_list.data),
            )
        elif operation == "identity":
            editor.update_entity("./", {"id": "#renamed"})
        elif operation == "schema":
            editor.update_entity(
                before.metadata.get_file_list_entity().tableSchema.id, {"column": []}
            )
        elif operation == "model":
            editor.update_entity("./", {"name": []})
        elif operation == "mapping":
            editor.update_entity("./", {"unmapped": "must not disappear"})
        else:
            editor.update_entity("./", {"hasPart": [{"@id": "#missing"}]})
    after = editor.snapshot()
    assert after.metadata.to_dict() == before.metadata.to_dict()
    assert after.file_list.schema == before.file_list.schema
    assert_frame_equal(after.file_list.data, before.file_list.data, check_exact=True)


@pytest.mark.parametrize("value", [float("nan"), {"nested": [{1: "value"}]}])
def test_json_conversion_cannot_silently_change_metadata(submission, value):
    editor = submission.editor()
    before = editor.snapshot().metadata.to_dict()
    term = ContextTerm("https://example.org/note", "note", type_mapping="@json")
    with pytest.raises(ValueError):
        editor.update_entity("./", {"note": value}, context_terms=[term])
    assert editor.snapshot().metadata.to_dict() == before


def test_mutated_models_are_revalidated_on_entry(submission):
    invalid = submission.metadata.get_object("./").model_copy(update={"name": []})
    submission.metadata.update_entity(invalid)
    with pytest.raises(ValueError):
        submission.editor()


def test_context_additions_preserve_extras_and_reject_semantic_conflicts(submission):
    submission.metadata.get_context().remove_term("name")
    editor = submission.editor()
    term = ContextTerm("https://example.org/note", "note")
    editor.update_entity("./", {"note": "Retain"}, context_terms=[term])
    editor.update_entity("./", {"name": "Reviewed study"})
    assert editor.get_entity("./").note == "Retain"
    assert (
        str(editor.snapshot().metadata.get_context().terms["name"].full_uri)
        == "http://schema.org/name"
    )
    conflict = ContextTerm(term.full_uri, "note", container="@set")
    with pytest.raises(ValueError, match="Context mapping conflict"):
        editor.update_entity("./", {"note": "Changed"}, context_terms=[conflict])
    assert editor.get_entity("./").note == "Retain"


def test_transaction_resolves_forward_references_and_detaches_the_draft(submission):
    editor = submission.editor()
    dataset = models.Dataset(**{"@id": "#new", "@type": "bia:Dataset", "name": "New"})
    with editor.transaction() as draft:
        draft.update_entity("./", {"hasPart": [{"@id": "#new"}]})
        draft.add_entity(dataset)
    draft.update_entity("#new", {"name": "Later change"})
    dataset.name = "Caller change"
    assert editor.get_entity("#new").name == "New"
    assert submission.metadata.get_object("#new") is None


@pytest.mark.parametrize("failure", ["reference", "exception", "nested"])
def test_failed_transactions_leave_the_parent_unchanged(submission, failure):
    editor = submission.editor()
    before = editor.snapshot().metadata.to_dict()
    with pytest.raises((ValueError, RuntimeError)):
        with editor.transaction() as draft:
            draft.update_entity("./", {"name": "Draft"})
            if failure == "reference":
                draft.update_entity("./", {"hasPart": [{"@id": "#missing"}]})
            elif failure == "exception":
                raise RuntimeError("abort")
            else:
                with draft.transaction():
                    pass
    assert editor.snapshot().metadata.to_dict() == before


def test_transaction_cannot_overwrite_an_intervening_parent_edit(submission):
    editor = submission.editor()
    with pytest.raises(RuntimeError, match="Parent editor changed"):
        with editor.transaction() as draft:
            draft.update_entity("./", {"name": "Draft"})
            editor.update_entity("./", {"name": "Parent"})
    assert editor.get_entity("./").name == "Parent"
