from pathlib import Path

import pandas as pd

from bia_ro_crate.core.file_list import FileList
from bia_ro_crate.core.parser.osv_metadata_parser import OSVMetadataParser


class TSVMetadataParser(OSVMetadataParser):
    def parse(self, target: Path | str | None = None) -> None:
        self._set_file_list_path_and_id(target)

        columns = self._get_schema()

        file_path_column = columns[self._file_path_column_id].columnName
        data = pd.read_csv(
            self._file_list_path,
            delimiter="\t",
            converters={file_path_column: lambda value: value},
        )

        self._validate_file_path_containment(data, columns)
        self._validate_file_path_characters(data, columns)
        self._validate_unique_file_paths(data, columns)

        self._expand_list_columns(data, columns)

        self._validate_reference_columns(data, columns)

        self._result = FileList(
            ro_crate_id=self._file_list_id, schema=columns, data=data
        )
