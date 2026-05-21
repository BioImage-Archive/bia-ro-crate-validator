import json
from pathlib import Path
from typing import Annotated, Union

from pydantic import AfterValidator, Field, field_validator
from rdflib import Graph, URIRef

from bia_ro_crate.models.linked_data.ld_context.SimpleJSONLDContext import (
    SimpleJSONLDContext,
)
from bia_ro_crate.models.linked_data.pydantic_ld.LDModel import LDModel
from bia_ro_crate.models.linked_data.pydantic_ld.utils import id_validate


class ROCrateModel(LDModel):
    id: Annotated[str, AfterValidator(id_validate)] = Field(alias="@id")
    type: Union[str, list[str]] = Field(alias="@type")

    @classmethod
    def get_model_type(cls) -> URIRef:
        required_type = cls.model_config.get("model_type")
        return URIRef(required_type)

    @field_validator("type", mode="after")
    @classmethod
    def includes_expected_type(
        cls, value: Union[str, list[str]]
    ) -> Union[str, list[str]]:
        """
        Note, this assume the object has either been expanded to have full urls for the types, or the standard bia context is being used. The actual document context is not checked.
        """
        expected_class: str = str(cls.model_config.get("model_type"))
        short_string = (
            expected_class.replace("http://www.w3.org/ns/csvw#", "csvw:")
            .replace("http://bia/", "bia:")
            .replace("http://schema.org/", "")
            .replace("https://schema.org/", "")
        )

        if isinstance(value, str):
            if value != expected_class and value != short_string:
                raise ValueError(
                    f"Expected {expected_class}, or {short_string} in types, found: {value}"
                )
        else:
            if expected_class not in value and short_string not in value:
                raise ValueError(
                    f"Expected {expected_class}, or {short_string} in types, found: {value}"
                )

        return value

    def to_graph(self, context: SimpleJSONLDContext, base_path: Path) -> Graph:
        graph = Graph()

        json_ld = {
            "@context": context.to_dict(),
            "@graph": [self.model_dump(mode="json", by_alias=True)],
        }
        json_ld_string = json.dumps(json_ld)

        base_file_uri = str(base_path.as_uri())
        graph.parse(data=json_ld_string, format="json-ld", publicID=f"{base_file_uri}")

        return graph

    def __hash__(self):
        return hash(self.id)
