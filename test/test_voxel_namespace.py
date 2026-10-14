import json
import warnings
from inspect import get_annotations
from pathlib import Path

import pandas as pd
import pytest
from rdflib import URIRef

from bia_ro_crate.core.parser.ro_crate_parser import ROCrateParser
from bia_ro_crate.models.linked_data.ontology_terms import BIA

VOXEL_TERMS = ("voxelSizeX", "voxelSizeY", "voxelSizeZ")


@pytest.mark.parametrize("name", VOXEL_TERMS)
def test_voxel_terms_are_declared_and_resolve_without_warnings(name):
    expected = URIRef(f"http://bia/{name}")
    assert get_annotations(BIA).get(name) is URIRef
    assert name in BIA
    assert expected in BIA
    with warnings.catch_warnings():
        warnings.simplefilter("error", UserWarning)
        assert getattr(BIA, name) == expected
        assert BIA[name] == expected


def test_voxel_columns_preserve_values_through_crate_parsing(tmp_path):
    source = Path(__file__).parent / "validator/input_ro_crate/test_typical_ro_crate"
    metadata_path = tmp_path / "ro-crate-metadata.json"
    metadata = json.loads((source / metadata_path.name).read_text())
    schema = next(entity for entity in metadata["@graph"] if "column" in entity)
    file_list_path = tmp_path / "file_list.tsv"
    frame = pd.read_csv(source / file_list_path.name, sep="\t")
    assert not frame.empty

    for index, name in enumerate(VOXEL_TERMS, start=1):
        column_id = f"#column-{name}"
        schema["column"].append({"@id": column_id})
        with warnings.catch_warnings():
            warnings.simplefilter("error", UserWarning)
            property_url = str(BIA[name])
        metadata["@graph"].append(
            {
                "@id": column_id,
                "@type": "csvw:Column",
                "columnName": name,
                "propertyUrl": property_url,
            }
        )
        frame[name] = [index * (row + 1) * 1.25e-7 for row in range(len(frame))]

    metadata_path.write_text(json.dumps(metadata))
    frame.to_csv(file_list_path, sep="\t", index=False)
    before = file_list_path.read_bytes()

    parser = ROCrateParser(tmp_path)
    parser.parse()
    file_list = parser.result.file_list
    for name in VOXEL_TERMS:
        column_id = file_list.get_column_id_by_property(f"http://bia/{name}")
        assert column_id == f"#column-{name}"
        pd.testing.assert_series_equal(
            file_list.data[column_id],
            frame[name],
            check_names=False,
            rtol=1e-12,
            atol=0,
        )
    assert file_list_path.read_bytes() == before
