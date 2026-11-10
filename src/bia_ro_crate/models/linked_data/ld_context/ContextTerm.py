from dataclasses import dataclass

from rdflib import URIRef


@dataclass(frozen=True, eq=False)
class ContextTerm:
    """An immutable term definition, safe to compare, share and hash."""

    full_uri: URIRef
    field_name: str
    type_mapping: str | None = None
    is_reverse: bool = False
    container: str | list[str] | tuple[str, ...] | None = None

    def __post_init__(self):
        object.__setattr__(self, "full_uri", URIRef(self.full_uri))
        if (
            not isinstance(self.field_name, str)
            or self.type_mapping is not None
            and not isinstance(self.type_mapping, str)
        ):
            raise TypeError("Term names and type mappings must be strings")
        object.__setattr__(self, "field_name", str(self.field_name))
        if self.type_mapping is not None:
            object.__setattr__(self, "type_mapping", str(self.type_mapping))
        if type(self.is_reverse) is not bool:
            raise TypeError("Reverse flag must be a boolean")
        if self.container is not None and not isinstance(
            self.container, (str, list, tuple)
        ):
            raise TypeError("Container must be a string or sequence of strings")
        values = (
            (self.container,)
            if isinstance(self.container, str)
            else self.container or ()
        )
        if not all(isinstance(value, str) for value in values):
            raise TypeError("Container entries must be strings")
        containers = frozenset(values)
        single = {"@set", "@list", "@index", "@id", "@type", "@language", "@graph"}
        valid = (
            not containers
            or len(containers) == 1
            and containers <= single
            or containers == {"@set", "@graph"}
            or any(
                containers == {"@set", other}
                for other in ("@index", "@id", "@type", "@language")
            )
            or any(
                containers in ({"@graph", other}, {"@graph", "@set", other})
                for other in ("@id", "@index")
            )
        )
        if not valid or self.is_reverse and not containers <= {"@set", "@index"}:
            raise ValueError(
                f"Invalid JSON-LD container for this term: {self.container}"
            )
        if isinstance(self.container, (list, tuple)):
            object.__setattr__(self, "container", tuple(sorted(containers)))

    def __eq__(self, other):
        if not isinstance(other, ContextTerm):
            return False

        return self._identity() == other._identity()

    def _identity(self) -> tuple:
        container = (
            tuple(sorted(self.container))
            if isinstance(self.container, (list, tuple))
            else (self.container,) if self.container else ()
        )
        return (
            self.full_uri,
            self.field_name,
            self.type_mapping,
            bool(self.is_reverse),
            container,
        )

    def __hash__(self):
        return hash(self._identity())

    def to_context_term_dict(self, prefixes: dict[str, str] | None = None) -> dict:
        context_term = {}

        id = str(self.full_uri)

        if prefixes:
            # Preserve delimiters exactly; JSON-LD expands by concatenation.
            # The longest namespace wins, independently of mapping insertion order.
            candidates = sorted(
                prefixes.items(), key=lambda item: (-len(item[1]), item[0])
            )
            for prefix_name, prefix_uri in candidates:
                if (
                    prefix_name
                    and prefix_name != "_"
                    and not prefix_name.startswith("@")
                    and not any(char in prefix_name for char in ":/")
                    and self.full_uri.startswith(prefix_uri)
                ):
                    suffix = self.full_uri.removeprefix(prefix_uri)
                    compact_id = f"{prefix_name}:{suffix}"
                    # A compact IRI cannot have an authority component.
                    if not suffix.startswith("//") and len(compact_id) < len(id):
                        id = compact_id
                        break

        if self.is_reverse:
            context_term |= {"@reverse": id}
        else:
            context_term |= {"@id": id}

        if self.type_mapping:
            context_term |= {"@type": self.type_mapping}
        if self.container:
            context_term |= {
                "@container": (
                    list(self.container)
                    if isinstance(self.container, (list, tuple))
                    else self.container
                )
            }
        return context_term

    def to_mapping_dict(
        self, prefixes: dict[str, str] | None = None
    ) -> dict[str, dict]:
        context_term = self.to_context_term_dict(prefixes)

        return {self.field_name: context_term}
