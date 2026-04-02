import re

import pandas as pd
from bia_ro_crate.models.linked_data.ontology_terms import BIA
from bia_ro_crate.models.ro_crate_models import Column
from bia_ro_crate.core.bia_ro_crate_metadata import BIAROCrateMetadata
from bia_ro_crate.core.parser.file_list_parser import FileListParser


class OSVMetadataParser(FileListParser):
    """
    Generic parser for operator separated value (e.g. csv, tsv) file lists:
    i.e. structured files who's schema is described in the ro-crate metadata.json
    """

    DEFAULT_LIST_PROPERTIES = [
        str(BIA.associatedBiologicalEntity),
        str(BIA.associatedImagingPreparationProtocol),
        str(BIA.associatedImageAcquisitionProtocol),
        str(BIA.associatedAnnotationMethod),
        str(BIA.associatedProtocol),
        str(BIA.associatedSourceImage),
    ]

    def __init__(
        self,
        ro_crate_metadata: BIAROCrateMetadata,
        *,
        context: dict | None = None,
    ) -> None:

        multivalued_properties_key = "multivalued_properties"
        if context and multivalued_properties_key in context:
            if not isinstance(context[multivalued_properties_key], list):
                raise TypeError(
                    f"{multivalued_properties_key} in context should be a list (of string or URIRefs of the properties)"
                )
            self.multivalued_properties = [
                str(list_property)
                for list_property in context[multivalued_properties_key]
            ]
        else:
            self.multivalued_properties = self.DEFAULT_LIST_PROPERTIES

        super().__init__(ro_crate_metadata=ro_crate_metadata, context=context)

    def _expand_list_columns(
        self, data: pd.DataFrame, columns: dict[str, Column]
    ) -> None:
        split_re = re.compile(r"\s*,\s*")

        def _expand_array_cells(value):
            if not isinstance(value, str) or not value.strip():
                return []
            value = value.strip().strip("[] ")
            parts = split_re.split(value)
            clean_list_value = [
                reference.strip().strip("\"'")
                for reference in parts
                if reference.strip()
            ]
            return clean_list_value

        for column in columns.values():
            if column.propertyUrl in self.multivalued_properties:
                data[column.columnName] = data[column.columnName].apply(
                    _expand_array_cells,
                )
