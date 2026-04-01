import pandas as pd
from models.ro_crate_models import Column


class FileList:
    """
    A file list is a columnar metadata container describing other files in an ro-crate.
    It is made up of the data about the other files (data), and a schema (a dictionary of Column objects, keyed by id).
    Its schema is usually described in the ro-crate-metadata.json, using a csvw:TableSchema object to hold a set of csvw:Column objects.
    """

    ro_crate_id: str | None
    schema: dict[str, Column]
    data: pd.DataFrame
    FILE_LIST_ID_COL: str = "_filelist_id"
    PROPERTYLESS_COLUMNS: str = "_propertyless_columns"
    DATASET_COLUMN_ID: str = "_part_of_dataset"

    def __init__(
        self,
        schema: dict[str, Column],
        data: pd.DataFrame,
        ro_crate_id: str | None = None,
        strict: bool = False,
    ) -> None:
        self.ro_crate_id = ro_crate_id

        self._validate_schema_dict(schema)
        schema_name_map = self._column_map('columnName', 'id')
        self._validate_column_defitions(schema_name_map, data.columns, strict)
        column_id_map = {
            col_name: schema_name_map[col_name] for col_name in data.columns
        }
        self.data = data.rename(columns=column_id_map)

        super().__init__()

    def _column_map(self, key: str, value: str) -> dict:
        return {getattr(col, key): getattr(col, value) for col in self.schema.values()}

    def _validate_schema_dict(self, schema: dict[str, Column]):
        if not all(key == column.id for key, column in schema.items()):
            raise KeyError(
                "Schema dictionary must have keys that are the IDs of the column objects"
            )
        self.schema = schema

    def _validate_column_defitions(
        self, schema_name_map: dict[str, str], data_columns: pd.Index, strict: bool
    ):
        if strict:
            if list(schema_name_map.keys()) != list(data_columns):
                raise ValueError("Schema does not match data columns")

        missing = set(data_columns) - schema_name_map.keys()
        if missing:
            raise ValueError(
                f"Schema does not contain columns with names that match data columns: {missing}"
            )

    def get_column_id_by_property(self, propertyUrl) -> str | None:
        return next(
            (column.id for column in self.schema.values() if column.propertyUrl == propertyUrl),
            None,
        )

    def get_column_properties(self) -> dict[str, None | str]:
        return self._column_map('id', 'propertyUrl')

    def get_column_names(self) -> dict[str, str]:
        return self._column_map('id', 'columnName')

    def add_column(self, columnDefinition: Column, data: list | pd.Series):
        if len(data) != len(self.data):
            raise ValueError(
                f"Data is not of correct length to map to file list. Expected: {len(self.data)}, found: {len(data)}"
            )

        if columnDefinition.id in self.schema:
            raise ValueError(f"Column with id: {columnDefinition.id} already exists.")

        self.data[columnDefinition.id] = data
        self.schema[columnDefinition.id] = columnDefinition
