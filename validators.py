from abc import ABC, abstractmethod


class Validator(ABC):
    """Abstract base class for input validators."""

    @abstractmethod
    def validate(self, text: str) -> list[str]:
        """Return error codes for the input, or [] if it is valid."""
 
    def clean(self, text: str) -> str:
        """Return valid input in its stored form. Only call after validate() passes."""
        return text.strip()
