from enum import IntEnum

class Severity(IntEnum):
    CRITICAL = 50
    ERROR = 40
    WARNING = 30
    INFO = 20
    DEBUG = 10

    def __str__(self):
        return self.name