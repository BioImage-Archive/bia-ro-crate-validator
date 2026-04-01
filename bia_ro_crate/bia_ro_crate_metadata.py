from collections import defaultdict
from operator import attrgetter
from pathlib import Path
from typing import Iterable

from models.linked_data.ld_context.SimpleJSONLDContext import (
    SimpleJSONLDContext,
)
from models.linked_data.pydantic_ld.ROCrateModel import ROCrateModel
from models.ro_crate_models import FileList
from rdflib import Graph


class BIAROCrateMetadata:
    _graph_bia_entities: dict[str, ROCrateModel]
    _context: SimpleJSONLDContext
    _base_path: Path
    _metadata_path: Path
    _file_list_id: str
    DEFAULT_RO_CRATE_FILENAME: str = "ro-crate-metadata.json"

    def __init__(
        self,
        graph_bia_entities: dict[str, ROCrateModel],
        context: SimpleJSONLDContext,
        base_path: Path,
        file_list_id: str | None = None,
    ) -> None:
        self._graph_bia_entities = graph_bia_entities
        self._context = context
        self._base_path = base_path
        self._metadata_path = base_path / self.DEFAULT_RO_CRATE_FILENAME

        if file_list_id:
            if file_list_id not in graph_bia_entities:
                raise ValueError(
                    f"File list with ID {file_list_id} not found in graph entities."
                )
            self._file_list_id = file_list_id
        else:
            file_lists = self.get_objects_by_type()[FileList]
            if (file_list_count := len(file_lists)) != 1:
                raise ValueError(
                    f"Found unexpected number of file lists: {file_list_count}"
                )
            self._file_list_id = next(iter(file_lists))

    def to_graph(self) -> Graph:
        graph = Graph()

        for entity in self._graph_bia_entities.values():
            graph += entity.to_graph(self._context, self._metadata_path)

        return graph

    def to_dict(self) -> dict:
        context_dict = self._context.to_dict()

        graph_objects = [
            entity.model_dump(by_alias=True, mode='json')
            for entity in sorted(
                self._graph_bia_entities.values(), key=attrgetter('id')
            )
        ]

        return {"@context": context_dict, "@graph": graph_objects}

    def get_context(self) -> SimpleJSONLDContext:
        return self._context

    def get_objects(self) -> Iterable[ROCrateModel]:
        return self._graph_bia_entities.values()

    def get_object_lookup(self) -> dict[str, ROCrateModel]:
        return self._graph_bia_entities

    def get_object(self, id: str) -> ROCrateModel | None:
        return self._graph_bia_entities.get(id)

    def get_base_path(self) -> Path:
        return self._base_path

    def get_objects_by_type(
        self,
    ) -> dict[type, dict[str, ROCrateModel]]:
        """
        Returns a dictionary of the form:
        {
            "type_A": {
                "id_a": <Object of type: type_A with id: id_a>
            }
        }
        """
        objects_by_type = defaultdict(dict)
        for object_id, bia_object in self._graph_bia_entities.items():
            objects_by_type[type(bia_object)][object_id] = bia_object

        return objects_by_type

    def get_file_list_entity(self):
        return self._graph_bia_entities[self._file_list_id]
