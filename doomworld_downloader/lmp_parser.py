"""
Parse data out of LMP header, footer, and other parts of the file (no playback).
"""
# TODO: All of the parser classes can have stuff abstracted out.
# TODO: Write LMP Python parsing library

import logging
import re
import shlex
import subprocess

from datetime import datetime, timedelta

from .data_manager import DataManager
from .upload_config import CONFIG
from .utils import run_cmd, convert_datetime_to_dsda_date, compare_iwad


LOGGER = logging.getLogger(__name__)


class LMPData:
    """Store all uploader-relevant data for an LMP file.

    This is intended to be a very generic storage class that is mostly unaware of intricacies of the
    LMP format like headers, footers, etc. That will be handled by the LMP library used underneath.
    """
    PORT_FOOTER_TO_DSDA_MAP = {'PrBoom-Plus': 'PRBoom', 'dsda-doom': 'DSDA-Doom', 'Woof': 'Woof'}
    KEY_LIST = [
        'engine', 'version', 'skill', 'episode', 'level', 'play mode', 'respawn', 'fast',
        'nomonsters', 'player 1', 'player 2', 'player 3', 'player 4', 'player 5', 'player 6',
        'player 7', 'player 8', 'turbo', 'stroller', 'sr50 on turns'
    ]
    PLAYER_RE = re.compile(r'^player \d$', re.IGNORECASE)
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
        201: '8', 202: '9', 210: '10', 211: '14', 212: '15', 213: '16', 214: '17', 221: '21'
    }
    WOOF_GAMEVERSION_TO_COMPLEVEL_MAP = {'1.9': '2', 'ultimate': '3', 'final': '4', 'chex': '3'}

    # TODO: We might benefit from certain/possible keys being possible to change as an instance;
    #       basically, source_port could be guessed fuzzily here or perfectly, and most of the time,
    #       it is the latter, but might be nice to account for the former
    #       Maybe an override certainty dictionary is a way to do this?
    CERTAIN_KEYS = ['is_solo_net', 'num_players', 'recorded_at', 'source_port']
    POSSIBLE_KEYS = ['is_tas']

    ADDITIONAL_IWADS = ['heretic', 'hexen']
    HEXEN_CLASS_MAPPING = {0: 'Fighter', 1: 'Cleric', 2: 'Mage'}

    DEMO_DATE_CUTOFF = datetime.strptime(CONFIG.demo_date_cutoff, '%Y-%m-%dT%H:%M:%SZ')
    FUTURE_CUTOFF = datetime.today() + timedelta(days=1)

    def __init__(self, lmp_path, recorded_date, demo_info=None):
        """Initialize LMP data class.

        :param lmp_path: Path to the LMP file
        :param recorded_date: Date the LMP was recorded
        """
        self.lmp_path = lmp_path
        dsda_date = convert_datetime_to_dsda_date(recorded_date)
        if not LMPData.DEMO_DATE_CUTOFF < recorded_date < LMPData.FUTURE_CUTOFF:
            LOGGER.error('Found possibly incorrect date, setting to UNKNOWN: "%s".', dsda_date)
            dsda_date = 'UNKNOWN'
        self.data = {'num_players': 0, 'recorded_at': dsda_date}
        self.note_strings = set()
        self.raw_data = {'player_classes': [], 'wad_strings': []}
        self._header = None
        self._footer = None
        self.demo_info = demo_info if demo_info else {}

    def analyze(self):
        self._get_header_and_footer()
        # TODO: There are probably other demos that we can't just put into the LMP parser, this
        #       logic may need to be expanded
        if not self._is_zdoom_or_gzdoom():
            self._parse_lmp()
            self._parse_footer()

        self._get_source_port()
        # DSDA API expects the num_players (i.e., guys) argument to be a string
        self.data['num_players'] = str(self.data['num_players'])

        iwad = self.raw_data.get('iwad')
        if not self.raw_data['wad_strings'] and iwad:
            self.raw_data['wad_strings'].append(iwad)

        if self.raw_data['player_classes']:
            self.note_strings.add('Hexen class: ' + ', '.join(self.raw_data['player_classes']))

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
        parse_lmp_cmd = '{start} "{demo}"'.format(start=LMPData.PARSE_LMP_COMMAND_START,
                                                  demo=self.lmp_path)
        parse_lmp_out = ''
        try:
            parse_lmp_out = run_cmd('{}'.format(parse_lmp_cmd), get_output=True)
        except subprocess.CalledProcessError as cpe:
            LOGGER.info('Encountered exception %s when running parse LMP command for LMP %s.',
                        cpe, self.lmp_path)

        if not parse_lmp_out or 'Unknown engine' in parse_lmp_out:
            upstream_iwad = self.demo_info.get('iwad')
            # Default to Heretic which receives more demos than Hexen
            engine_option = 'heretic'
            for additional_iwad in LMPData.ADDITIONAL_IWADS:
                if compare_iwad(upstream_iwad, additional_iwad):
                    engine_option = additional_iwad
                    break

            try:
                parse_lmp_out = run_cmd('{} --engine={}'.format(parse_lmp_cmd, engine_option),
                                        get_output=True)
                self.raw_data['iwad'] = f'{engine_option}.wad'
            except subprocess.CalledProcessError as cpe:
                LOGGER.info('Encountered exception %s when running parse LMP command for LMP %s.',
                            cpe, self.lmp_path)

        parse_lmp_out = parse_lmp_out.splitlines()
        for key in LMPData.KEY_LIST:
            for line in parse_lmp_out:
                self._parse_key(key, line)

    def _parse_key(self, key, line):
        """Parse key out of a line of parse_lmp output.

        Script output format:
          --------
          Details:

          Engine: Doom
          Version: 109
          Skill: 4
          Episode: 1
          Level: 16
          Play Mode: single / coop
          Respawn: 0
          Fast: 0
          NoMonsters: 15
          Point of View: 0
          Player 1: 1
          Player 2: 0
          Player 3: 0
          Player 4: 0
          --------
          Statistics:

          SR40:  32 %
          SR50:  64 %
          SR:    96 %

          Run Frequency:
             50: 1.0

          Strafe Frequency:
             40: 1.0

          Turn Frequency:
              2: 1.0

          Average Turn Speed: 2
          Standard Deviation: 0

          Turbo:           false
          Stroller:        false
          SR50 On Turns:   false
          One Frame Uses:  None / 2
          One Frame Fires: None / 0
          One Frame Swaps: None / 0
          Pauses:          None
          Saves:           None

          One Frame Turns:
            None

          Sudden Turns:
            None

          Bad Straferun:
            None

          --- END ---

        :param key: Key to parse
        :param line: parse_lmp output line
        """
        line = line.strip().lower()
        # We only care about lines with a single ":" character, since those are the top-level keys
        # in the output
        if line.count(':') == 1:
            cur_key, value = [part.strip() for part in line.split(':')]
            if cur_key == key:
                iwad = self.raw_data.get('iwad')
                if LMPData.PLAYER_RE.match(key):
                    if iwad == 'hexen':
                        player_value, class_value = value.split()
                        # Hexen player line would look like the following (first value is the
                        # player existence value, second value in parens is the class):
                        #   Player 1: 1 (0)
                        class_value = int(class_value.replace('(', '').replace(')', ''))
                    else:
                        player_value = value
                        class_value = None

                    try:
                        player_value = int(player_value)
                    except ValueError:
                        LOGGER.warning(
                            "Player value provided isn't int, demo %s is likely a Hexen demo.",
                            self.lmp_path
                        )
                    if player_value != 0:
                        self.data['num_players'] += 1
                        if class_value is not None:
                            self.raw_data['player_classes'].append(
                                LMPData.HEXEN_CLASS_MAPPING[class_value]
                            )
                if key == 'sr50 on turns' and value.lower() == 'true':
                    self.data['is_tas'] = True
                # For Heretic/Hexen demos, these keys are just output as "true"/"false" strings
                if (not iwad == 'heretic.wad' and not iwad == 'hexen.wad' and
                        key in self.BOOLEAN_INT_KEYS):
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
            for footer_port_start in LMPData.PORT_FOOTER_TO_DSDA_MAP.keys():
                if line.startswith(footer_port_start):
                    self.raw_data['source_port_family'] = line.strip()
            # Detect the command-line section by an argument that should always be there, I think
            if '-iwad' in line:
                line = shlex.split(line)
                in_wad_args = False
                in_deh_args = False
                gameversion = None
                for idx, elem in enumerate(line):
                    if elem.startswith('-'):
                        in_wad_args = False
                        in_deh_args = False
                        # TODO: Add more possible arguments (spechits numbers, emulate args, etc.)
                        # TODO: Add example footers somewhere in documentation
                        # TODO: Parse mouselook data
                        if elem == '-iwad':
                            self.raw_data['iwad'] = self._parse_file_in_footer(line[idx + 1],
                                                                               '.wad')
                        if elem == '-file':
                            # There may be multiple WAD files passed in, so check all of them
                            in_wad_args = True
                        if elem == '-deh':
                            # There may be multiple DEH files passed in, so check all of them
                            in_deh_args = True
                        if elem == '-complevel':
                            self.raw_data['complevel'] = line[idx + 1]
                        if elem == '-solo-net':
                            self.data['is_solo_net'] = True
                        if elem == '-coop_spawns':
                            self.note_strings.add('-coop_spawns')
                        if elem == '-gameversion':
                            gameversion = line[idx + 1]
                    elif in_wad_args:
                        self.raw_data['wad_strings'].append(
                            self._parse_file_in_footer(line[idx], '.wad')
                        )
                    elif in_deh_args:
                        self.raw_data['wad_strings'].append(
                            self._parse_file_in_footer(line[idx], '.deh')
                        )
                if self.raw_data.get('complevel') == 'vanilla' and gameversion:
                    self.raw_data['complevel'] = LMPData.WOOF_GAMEVERSION_TO_COMPLEVEL_MAP.get(
                        gameversion, self.raw_data['complevel']
                    )

    def _parse_file_in_footer(self, footer_file, extension):
        """Parse file argument from footer.

        :param footer_file: File argument value
        :param extension: Extension for file for sanitizing input
        :return: Parsed file from footer
        """
        # Files in footers are surrounded with double quotes, removing those.
        # Sometimes files are stored in footers as doom2.wad.wad. Fixing, this case, not sure if
        # the extension could be repeated more times, but if so, this could be updated.
        return footer_file.replace('"', '').replace(
            '{extension}{extension}'.format(extension=extension), extension
        )

    def _get_source_port(self):
        """Get full source port info when possible.

        In most cases, unless we have a footer, this function will be unable to retrive any port
        info.
        """
        # TODO: 130-150 are Legacy demos.
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
        # Heretic does not have the version flag set, so default to non-existent version
        raw_version = int(self.raw_data.get('version', -1))
        # This value, along with complevel, could already be obtained from the footer, in which case
        # we can just use that.
        if source_port_family:
            port_split = source_port_family.split(maxsplit=2)
            # Later versions of XDRE output source port as "PrBoom-Plus 2.5.1.4 (XDRE 2.20)"
            if 'XDRE' in source_port_family:
                self.data['source_port'] = port_split[-1].replace('(', '').replace(')', '')
            else:
                port_name, port_version = port_split
                # Normalize port names
                port_name = LMPData.PORT_FOOTER_TO_DSDA_MAP.get(port_name, port_name)

                port_with_version = '{name} v{version}'.format(name=port_name, version=port_version)
                # Infer complevel for any that PrBoom+/DSDA-Doom do not output to the footer
                if not complevel:
                    if raw_version == 203:
                        first_character = chr(self._header[2])
                        if first_character == "M":
                            complevel = '11'
                    else:
                        complevel = LMPData.VERSION_COMPLEVEL_MAP.get(raw_version)
                if complevel:
                    self.data['source_port'] = '{name}cl{complevel}'.format(name=port_with_version,
                                                                            complevel=complevel)
                    # Update the raw complevel setting with the final guess
                    self.raw_data['complevel'] = complevel
                    return

        # Up to (and including) Doom 1.2, first byte was skill level, not game/exe version
        if 0 <= raw_version <= 4:
            if self.check_doom_1_2_or_before():
                self.data['source_port'] = 'Doom v1.2 or earlier'
        elif raw_version == 110:
            self.data['source_port'] = 'TASDoom'

        # This isn't 100% part of the port info, but this is the cleanest place to check for this.
        if raw_version == 111:
            self.raw_data['is_longtics'] = True
            self.note_strings.add('Uses -longtics')

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
