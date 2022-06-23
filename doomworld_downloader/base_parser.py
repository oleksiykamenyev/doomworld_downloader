"""
Base parser class.
"""

from abc import ABC, abstractmethod


class BaseData(ABC):
    """Store all uploader-relevant data for a source."""
    @abstractmethod
    def __init__(self):
        """Initialize base data class."""
        self.data = {}
        self.raw_data = {}
        self.note_strings = set()

    @abstractmethod
    def analyze(self):
        """Analyze info provided to parser."""

    @abstractmethod
    def populate_data_manager(self, data_manager):
        """Populate data manager with info from parser.

        :param data_manager: Data manager to populate
        """
