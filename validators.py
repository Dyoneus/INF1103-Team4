from abc import ABC, abstractmethod


class Validator(ABC):
    """Abstract base class for input validators."""

    @abstractmethod
    def validate(self, text: str) -> list[str]:
        """Return error codes for the input, or [] if it is valid."""
 
    def clean(self, text: str) -> str:
        """Return valid input in its stored form. Only call after validate() passes."""
        return text.strip()


class RequiredTextValidator(Validator):
    """Free text that must not be blank and must fit within a length limit.
 
    Used for the description, workplace location, workplace name and
    person name, which differ only in their limit and error codes.
    """

    def __init__(self, max_length: int, empty_code: str, too_long_code: str):
        self._max_length = max_length
        self._empty_code = empty_code
        self._too_long_code = too_long_code

    @property
    def max_length(self) -> int:
        return self._max_length

    def validate(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return [self._empty_code]
        if len(text) > self._max_length:
            return [self._too_long_code]
        return []
    

        
