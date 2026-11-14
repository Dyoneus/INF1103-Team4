"""Shared test helpers."""

import pytest

from io_manager import IOManager


class FakeConsole:
    """Scripted terminal: hands out answers in order and records everything shown.

    An exception instance in the answers (e.g. KeyboardInterrupt()) is raised
    at that prompt, to simulate Ctrl+C / Ctrl+D.
    """

    def __init__(self, answers):
        self.remaining = list(answers)
        self.lines = []

    def input(self, prompt=""):
        self.lines.append(prompt)
        if not self.remaining:
            raise AssertionError(f"Unexpected prompt: {prompt!r}")
        answer = self.remaining.pop(0)
        if isinstance(answer, BaseException):
            raise answer
        return answer

    def output(self, text=""):
        self.lines.append(text)

    @property
    def text(self):
        return "\n".join(self.lines)


@pytest.fixture
def make_io():
    """Return a factory: make_io([answers...]) -> (IOManager, FakeConsole)."""
    def factory(answers=()):
        console = FakeConsole(answers)
        return IOManager(console.input, console.output), console
    return factory
