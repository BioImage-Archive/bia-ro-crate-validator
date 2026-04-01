from rdflib import URIRef


def id_validate(value: str):
    # Skip blank nodes that do not need to be valid IRIs
    if not value.startswith("_:"):
        uri_version = URIRef(value)
        try:
            uri_version.n3()
        except Exception:
            raise ValueError(f'"{value}" is not a valid IRI')
    return value
