"""
Parse data out of demo textfile.
"""
# TODO: All of the parser classes can have stuff abstracted out.

import logging
import re

from .data_manager import DataManager
from .utils import parse_youtube_url


LOGGER = logging.getLogger(__name__)


class TextfileData:
    """Store all uploader-relevant data for a demo textfile."""
    CATEGORY_KEYS = ['category', 'discipline']
    PORT_KEYS = ['builtusing', 'builtwith', 'client', 'engine', 'exe', 'port', 'portused',
                 'recordedusing', 'recordedwith', 'sourceport', 'sourceportused', 'usingport',
                 'usingsourceport']
    TAS_PORTS = ['DRE', 'TASDoom', 'TASMBF', 'XDRE']
    TAS_STRING = 'this is a tools-assisted demo'
    VIDEO_KEYS = ['video', 'videolink', 'youtube', 'youtubelink', 'yt', 'ytlink']
    WAD_KEYS = ['mapset', 'pwad', 'pwadfile', 'wad']

    CERTAIN_KEYS = ['is_tas']
    POSSIBLE_KEYS = ['category', 'source_port', 'video_link']

    CATEGORY_REGEXES = {
        re.compile(r'UV[ -_]?Max', re.IGNORECASE): 'UV Max',
        re.compile(r'UV[ -_]?Speed', re.IGNORECASE): 'UV Speed',
        re.compile(r'NM[ -_]?Speed', re.IGNORECASE): 'NM Speed',
        re.compile(r'NM[ -_]?100s?', re.IGNORECASE): 'NM 100S',
        re.compile(r'UV[ -_]?-?fast', re.IGNORECASE): 'UV Fast',
        re.compile(r'(UV)?[ -_]?-?respawn', re.IGNORECASE): 'UV Respawn',
        re.compile(r'(UV)?[ -_]?Pacifist', re.IGNORECASE): 'Pacifist',
        re.compile(r'(UV)?[ -_]?Tyson', re.IGNORECASE): 'Tyson',
        re.compile(r'(UV)?[ -_]?No\s*mo(nsters)?\s*$', re.IGNORECASE): 'NoMo',
        re.compile(r'(UV)?[ -_]?No\s*mo(nsters)?[ -_]?100s?', re.IGNORECASE): 'NoMo 100S',
        re.compile(r'(UV)?[ -_]?Stroller', re.IGNORECASE): 'Stroller'
    }
    NOTE_REGEXES = {
        re.compile(r'(UV|NM)?[ -_]?Reality', re.IGNORECASE): 'Also Reality'
    }
    PORT_REGEXES = {
        # Chocolate family
        # Chocolate Doom
        re.compile(r'Chocolate(\s*|-)?Doom(\.exe)?(\s*|-)?v?\.?(?P<version>\d\.\d+\.\d+)',
                   re.IGNORECASE): 'Chocolate DooM',
        # Crispy Doom
        re.compile(
            r'Crispy(\s*|-)?Doom(\.exe)?(\s*|-)?v?\.?(?P<version>\d\.\d+(\.\d+)?)', re.IGNORECASE
        ): 'Crispy Doom',
        # Crispy Heretic
        re.compile(
            r'Crispy(\s*|-)?Heretic(\.exe)?(\s*|-)?v?\.?(?P<version>\d\.\d+(\.\d+)?)', re.IGNORECASE
        ): 'Crispy Heretic',
        # CNDoom
        re.compile(
            r'CNDoom(\.exe)?\s*v?\.?(?P<version>\d\.\d\.\d(\.\d))?', re.IGNORECASE
        ): 'CNDoom',

        # Boom/MBF family
        # Boom
        re.compile(r'([\S+])Boom\s*v?(?P<version>2\.0\.[0-2])', re.IGNORECASE): 'Boom',
        # MBF
        re.compile(
            r'[\S+](?P<name>MBF(386|-Sigil|-SNM)?)\s*v?(?P<version>\d\.\d\.\d)', re.IGNORECASE
        ): None,
        # TASMBF
        re.compile(r'TASMBF', re.IGNORECASE): 'TASMBF',
        # PrBoom
        re.compile(
            r'(Pr|GL)Boom(\.exe)?^(\+|-?plus)\s*v?\.?(?P<version>\d\.\d\.\d)', re.IGNORECASE
        ): 'PRBoom',
        # PrBoom+
        re.compile(
            r'(Pr|GL)(Boom)?\s*(\+|-?plus)?(\.exe)?(\s*|-)?v?\.?(?P<version>\d\.\d\.\d\.\d)\s'
            r'*-?((complevel|cl)\s*(?P<complevel>\d+))?',
            re.IGNORECASE
        ): 'PRBoom',
        # DSDA-Doom
        re.compile(
            r'DSDA(\s*|-)Doom(\.exe)?(\s*|-)?v?\.?(?P<version>\d\.\d+(\.\d+)?)\s*'
            r'-?((complevel|cl)\s*(?P<complevel>\d+))?',
            re.IGNORECASE
        ): 'DSDA-Doom',

        # ZDoom family
        # ZDoom
        re.compile(r'[\S+]ZDoom\s*v?(?P<version>\d\.\d(\.\S+))?', re.IGNORECASE): 'ZDoom',
        # GZDoom
        re.compile(r'GZDoom\s*v?(?P<version>\d\.\d\.\d+)', re.IGNORECASE): 'GZDoom',
        # ZDaemon
        re.compile(r'ZDaemon\s*v?(?P<version>\d\.\d\.\d+)', re.IGNORECASE): 'ZDaemon',
        # Zandronum
        re.compile(r'Zandronum\s*v?(?P<version>\d\.\d(\.\d+)?(\s*Alpha))',
                   re.IGNORECASE): 'Zandronum',

        # Other ports
        # Strawberry Doom
        re.compile(r'Strawberry\s*Doom\s*r(?P<version>\d+)', re.IGNORECASE): 'Strawberry Doom',

        # TAS
        re.compile(r'XDRE(\.exe)?(\s*|-)?v?\.?(?P<version>\d.\d+)', re.IGNORECASE): 'XDRE',
    }

    def __init__(self, textfile_path):
        """Initialize textfile data class.

        :param textfile_path: Path to textfile on local filesystem.
        """
        self.data = {}
        self.raw_data = {'wad_strings': [], 'video_links': []}
        self.note_strings = set()
        self.textfile_path = textfile_path
        self._raw_textfile = None

    def analyze(self):
        self._parse_textfile()

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

    def _parse_textfile(self):
        """Parse textfile path."""
        # TODO: Try at least once without errors='ignore'?
        with open(self.textfile_path, encoding='utf-8', errors='ignore') as textfile_stream:
            self._raw_textfile = textfile_stream.read()

        if TextfileData.TAS_STRING in self._raw_textfile.lower():
            self.data['is_tas'] = True

        text_lines = self._raw_textfile.splitlines()
        for line in text_lines:
            if ':' in line:
                key, value = line.split(':', 1)
                key = ''.join(key.lower().split())
                value_lowercase = value.lower().strip()

                if key in TextfileData.CATEGORY_KEYS:
                    self.data['category'] = self._parse_category(value_lowercase)
                elif key in TextfileData.PORT_KEYS:
                    self.data['source_port'] = self._parse_port(value_lowercase)
                elif key in TextfileData.VIDEO_KEYS:
                    youtube_url_key = parse_youtube_url(value)
                    self.raw_data['video_links'].append(youtube_url_key)
                elif key in TextfileData.WAD_KEYS:
                    self.raw_data['wad_strings'].append(value_lowercase)
                elif key == 'iwad':
                    self.raw_data['iwad'] = value_lowercase

        iwad = self.raw_data.get('iwad')
        if not self.raw_data['wad_strings'] and iwad:
            self.raw_data['wad_strings'].append(iwad)

        if len(self.raw_data['video_links']) == 1:
            self.data['video_link'] = self.raw_data['video_links'][0]

        # If we were unable to parse the category or source port from key/value pairs in the
        # textfile, we just try the entire textfile; this is likely to be wrong since someone could
        # just have a category or port name in their general comments, but better than nothing.
        if not self.data.get('category'):
            self.data['category'] = self._parse_category(self._raw_textfile)
            if not self.data.get('category'):
                LOGGER.info('Could not parse category from textfile %s.', self.textfile_path)
                self.data.pop('category')
        if not self.data.get('source_port'):
            self.data['source_port'] = self._parse_port(self._raw_textfile)
            if not self.data.get('source_port'):
                LOGGER.info('Could not parse source port from textfile %s.', self.textfile_path)
                self.data.pop('source_port')

        if self.data.get('source_port'):
            for tas_port in TextfileData.TAS_PORTS:
                if tas_port in self.data['source_port']:
                    self.data['is_tas'] = True

        for note_regex, note in TextfileData.NOTE_REGEXES.items():
            match = note_regex.search(self._raw_textfile)
            if match:
                self.note_strings.add(note)

    @staticmethod
    def _parse_category(text_str):
        """Parse category from a provided text string.

        :param text_str: Text string
        :return: Category name if it was possible to parse, else None
        """
        for category_regex, category_name in TextfileData.CATEGORY_REGEXES.items():
            match = category_regex.search(text_str)
            if match:
                return category_name

        return None

    @staticmethod
    def _parse_port(text_str):
        """Parse port from a provided text string.

        :param text_str: Text string
        :return: Port name if it was possible to parse, else None
        """
        for port_regex, port_name in TextfileData.PORT_REGEXES.items():
            match = port_regex.search(text_str)
            if match:
                # A whole bunch of hacky finagling to try to parse all kinds of different formats
                # for a port name and conform them to a single naming convention.
                version = match.group('version')
                port_name_final = port_name
                if not port_name_final:
                    port_name_final = match.group('name')

                # If someone formats DSDA-Doom version as just #.##, set to #.##.0 by default
                if port_name_final == 'DSDA-Doom' and version.count('.') == 1:
                    version = '{}.0'.format(version)

                # No need to fail on this since most ports don't have complevels anyway
                try:
                    complevel = match.group('complevel')
                except IndexError:
                    complevel = None
                if complevel:
                    version = '{}{}{}'.format(version, 'cl', complevel)

                if not version.startswith('v'):
                    version = 'v{}'.format(version)

                return '{} {}'.format(port_name_final, version)

        return None
