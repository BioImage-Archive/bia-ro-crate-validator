import csv
import json
import shutil
from pathlib import Path

import pytest

from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser


@pytest.fixture
def crate(tmp_path: Path) -> Path:
    source = (
        Path(__file__).parent / "validator/input_ro_crate/test_minimal_valid_ro_crate"
    )
    shutil.copytree(source, tmp_path, dirs_exist_ok=True)
    return tmp_path


def write_paths(crate: Path, paths: list[str], column_name: str = "file_path") -> None:
    with (crate / "file_list.tsv").open("w", newline="") as file:
        writer = csv.writer(file, delimiter="\t")
        writer.writerow([column_name, "dataset"])
        writer.writerows((path, "") for path in paths)


@pytest.mark.parametrize(
    "path",
    ["folder/image 01.tiff", "a!*'()-_.txt", "001", "NA"],
)
def test_valid_file_paths_are_preserved(crate: Path, path: str) -> None:
    write_paths(crate, [path])
    parser = ROCrateParser(crate)
    parser.parse()
    file_list = parser.result.file_list
    column = file_list.get_column_id_by_property("http://bia/filePath")
    assert file_list.data[column].tolist() == [path]


@pytest.mark.parametrize(
    "path, detail",
    [
        ("", "the path must not be empty"),
        ("file~name", "unsupported character(s): '~'"),
        ("file|name", "unsupported character(s): '|'"),
        ("a@b[1]\\file", "unsupported character(s): '@', '[', ']', '\\\\'"),
        ("folder/", "the file path must not be a directory"),
        ("café", "unsupported character(s): 'é'"),
        ("file\n", r"unsupported character(s): '\n'"),
        ("bad~|~file", "unsupported character(s): '~', '|'"),
    ],
)
def test_invalid_file_paths_are_reported(crate: Path, path: str, detail: str) -> None:
    write_paths(crate, [path])
    parser = ROCrateParser(crate)
    with pytest.raises(ExceptionGroup):
        parser.parse()
    issues = [issue for issue in parser.issues if "Invalid file path" in issue.message]
    assert len(issues) == 1
    assert repr(path) in issues[0].message
    assert detail in issues[0].message
    assert "row 2, column file_path" in issues[0].location_description


def test_multiple_invalid_paths_and_schema_column_name(crate: Path) -> None:
    metadata_path = crate / "ro-crate-metadata.json"
    metadata = json.loads(metadata_path.read_text())
    for entity in metadata["@graph"]:
        if entity.get("propertyUrl") == "http://bia/filePath":
            entity["columnName"] = "path"
    metadata_path.write_text(json.dumps(metadata))
    write_paths(crate, ["ok/file", "bad~file", "bad|file"], "path")
    parser = ROCrateParser(crate)
    with pytest.raises(ExceptionGroup):
        parser.parse()
    issues = [issue for issue in parser.issues if "Invalid file path" in issue.message]
    assert len(issues) == 2
    assert "row 3, column path" in issues[0].location_description
    assert "row 4, column path" in issues[1].location_description


def test_valid_path_after_unsafe_path_has_no_containment_error(crate: Path) -> None:
    write_paths(crate, ["../outside.tif", "inside.tif"])
    parser = ROCrateParser(crate)
    with pytest.raises(ExceptionGroup):
        parser.parse()
    issues = [
        issue for issue in parser.issues if "outside the RO-Crate" in issue.message
    ]
    assert len(issues) == 1
    assert "row 2" in issues[0].location_description


@pytest.mark.parametrize(
    "path",
    [
        "../bad/file.tif",
        "folder/../../bad/file.tif",
    ],
)
def test_unsafe_paths_are_rejected(crate: Path, path: str):
    write_paths(crate, [path])
    parser = ROCrateParser(crate)
    with pytest.raises(ExceptionGroup):
        parser.parse()
    issues = [
        issue for issue in parser.issues if "outside the RO-Crate" in issue.message
    ]
    assert len(issues) == 1
    assert repr(path) in issues[0].message
    assert "row 2, column file_path" in issues[0].location_description


@pytest.mark.parametrize(
    "path",
    ["folder/file.tif", "./file.tif", "folder/.../file.tif", "folder/../file.tif"],
)
def test_safe_relative_paths_are_accepted(crate: Path, path: str):
    write_paths(crate, [path])
    parser = ROCrateParser(crate)
    parser.parse()


@pytest.mark.parametrize("inside", [True, False])
def test_absolute_paths_are_checked_against_crate_directory(crate: Path, inside: bool):
    path = (crate if inside else crate.parent) / "file.tif"
    write_paths(crate, [str(path)])
    parser = ROCrateParser(crate)
    if inside:
        parser.parse()
    else:
        with pytest.raises(ExceptionGroup):
            parser.parse()
        assert any("outside the RO-Crate" in issue.message for issue in parser.issues)
