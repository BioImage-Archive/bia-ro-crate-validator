from dataclasses import dataclass
from typing import Optional

from bia_ro_crate.core.validation.severity import Severity


@dataclass
class ValidationError:
    message: str
    severity: Severity
    location_description: Optional[str] = None

    def format_message(self) -> str:
        if self.location_description:
            return f"{self.location_description}: \n   {self.message}"
        else:
            return self.message

    def to_exception(self) -> Exception:
        return Exception(self.format_message())
    
    def to_dict(self):
        return self.__dict__
