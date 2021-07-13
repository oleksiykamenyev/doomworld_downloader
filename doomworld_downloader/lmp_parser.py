"""
Parse data out of LMP header, footer, and other parts of the file (no playback).
"""
# TODO: All of the parser classes can have stuff abstracted out.

import logging
import subprocess

from .data_manager import DataManager
from .upload_config import CONFIG
from .utils import run_cmd


LOGGER = logging.getLogger(__name__)


class LMPData:
    """Store all uploader-relevant data for an LMP file.

    This is intended to be a very generic storage class that is mostly unaware of intricacies of the
    LMP format like headers, footers, etc. That will be handled by the LMP library used underneath.
    """
    KEY_LIST = [
        'engine', 'version', 'skill', 'episode', 'level', 'play mode', 'respawn', 'fast',
        'nomonsters', 'player 1', 'player 2', 'player 3', 'player 4', 'turbo', 'stroller',
        'sr50 on turns'
    ]
    PLAYER_KEYS = ['player 1', 'player 2', 'player 3', 'player 4']
    BOOLEAN_INT_KEYS = ['respawn', 'fast', 'nomonsters']
    # -d: Print demo (header) details
    # -s: Print demo statistics
    PARSE_LMP_COMMAND_START = 'ruby {parse_lmp_path}/parse_lmp.rb -d -s'.format(
        parse_lmp_path=CONFIG.parse_lmp_directory
    )

    # Note: trying to record with complevels 10 (LxDoom 1.4.x) or 12 (PrBoom 2.03beta) will crash
    # PrBoom+. Complevel -1 is identical to 17, however, -1 is more consistent, as hypothetical
    # future PrBoom+ versions that require compatibility with an older PrBoom+ would presumable use
    # the next complevel 17 for that. Pre-Boom complevels aren't included as they are present in the
    # footer.
    VERSION_COMPLEVEL_MAP = {
        201: '8', 202: '9', 210: '10', 211: '14', 212: '15', 213: '16', 214: '-1'
    }

    CERTAIN_KEYS = ['is_solo_net', 'num_players', 'recorded_at']
    POSSIBLE_KEYS = ['source_port', 'is_tas']

    def __init__(self, lmp_path, recorded_date):
        """Initialize LMP data class.

        :param lmp_path: Path to the LMP file
        :param recorded_date: Date the LMP was recorded
        """
        self.lmp_path = lmp_path
        # TODO: We might want some sanity checking on the recording date of the LMP
        self.data = {'num_players': 0, 'recorded_at': recorded_date}
        self.note_strings = set()
        self.raw_data = {'wad_strings': []}
        self._header = None
        self._footer = None
        self._get_header_and_footer()
        # TODO: There are probably other demos that we can't just put into the LMP parser, this
        #       logic may need to be expanded
        if not self._is_zdoom_or_gzdoom():
            self._parse_lmp()
            self._parse_footer()

        self._get_source_port()

    def populate_data_manager(self, data_manager):
        for key, value in self.data.items():
            if key in LMPData.CERTAIN_KEYS:
                data_manager.insert(key, value, DataManager.CERTAIN, source='lmp')
            elif key in LMPData.POSSIBLE_KEYS:
                data_manager.insert(key, value, DataManager.POSSIBLE, source='lmp')
            else:
                raise ValueError('Unrecognized key found in data dictionary: {}.'.format(key))

    def _get_header_and_footer(self):
        """Get header and footer for LMP file."""
        footer_chars = []
        with open(self.lmp_path, 'rb') as lmp_bytes:
            # No error even if the file is smaller than 22 bytes.
            self._header = lmp_bytes.read(22)
            # (G)ZDoom demos don't use \x80 as the "end of inputs" and also don't even have a footer
            # (all meta info is in the header)
            if not self._is_zdoom_or_gzdoom():
                lmp_bytes.seek(-1, 2)  # Go one byte before the end of file
                current_byte = lmp_bytes.read(1)
                while current_byte != b'\x80':
                    footer_chars.append(current_byte)
                    lmp_bytes.seek(-2, 1)  # Go back one byte
                    current_byte = lmp_bytes.read(1)

        self._footer = b''.join(footer_chars[::-1]).decode(errors='ignore')

    def _parse_lmp(self):
        """Parse LMP file using the parse_lmp Ruby library."""
        parse_lmp_cmd = '{start} {demo}'.format(start=LMPData.PARSE_LMP_COMMAND_START,
                                                demo=self.lmp_path)
        parse_lmp_out = None
        try:
            parse_lmp_out = run_cmd(parse_lmp_cmd, get_output=True).splitlines()
        except subprocess.CalledProcessError as cpe:
            LOGGER.debug('Encountered exception %s when running parse LMP command.', cpe)
            pass

        if not parse_lmp_out:
            # For now, we have no clear indicator that a demo is Heretic or not at this point, so
            # the easiest approach is trying it both ways and seeing which one works.
            # TODO: Probably need a better approach here, although not sure there is anything great
            LOGGER.debug('Trying parse LMP command with Heretic.')
            parse_lmp_cmd = '{} --engine=heretic'.format(parse_lmp_cmd)
            parse_lmp_out = run_cmd(parse_lmp_cmd, get_output=True).splitlines()
            self.raw_data['is_heretic'] = True

        for key in LMPData.KEY_LIST:
            for line in parse_lmp_out:
                self._parse_key(key, line)

    def _parse_key(self, key, line):
        """Parse key out of a line of parse_lmp output.

        :param key: Key to parse
        :param line: parse_lmp output line
        """
        # TODO: Add example output from script to documentation
        line = line.strip().lower()
        if ':' in line:
            cur_key, value = [part.strip() for part in line.split(':')]
            if cur_key == key:
                if key in LMPData.PLAYER_KEYS and int(value) != 0:
                    self.data['num_players'] += 1
                if key == 'sr50 on turns' and value.lower() == 'true':
                    self.data['is_tas'] = True
                if key in self.BOOLEAN_INT_KEYS:
                    value = False if int(value) == 0 else True
                self.raw_data[key] = value

    def _is_zdoom_or_gzdoom(self):
        """Return whether a demo is ZDoom or GZDoom.

        :return: Flag indicating whether a demo is ZDoom or GZDoom.
        """
        # TODO: Handle other cases that have no footer
        # Starting from 1.14, until then the signature was "ZDEM"
        return self._header[:4] == b'FORM'

    def _parse_footer(self):
        """Parse footer of LMP."""
        for line in self._footer.splitlines():
            # Adding a bunch of ports just in case they start supporting the footer...
            if (line.startswith('PrBoom-Plus') or line.startswith('DSDA-Doom') or
                    line.startswith('Crispy Doom')):
                self.raw_data['source_port_family'] = line.strip()
            # Detect the command-line section by an argument that should always be there, I think
            # TODO: Should probably make this a class var
            if '-iwad' in line:
                line = line.split()
                for idx, elem in enumerate(line):
                    if elem.startswith('-'):
                        # TODO: Should probably make these class vars
                        # TODO: Add more possible arguments (spechits numbers, emulate args, etc.)
                        # TODO: Add example footers somewhere
                        # TODO: Add dehacked patches
                        if elem == '-iwad':
                            # WAD files in footers are surrounded with double quotes, removing
                            # those.
                            iwad = line[idx + 1].replace('"', '')
                            self.raw_data['iwad'] = iwad
                            if iwad == 'chex.wad':
                                self.raw_data['is_chex'] = True
                            if iwad == 'heretic.wad':
                                self.raw_data['is_heretic'] = True
                        if elem == '-file':
                            # WAD files in footers are surrounded with double quotes, removing
                            # those.
                            self.raw_data['wad_strings'].append(line[idx + 1].replace('"', ''))
                        if elem == '-complevel':
                            self.raw_data['complevel'] = line[idx + 1]
                        if elem == '-solo-net':
                            self.data['is_solo_net'] = True

    def _get_source_port(self):
        """Get full source port info when possible.

        In most cases, unless we have a footer, this function will be unable to retrive any port
        info.
        """
        if self._is_zdoom_or_gzdoom():
            # Based on the code and there doesn't seem to be any way to discern ZDoom from GZDoom
            # from the demo file. Demo compatibility version for the very first version of ZDoom
            # (1.11) was 0x10B (but the current demo format was introduced in 1.14).
            self.data['source_port'] = 'ZDoom/GZDoom (demo compat version 0x{:X}{:02X})'.format(
                self._header[20], self._header[21]
            )
            return

        source_port_family = self.raw_data.get('source_port_family', '')
        complevel = self.raw_data.get('complevel')
        raw_version = int(self.raw_data['version'])
        # This value, along with complevel, could already be obtained from the footer, in which case
        # we can just use that.
        if source_port_family:
            port_name, port_version = source_port_family.split()
            # Normalize port names
            # TODO: Could be dictionary lookup? Or use class vars.
            if port_name == 'PrBoom-Plus':
                port_name = 'PrBoom-plus'
            elif port_name == 'dsda-doom':
                port_name = 'DSDA-Doom'

            port_with_version = '{name} v{version}'.format(name=port_name, version=port_version)
            # Infer complevel for any that PrBoom+/DSDA-Doom do not output to the footer
            if not complevel:
                if raw_version == 203:
                    first_character = self.raw_data['engine'][0]
                    if first_character == "M":
                        complevel = '11'
                else:
                    complevel = LMPData.VERSION_COMPLEVEL_MAP.get(raw_version)
            if complevel:
                self.data['source_port'] = '{name}cl{complevel}'.format(name=port_with_version,
                                                                        complevel=complevel)
                return

        # Up to (and including) Doom 1.2, first byte was skill level, not game/exe version
        # TODO: Double check if this is worth setting; can any source ports record with 1.2 compat?
        if 0 <= raw_version <= 4:
            if self.check_doom_1_2_or_before():
                self.data['source_port'] = 'Doom v1.2 or earlier'
        elif raw_version == 110:
            self.data['source_port'] = 'TASDoom'

        # This isn't 100% part of the port info, but this is the cleanest place to check for this.
        # TODO: Should probably just make this a note string
        if 111 <= raw_version < 200:
            self.raw_data['is_longtics'] = True

    def check_doom_1_2_or_before(self):
        """Check if a demo is recorded in a version of Doom 1.2 or prior.

        :return: Flag indicating if a demo is recorded in a version of Doom 1.2 or prior
        """
        _, episode, level, *players = self._header[:7]
        if episode not in range(1, 4):
            return False
        if level not in range(1, 10):
            return False
        if any(player not in (0, 1) for player in players):
            return False

        return True
