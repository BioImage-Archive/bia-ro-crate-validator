from rdflib import URIRef

from ..ld_context.ContextTerm import ContextTerm


class FieldContext:
    uri: URIRef
    is_id_field: bool
    is_reverse_field: bool

    def __init__(
        self, uri: str | URIRef, is_id_field: bool = False, is_reverse_field=False
    ):
        self.uri = URIRef(str(uri))
        self.is_id_field = is_id_field
        self.is_reverse_field = is_reverse_field

    def to_context_term(self, field_name: str) -> ContextTerm:
        type_mapping = None
        if self.is_id_field:
            type_mapping = "@id"
        return ContextTerm(
            full_uri=self.uri,
            field_name=field_name,
            is_reverse=self.is_reverse_field,
            type_mapping=type_mapping,
        )
