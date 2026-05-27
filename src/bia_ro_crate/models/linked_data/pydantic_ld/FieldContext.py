from rdflib import URIRef

from bia_ro_crate.models.linked_data.ld_context.ContextTerm import ContextTerm


class FieldContext:
    uri: URIRef
    is_id_field: bool
    is_reverse_field: bool
    container: str | None

    def __init__(
        self, uri: str | URIRef, is_id_field: bool = False, is_reverse_field=False
        , container: str | None = None
    ):
        self.uri = URIRef(str(uri))
        self.is_id_field = is_id_field
        self.is_reverse_field = is_reverse_field
        self.container = container

    def to_context_term(self, field_name: str) -> ContextTerm:
        type_mapping = None
        if self.is_id_field:
            type_mapping = "@id"
        return ContextTerm(
            full_uri=self.uri,
            field_name=field_name,
            is_reverse=self.is_reverse_field,
            type_mapping=type_mapping,
            container=self.container,
        )
