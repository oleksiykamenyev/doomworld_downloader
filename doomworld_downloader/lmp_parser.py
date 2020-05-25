"""
Stub: lmp parser

TODO: We can start working on this earlier. Please operate off the following assumptions:
  - You're provided an lmp in a local directory
  - For now, we can use Kraflab's parse_lmp tool:
    - Assume the user of the script has Ruby installed
    - Add a property to upload.ini that is points to the path of the parse_lmp script
  - Your output should be a dictionary of all relevant info for the final JSON
"""

import logging
import subprocess

from .upload_config import CONFIG


LOGGER = logging.getLogger(__name__)


class LMPData:
    """Stores all uploader-relevant data for an LMP file

    This is intended to be a very generic storage class that is mostly unaware of intricacies of the
    LMP format like headers, footers, etc. That will be handled by the LMP library used underneath.
    """
    # Additional key notes:
    #   Engine: Very high level info on what engine was used, either Doom or Boom
    #   Version: Probably not very useful?
    #   Episode: Always 1 for Doom 2
    #   Play mode: Either "single / co-op" or "altdeath". In latter case, demo needs a note
    #   Turbo: If yes, demo needs a note as a turbo run
    #   Stroller: Doesn't indicate stroller on its own, but a  false here indicates the demo is NOT
    #             a stroller.
    #   SR50 On Turns: If true, demo uses TAS.
    KEY_LIST = [
        'engine', 'version', 'skill', 'episode', 'level', 'play mode', 'respawn', 'fast',
        'nomonsters', 'player 1', 'player 2', 'player 3', 'player 4', 'turbo', 'stroller',
        'sr50 on turns'
    ]
    PLAYER_KEYS = ['player 1', 'player 2', 'player 3', 'player 4']
    # -d: Print demo (header) details
    # -s: Print demo statistics
    PARSE_LMP_COMMAND_START = '{parse_lmp_path}/parse_lmp.rb -d -s'.format(
        parse_lmp_path=CONFIG.parse_lmp_directory
    )

    def __init__(self, lmp_path):
        self.lmp_path = lmp_path
        self.data = {'num_players': 0}
        # TODO:
        #   Consider making this an ordered set. Not sure if this should be in this class, so
        #   not populating it yet
        self.note_strings = set()
        self.raw_data = {}
        self._parse_lmp(lmp_path)

    def _parse_lmp(self, lmp_path):
        parse_lmp_cmd = '{start} {demo}'.format(start=LMPData.PARSE_LMP_COMMAND_START,
                                                demo=lmp_path)
        LOGGER.debug('Running command "%s"', parse_lmp_cmd)
        parse_lmp_out = subprocess.check_output(parse_lmp_cmd.split()).decode('utf-8').splitlines()
        for key in LMPData.KEY_LIST:
            for line in parse_lmp_out:
                self._parse_key(key, line)

    def _parse_key(self, key, line):
        line = line.strip().lower()
        if ':' in line:
            cur_key, value = [part.strip() for part in line.split(':')]
            if cur_key == key:
                if key in LMPData.PLAYER_KEYS:
                    self.data['num_players'] += 1
                self.raw_data[key] = value
