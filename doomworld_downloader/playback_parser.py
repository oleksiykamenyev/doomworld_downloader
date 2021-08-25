"""
Parse data out of DSDA-Doom playback of the LMP.
"""
# TODO: All of the parser classes can have stuff abstracted out.

import logging
import os
import subprocess

from shutil import copyfile, rmtree

from .data_manager import DataManager
from .dsda import download_wad_from_dsda, get_wad_name_from_dsda_url
from .upload_config import CONFIG, NEEDS_ATTENTION_PLACEHOLDER
from .utils import checksum, parse_range, run_cmd, zip_extract


LOGGER = logging.getLogger(__name__)


class PlaybackData:
    """Store all uploader-relevant data obtainable using DSDA-Doom.

    This includes data from levelstat.txt as well as the analysis.txt files.
    """
    # -levelstat: Create a levelstat.txt file with level statistics
    # -analysis: Create an analysis.txt file with additional analysis on the demo
    DEFAULT_ARGS = '-levelstat -analysis -nosound -nommusic -nodraw'
    DSDA_DOOM_COMMAND_START = '{dsda_doom_path}/dsda-doom.exe {additional_args}'.format(
        dsda_doom_path=CONFIG.dsda_doom_directory, additional_args=DEFAULT_ARGS
    )

    ANALYSIS_FILENAME = 'analysis.txt'
    LEVELSTAT_FILENAME = 'levelstat.txt'

    LEVELSTAT_LINE_LEVEL_IDX = 0
    LEVELSTAT_LINE_TIME_IDX = 2
    LEVELSTAT_LINE_TOTAL_TIME_IDX = 3
    LEVELSTAT_LINE_KILLS_IDX = 5
    LEVELSTAT_LINE_ITEMS_IDX = 7
    LEVELSTAT_LINE_SECRETS_IDX = 9

    ALL_SECRETS_CATEGORIES = [
        'UV Max', 'UV Fast', 'UV Respawn', 'NM 100S', 'NoMo 100S', 'SM Max', 'BP Max',
        'Skill 3 Max', 'Skill 3 Fast', 'Skill 3 Respawn', 'Skill 3 100S', 'Skill 3 NoMo 100S',
        'Skill 2 Max', 'Skill 2 Fast', 'Skill 2 Respawn', 'Skill 2 100S', 'Skill 2 NoMo 100S',
        'Skill 1 Max', 'Skill 1 Fast', 'Skill 1 Respawn', 'Skill 1 100S', 'Skill 1 NoMo 100S'
    ]
    ALL_KILLS_CATEGORIES = [
        'UV Max', 'UV Fast', 'UV Respawn', 'UV Tyson', 'Skill 3 Max', 'Skill 3 Fast',
        'Skill 3 Respawn', 'Skill 3 Tyson', 'Skill 2 Max', 'Skill 2 Fast', 'Skill 2 Respawn',
        'Skill 2 Tyson', 'Skill 1 Max', 'Skill 1 Fast', 'Skill 1 Respawn', 'Skill 1 Tyson'
    ]
    # TODO: Fix this in DSDA-Doom
    DOOM_CATEGORY_MAP = {'UV Tyson': 'Tyson'}
    BOOLEAN_INT_KEYS = ['nomonsters', 'respawn', 'fast', 'pacifist', 'stroller', 'almost_reality'
                        '100k', '100s', 'weapon_collector', 'tyson_weapons', 'turbo']

    IWAD_TO_SECRET_EXIT_MAP = {
        'doom': {'E1M3': 'E1M9', 'E2M5': 'E2M9', 'E3M6': 'E3M9', 'E4M2': 'E4M9'},
        'doom2': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'plutonia': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'tnt': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'heretic': {'E1M6': 'E1M9', 'E2M4': 'E2M9', 'E3M4': 'E3M9', 'E4M4': 'E4M9', 'E5M3': 'E5M9'}
    }
    D2ALL_DEFAULT = ['Map 01', 'Map 30']
    EPISODE_DEFAULTS = {
        'doom': [['E1M1', 'E1M8'], ['E2M1', 'E2M8'], ['E3M1', 'E3M8'], ['E4M1', 'E4M8']],
        'doom2': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        'plutonia': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        'tnt': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        # One less map for episode 6 since E6M1 won't appear in the levelstat due to having no exit
        # TODO: Handle this better
        'heretic': [['E1M1', 'E1M8'], ['E2M1', 'E2M8'], ['E3M1', 'E3M8'], ['E4M1', 'E4M8'],
                    ['E5M1', 'E5M8'], ['E6M1', 'E6M2']],
        # TODO: This won't actually be accurate until Chex levelstat is fixed
        'chex': [['E1M1', 'E1M5']]
    }
    ALL_IWADS = ['doom.wad', 'doom2.wad', 'plutonia.wad', 'tnt.wad']

    CERTAIN_KEYS = ['levelstat', 'time', 'level', 'kills', 'items', 'secrets', 'secret_exit', 'wad']
    POSSIBLE_KEYS = ['category']

    def __init__(self, lmp_path, wad_guesses, demo_info=None):
        """Initialize playback data class.

        :param lmp_path: Path to the LMP file
        :param wad_guesses: List of WAD guesses ordered from most likely to least likely
        :param demo_info: Miscellaneous additional info about the demo useful for demo playback and
                          categorization
        """
        self._cleanup()

        # -fastdemo: Play back demo as fast as possible, this is better than timedemo since it does
        #            not display any tic statistics afterwards, so DSDA-Doom doesn't hang waiting
        #            for user input
        self.command = '{} -fastdemo "{}"'.format(PlaybackData.DSDA_DOOM_COMMAND_START, lmp_path)
        self.lmp_path = lmp_path
        self.playback_failed = False

        self.demo_info = demo_info if demo_info else {}
        self._append_misc_args()

        self.wad_guesses = wad_guesses
        self.data = {}
        self.raw_data = {}
        self.note_strings = set()

    def analyze(self):
        self._playback()

    def populate_data_manager(self, data_manager):
        # The following data points are set for the playback parser:
        #   - Certain: levelstat, time, level, kills, items, secrets, wad
        #   - Somewhat certain: category
        for key, value in self.data.items():
            if key in PlaybackData.CERTAIN_KEYS:
                data_manager.insert(key, value, DataManager.CERTAIN, source='playback')
            elif key in PlaybackData.POSSIBLE_KEYS:
                data_manager.insert(key, value, DataManager.POSSIBLE, source='playback')
            else:
                raise ValueError('Unrecognized key found in data dictionary: {}.'.format(key))

    def _cleanup(self):
        """Cleanup analysis and levelstat files, if they exist."""
        try:
            os.remove(PlaybackData.ANALYSIS_FILENAME)
            os.remove(PlaybackData.LEVELSTAT_FILENAME)
        except OSError:
            pass

    def _append_misc_args(self):
        """Append miscellaneous arguments to the playback command based on demo info."""
        if not self.demo_info:
            return

        # This may not always be necessary, as later PrBoom+ and DSDA-Doom demos have -solo-net in
        # the footer, but this is necessary for older demos.
        # TODO: Consider running solo-net even if it's not detected for each demo in case of desync
        if self.demo_info.get('is_solo_net', False):
            self.command = '{} -solo-net'.format(self.command)

        iwad = self.demo_info.get('iwad', '').lower()
        if iwad == 'chex.wad':
            self.command = '{} -iwad chex -exe chex'.format(self.command)
        if iwad == 'heretic.wad':
            self.command = '{} -iwad heretic -heretic'.format(self.command)

    def _check_wad_existence(self, wad):
        """Check that the WAD exists locally.

        Download wad if it does not exist. Downloads will only be done from DSDA because in order
        for an upload to even be possible, we need the WAD to be on DSDA, in which case it would
        probably already be in the local config files anyway. Additionally, not every WAD is on
        idgames, and WADs on DSDA may not match the same name WADs on idgames anyway (which would be
        a problem but out of scope of this script). Additionally, a single download location is
        simpler.

        For WADs that could not be guessed or are not on DSDA, the script will have a separate
        output location where it will list what it could determine about the WADs, which could then
        be manually uploaded. (TODO)

        Mismatches between idgames and DSDA will need to be handled by a separate utility. (TODO)

        :param wad: WAD object to check for
        :raises RuntimeError if the WAD could not be downloaded.
        """
        dsda_doom_dirlist = [file.lower() for file in os.listdir(CONFIG.dsda_doom_directory)]
        local_wad_location = None
        for wad_file, wad_info in wad.files.items():
            if wad_info.get('not_required_for_playback', False):
                continue

            wad_checksum = wad_info['checksum']
            if wad_file in dsda_doom_dirlist:
                if wad_checksum == checksum(os.path.join(CONFIG.dsda_doom_directory, wad_file)):
                    continue

            if local_wad_location is None:
                zip_location = download_wad_from_dsda(wad.dsda_url) if wad.dsda_url else None
                if not zip_location:
                    raise RuntimeError('Could not download wad {}.'.format(wad.name))

                local_wad_location = zip_extract(zip_location)

            copyfile(os.path.join(local_wad_location, wad_file),
                     os.path.join(CONFIG.dsda_doom_directory, wad_file))

        if local_wad_location:
            rmtree(local_wad_location)

    def _playback(self):
        """Play back demo and categorize it.

        :raises RuntimeError if the WAD could not be guessed for this demo
        """
        wad_guessed = False
        for wad_guess in self.wad_guesses:
            try:
                self._check_wad_existence(wad_guess)
            except RuntimeError:
                LOGGER.error('Wad %s not available.', wad_guess.name)
                continue

            # TODO: Some WADs have fix files and optional files that may or may not be needed for
            #       loading for playback; we need to account for this, probably as follows:
            #         - if demo has a footer, use the fixfiles present there
            #         - if not, try all combos of fix files
            self.command = '{} -iwad {} {}'.format(self.command, wad_guess.iwad,
                                                   wad_guess.playback_cmd_line)
            # LOGGER.info(self.command)
            try:
                run_cmd(self.command)
            except subprocess.CalledProcessError as e:
                LOGGER.warning('Failed to play back demo %s.', self.lmp_path)
                LOGGER.debug('Error message: %s.', e)
            # Technically, there could be edge cases where a levelstat could be generated even if
            # the wrong WAD is used (e.g., thissuxx). I'm not sure if there's any reasonable way to
            # fix this, though.
            # TODO: Perhaps a hardcoded exception list for when this guess might not be trusted is
            #       needed (depends how likely the wrong guess is)
            if os.path.isfile(self.LEVELSTAT_FILENAME):
                dsda_wad_name = (
                    wad_guess.dsda_name
                    if wad_guess.dsda_name else get_wad_name_from_dsda_url(wad_guess.dsda_url)
                )
                self.data['wad'] = dsda_wad_name
                self._parse_analysis()
                if self.data['category'] == 'Other':
                    self._get_actual_category()
                self._parse_levelstat(wad_guess)

                # TODO: Additional processing needed for maps that are max exceptions; for a
                #       complete fix, this will need DSDA-Doom to output missed monster/secret IDs
                self._parse_raw_data(wad_guess)
                complevel = self.demo_info.get('complevel')
                if complevel:
                    if int(wad_guess.complevel) != int(complevel):
                        self.note_strings.add('Incompatible')

                wad_guessed = True
                break

        if not wad_guessed:
            LOGGER.error('Could not guess wad for demo %s.', self.lmp_path)
            self.playback_failed = True

    def _parse_raw_data(self, wad):
        """Parse additional info available in raw data.

        This is mostly for special cases that are not handled by DSDA-Doom as they depend on the
        WAD itself.

        :param wad: WAD object
        """
        is_nomo = self.raw_data.get('nomonsters', False)
        level_info = wad.map_info.get(self.data['level'], {})
        if is_nomo:
            # In some cases, we might actually want to default nomo to have Reality tags (e.g.,
            # Doom 2 map 25 or All Hell map 3 which has lost souls on nomo due to Dehacked).
            if not level_info.get('add_reality_in_nomo', False):
                return

        # Some maps don't need a Reality marker if it is trivial (e.g., many nomonsters maps).
        # TODO: This setting might not be write on different skill levels, co-op, solo-net:
        #       Long-term, the config should be able to at least support co-op and solo-net
        if level_info.get('skip_reality'):
            return

        if self.raw_data.get('reality', False):
            self.note_strings.add('Also Reality')
        elif not is_nomo and self.raw_data.get('almost_reality', False):
            # TODO: This probably should be configurable, but I'm not sure of any cases where this
            #       is really needed.
            # Will not add Almost Reality in nomo for now
            self.note_strings.add('Also Almost Reality')

    def _get_actual_category(self):
        """Stub for getting actual category for other skills; this might duplicate DSDA-Doom's
           category logic, so it might not belong here."""
        if int(self.raw_data['skill']) != 4:
            # TODO: maybe this should be in the port?
            pass

    def _parse_analysis(self):
        """Parse analysis info.

        Analysis format:
          skill 4
          nomonsters 0
          respawn 0
          fast 0
          pacifist 0
          stroller 0
          reality 0
          almost_reality 0
          100k 1
          100s 1
          missed_monsters 0
          missed_secrets 0
          weapon_collector 0
          tyson_weapons 0
          turbo 0
          category UV Max
        """
        with open(self.ANALYSIS_FILENAME) as analysis_strm:
            analysis = analysis_strm.read()

        for line in analysis.splitlines():
            key, value = line.split(maxsplit=1)
            if key in self.BOOLEAN_INT_KEYS:
                value = False if int(value) == 0 else True
            if key == 'turbo' and value:
                # This will need manual effort to actually figure out what kind of turbo usage is
                # performed, which will be handled later.
                self.note_strings.add('Uses turbo')
            if key == 'category':
                if not self.demo_info.get('is_heretic', False):
                    self.data['category'] = PlaybackData.DOOM_CATEGORY_MAP.get(value, value)
                else:
                    # TODO: Heretic categories still incorrect in analysis, need to add a custom map
                    self.data['category'] = NEEDS_ATTENTION_PLACEHOLDER

            self.raw_data[key] = value

    def _has_required_secret_maps(self, wad, map_list):
        """Determine whether all required secret maps (if any) were visited by the demo.

        :param wad: WAD object
        :param map_list: Map list that is covered by the demo.
        :return: Flag indicating if all required secret maps (if any) were visited by the demo.
        """
        category = self.data['category']
        secret_maps = []
        if (category not in PlaybackData.ALL_SECRETS_CATEGORIES and
                category not in PlaybackData.ALL_KILLS_CATEGORIES):
            return True

        secret_exits = wad.map_info.get('secret_exits',
                                        PlaybackData.IWAD_TO_SECRET_EXIT_MAP.get(wad.iwad))
        if not secret_exits:
            return True

        for secret_exit, secret_map in secret_exits.items():
            if secret_exit in map_list:
                if category in PlaybackData.ALL_SECRETS_CATEGORIES:
                    secret_maps.append(secret_map)
                else:
                    # Categories that do not require secrets do not need to visit nomonster maps.
                    if not wad.map_info.get(secret_map, {}).get('has_no_kills', False):
                        secret_maps.append(secret_map)

        for map in secret_maps:
            if map not in map_list:
                return False

        return True

    def _detect_movie_type(self, wad, map_list):
        """Detect movie type for a given demo.

        :param wad: WAD object
        :param map_list: Map list that is covered by the demo.
        """
        # Note that while this pulls from the secret exits dictionary, it is actually the exits
        # mapped to the maps they go to, and this pulls the values only
        secret_maps = wad.map_info.get(
            'secret_exits', PlaybackData.IWAD_TO_SECRET_EXIT_MAP.get(wad.iwad)
        ).values()
        # Technically a WAD can start or end on secret maps, and it's unclear in cases like that if
        # UV-Speeds should start/visit those, but for the sake of consistency, will keep it this
        # way for now.
        first_non_secret_map = None
        last_non_secret_map = None
        for cur_map in map_list:
            if cur_map in secret_maps:
                continue
            if not first_non_secret_map:
                first_non_secret_map = cur_map

            last_non_secret_map = cur_map

        has_required_secret_maps = self._has_required_secret_maps(wad, map_list)
        map_range = [first_non_secret_map, last_non_secret_map]
        if has_required_secret_maps:
            episodes = wad.map_info.get('episodes', PlaybackData.EPISODE_DEFAULTS.get(wad.iwad, []))
            if map_range == wad.map_info.get('d2all', PlaybackData.D2ALL_DEFAULT):
                self.data['level'] = 'D2All'
            # D2ALLs are set when a Doom 1 wad isn't a complete episode.
            elif map_range == wad.map_info.get('d1all'):
                self.data['level'] = 'D1All'
            elif episodes:
                for idx, episode_range in enumerate(episodes):
                    if map_range == episode_range:
                        self.data['level'] = 'Episode {}'.format(idx + 1)

            if not self.data.get('level'):
                self.data['level'] = 'Other Movie'
                self.note_strings.add('Other Movie {} - {}'.format(first_non_secret_map,
                                                                   last_non_secret_map))
        else:
            self.data['level'] = 'Other Movie'
            self.note_strings.add('Other Movie {} - {}'.format(first_non_secret_map,
                                                               last_non_secret_map))
            self.note_strings.add('Does not visit secret maps.')

    def _parse_levelstat(self, wad):
        """Parse levelstat info.

        Levelstat format:
          MAP01 - 1:23.00 (1:23)  K: 1337/1337  I: 69/69  S: 420/420
          MAP02 - 1:11.97 (2:34)  K: 0/0  I: 0/0  S: 0/0

        :param wad: WAD object
        """
        with open(self.LEVELSTAT_FILENAME) as levelstat_strm:
            levelstat = levelstat_strm.read()

        levelstat = levelstat.splitlines()
        # IL run case
        if len(levelstat) == 1:
            # TODO: Add logic to override secret exit marker (e.g., Sunlust map 31)
            levelstat_line_split = levelstat[0].split()
            self.data['level'] = self._get_level(levelstat_line_split, wad)
            self.data['secret_exit'] = self.data['level'].endswith('s')
            time = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_TIME_IDX]
            self.data['time'] = time
            self.data['levelstat'] = time
            self.data['kills'] = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_KILLS_IDX]
            self.data['items'] = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_ITEMS_IDX]
            self.data['secrets'] = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_SECRETS_IDX]
        else:
            self.data['secret_exit'] = False
            if not self.demo_info.get('is_chex', False):
                # TODO: Is there a cleaner way to parse out the times here?
                self.data['time'] = levelstat[-1].split()[
                    PlaybackData.LEVELSTAT_LINE_TOTAL_TIME_IDX
                ].replace('(', '').replace(')', '')

                self.data['levelstat'] = ','.join(
                    [line.split()[PlaybackData.LEVELSTAT_LINE_TIME_IDX].split('.')[0]
                     for line in levelstat]
                )

                map_list = []
                for line in levelstat:
                    level = self._get_level(line.split(), wad)
                    map_list.append(level)

                self._detect_movie_type(wad, map_list)
            else:
                self.data['level'] = NEEDS_ATTENTION_PLACEHOLDER
                self.data['time'] = NEEDS_ATTENTION_PLACEHOLDER
                self.data['levelstat'] = NEEDS_ATTENTION_PLACEHOLDER

    def _get_level(self, levelstat_line_split, wad):
        """Get level from levelstat split into lines.

        This returns a dummy value and sets a note if the level run isn't actually a map in the WAD.

        :param levelstat_line_split: Levelstat split into lines
        :param wad: WAD object
        :return: Level in levelstat
        :raises ValueError if there's an issue parsing map ranges for WAD object
        """
        level = self._convert_level_to_dsda_format(
            levelstat_line_split[PlaybackData.LEVELSTAT_LINE_LEVEL_IDX]
        )
        map_ranges = wad.map_info.get('map_ranges')
        if map_ranges:
            level_num = self._convert_level_to_num(level)
            for map_range in map_ranges:
                try:
                    map_range = parse_range(map_range, remove_non_numeric_chars=True)
                except ValueError:
                    LOGGER.error('Issue parsing ranges for WAD %s.', wad.name)
                    raise

                map_range[1] += 1
                if level_num in range(*map_range):
                    return level

        self.note_strings.add('Run for map that is not part of the wad.')
        return NEEDS_ATTENTION_PLACEHOLDER

    @staticmethod
    def _convert_level_to_dsda_format(level_str):
        """Convert level text from levelstat format to DSDA format.

        :param level_str: Level string from levelstat
        :return: Level string in DSDA format
        """
        # Doom 2 case (MAP##)
        if 'MAP' in level_str:
            return level_str.replace('MAP', 'Map ')

        # Doom 1 case (E#M#)
        return level_str

    @staticmethod
    def _convert_level_to_num(level_str):
        """Convert level text from levelstat/DSDA formats to number.

        :param level_str: Level string from levelstat or DSDA
        :return: Level number
        """
        # Replace any secret exit marker
        level_str = level_str.replace('s', '')
        if 'MAP' in level_str:
            return int(level_str.replace('MAP', ''))
        elif 'Map ' in level_str:
            return int(level_str.replace('Map ', ''))

        return int(level_str.replace('E', '').replace('M', ''))
