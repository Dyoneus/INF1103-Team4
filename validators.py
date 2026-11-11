from abc import ABC, abstractmethod
import re

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


class EmailValidator(Validator):
    """Email address with a basic name@domain.tld shape."""

    _PATTERN = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]{2,}")

    def validate(self, text: str) -> list[str]:
        text = text.strip()
        if not text:
            return ["EMPTY_EMAIL"]
        if not self._PATTERN.fullmatch(text):
            return ["INVALID_EMAIL"]
        return []

    def clean(self, text: str) -> str:
        return text.strip().lower()
        

class NricValidator(Validator):
    """Singapore NRIC/FIN.
 
    S/T/F/G numbers are checked against the official checksum letter.
    M-series FINs are only checked for format.
    """
 
    _PATTERN = re.compile(r"[STFGM]\d{7}[A-Z]")
    _WEIGHTS = (2, 7, 6, 5, 4, 3, 2)
    _CITIZEN_LETTERS = "JZIHGFEDCBA"    # S and T prefixes
    _FOREIGNER_LETTERS = "XWUTRQPNMLK"  # F and G prefixes
 
    def validate(self, text: str) -> list[str]:
        value = self.clean(text)
        if not value:
            return ["EMPTY_NRIC"]
        if not self._PATTERN.fullmatch(value):
            return ["INVALID_NRIC_FORMAT"]
        if value[0] == "M":
            return []
        if value[8] != self._expected_checksum(value):
            return ["INVALID_NRIC_CHECKSUM"]
        return []
 
    def clean(self, text: str) -> str:
        return text.strip().upper()
 
    def _expected_checksum(self, value: str) -> str:
        """Return the checksum letter an S/T/F/G number should end with."""
        prefix = value[0]
        total = sum(
            int(digit) * weight
            for digit, weight in zip(value[1:8], self._WEIGHTS)
        )
        if prefix in "TG":
            total += 4
        letters = self._CITIZEN_LETTERS if prefix in "ST" else self._FOREIGNER_LETTERS
        return letters[total % 11]

        
