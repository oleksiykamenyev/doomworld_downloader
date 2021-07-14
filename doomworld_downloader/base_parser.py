"""
Base parser class.
"""

from abc import ABC, abstractmethod


class BaseData(ABC):
    """Store all uploader-relevant data for a source."""
    CERTAIN_KEYS = ['is_tas']
    POSSIBLE_KEYS = ['category', 'source_port', 'video_link']

    @abstractmethod
    def __init__(self):
        """Initialize base data class."""
        self.data = {}
        self.raw_data = {}
        self.note_strings = set()

    @abstractmethod
    def populate_data_manager(self, data_manager):
        # The following data points are set for the playback parser:
        #   - Certain: levelstat, time, level, kills, items, secrets, wad
        #   - Somewhat certain: category
        for key, value in self.data.items():
            if key in TextfileData.CERTAIN_KEYS:
                data_manager.insert(key, value, DataManager.CERTAIN, source='textfile')
            elif key in TextfileData.POSSIBLE_KEYS:
                data_manager.insert(key, value, DataManager.POSSIBLE, source='textfile')
            else:
                raise ValueError('Unrecognized key found in data dictionary: {}.'.format(key))
