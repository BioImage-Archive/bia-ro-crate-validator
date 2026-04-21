from pathlib import Path

import pandas as pd
from bia_ro_crate.core.file_list import FileList
from bia_ro_crate.core.parser.osv_metadata_parser import OSVMetadataParser


class TSVMetadataParser(OSVMetadataParser):
    def parse(self, target: Path | str | None = None) -> None:
        self._set_file_list_path_and_id(target)

        columns = self._get_schema()

        data = pd.read_csv(self._file_list_path, delimiter="\t")

        self._expand_list_columns(data, columns)

        self._validate_reference_columns(data, columns)

        self._result = FileList(
            ro_crate_id=self._file_list_id, schema=columns, data=data
        )
