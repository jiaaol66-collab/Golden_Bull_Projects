"""Modern desktop shell for the existing Golden Bull Terminal runtime."""

from .api import TerminalBridge
from .state_reader import TerminalStateReader

__all__ = ["TerminalBridge", "TerminalStateReader"]

