"""
Parse data out of DSDA-Doom playback of the LMP.
"""

import logging
import os
import re
import subprocess

from collections import Counter
from dataclasses import dataclass, field
from shutil import copyfile, rmtree

from .base_parser import BaseData
from .data_manager import DataManager
from .dsda import download_wad_from_dsda, get_wad_name_from_dsda_url
from .upload_config import CONFIG, NEEDS_ATTENTION_PLACEHOLDER
from .utils import checksum, parse_range, run_cmd, zip_extract, compare_iwad, \
    get_single_key_value_dict
from .wad import Wad


LOGGER = logging.getLogger(__name__)


class PlaybackData(BaseData):
    """Store all uploader-relevant data obtainable using DSDA-Doom.

    This includes data from levelstat.txt as well as the analysis.txt files.
    """
    # -levelstat: Create a levelstat.txt file with level statistics
    # -analysis: Create an analysis.txt file with additional analysis on the demo
    # -quiet: Suppress a bunch of playback logging from DSDA-Doom
    DEFAULT_ARGS = '-levelstat -analysis -nosound -nomusic -nodraw -quiet'
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
    LEVELSTAT_LINE_ITEMS_COOP_IDX = 8
    LEVELSTAT_LINE_SECRETS_COOP_IDX = 11
    PAREN_WITH_OFFSET_RE = re.compile(r'\(\s+')

    ALL_SECRETS_CATEGORIES = [
        'UV Max', 'UV Fast', 'UV Respawn', 'NM 100S', 'NoMo 100S', 'SM Max', 'BP Max',
        'Skill 3 Max', 'Skill 3 Fast', 'Skill 3 Respawn', 'Skill 3 100S', 'Skill 3 NoMo 100S',
        'Skill 2 Max', 'Skill 2 Fast', 'Skill 2 Respawn', 'Skill 2 100S', 'Skill 2 NoMo 100S',
        'Skill 1 Max', 'Skill 1 Fast', 'Skill 1 Respawn', 'Skill 1 100S', 'Skill 1 NoMo 100S'
    ]
    ALL_KILLS_CATEGORIES = [
        'UV Max', 'UV Fast', 'UV Respawn', 'UV Tyson', 'Tyson', 'Skill 3 Max', 'Skill 3 Fast',
        'Skill 3 Respawn', 'Skill 3 Tyson', 'Skill 2 Max', 'Skill 2 Fast', 'Skill 2 Respawn',
        'Skill 2 Tyson', 'Skill 1 Max', 'Skill 1 Fast', 'Skill 1 Respawn', 'Skill 1 Tyson'
    ]
    # TODO: Fix this in DSDA-Doom
    DOOM_CATEGORY_MAP = {'UV Tyson': 'Tyson'}
    BOOLEAN_INT_KEYS = ['nomonsters', 'respawn', 'fast', 'pacifist', 'stroller', 'almost_reality',
                        '100k', '100s', 'weapon_collector', 'tyson_weapons', 'turbo', 'reality']

    CERTAIN_KEYS = ['levelstat', 'time', 'level', 'kills', 'items', 'secrets', 'secret_exit', 'wad',
                    'is_solo_net']
    POSSIBLE_KEYS = ['category']

    DOOM_1_MAP_RE = re.compile(r'^E(?P<episode_num>\d)M\ds?$')

    ALLOWED_FOOTER_FILES = ['bloodcolor.deh', 'bloodfix.deh', 'doom widescreen hud.wad',
                            'doom 2 widescreen assets.wad', 'dsda-doom.wad', 'prboom-plus.wad',
                            'doom_wide.wad', 'notransl.deh', 'doomgirl_01.wad', 'good.deh']
    CHEX_ADDITIONAL_FOOTER_FILES = ['chex.deh', 'chexehud.wad']
    FOOTER_WAD_EXTENSIONS = ['.bex', '.deh', '.hhe', '.pk3', '.pk7', '.wad']

    def __init__(self, lmp_path, wad_guesses, demo_info=None):
        """Initialize playback data class.

        :param lmp_path: Path to the LMP file
        :param wad_guesses: List of WAD guesses ordered from most likely to least likely
        :param demo_info: Miscellaneous additional info about the demo useful for demo playback and
                          categorization
        """
        super().__init__()
        self._cleanup()

        # -fastdemo: Play back demo as fast as possible, this is better than timedemo since it does
        #            not display any tic statistics afterwards, so DSDA-Doom doesn't hang waiting
        #            for user input
        self.base_command = '{} -fastdemo "{}"'.format(PlaybackData.DSDA_DOOM_COMMAND_START,
                                                       lmp_path)
        self.lmp_path = lmp_path
        self.playback_failed = False

        self.demo_info = demo_info if demo_info else {}
        self._append_misc_args()

        self.url_to_wad = {wad.dsda_url: wad for wad in wad_guesses}
        self.wad_guesses = Counter([wad.dsda_url for wad in wad_guesses])
        self.data = {}
        self.raw_data = {}
        self.note_strings = set()

        self._demo_playback = None

    def analyze(self):
        """Analyze info provided to playback parser."""
        self._playback()

    def populate_data_manager(self, data_manager):
        """Populate data manager with info from post.

        :param data_manager: Data manager to populate
        """
        for key, value in self.data.items():
            if (key in PlaybackData.CERTAIN_KEYS or
                    (key == 'category' and CONFIG.trust_dsda_doom_category)):
                data_manager.insert(key, value, DataManager.CERTAIN, source='playback')
            elif key in PlaybackData.POSSIBLE_KEYS:
                data_manager.insert(key, value, DataManager.POSSIBLE, source='playback')
            else:
                raise ValueError('Unrecognized key found in data dictionary: {}.'.format(key))

    @staticmethod
    def _cleanup():
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

        num_players = self.demo_info.get('num_players')
        if num_players and num_players > 1:
            self.demo_info['game_mode'] = 'coop'
        else:
            self.demo_info['game_mode'] = 'single_player'

        raw_skill = self.demo_info['skill']
        if raw_skill:
            raw_skill = int(raw_skill)
            if 0 < raw_skill < 3:
                self.demo_info['skill'] = 'easy'
            elif raw_skill == 3:
                self.demo_info['skill'] = 'medium'
            elif 3 < raw_skill < 6:
                self.demo_info['skill'] = 'hard'
            else:
                LOGGER.error('Invalid skill %s passed to playback parser.', raw_skill)
                self.demo_info['skill'] = None

        iwad = self.demo_info.get('iwad', '').lower()
        if compare_iwad(iwad, 'chex'):
            self.base_command = '{} -iwad chex'.format(self.base_command)
        if compare_iwad(iwad, 'heretic'):
            self.base_command = '{} -iwad commercial/heretic -heretic'.format(self.base_command)
        if compare_iwad(iwad, 'hexen'):
            self.base_command = '{} -iwad commercial/hexen -hexen'.format(self.base_command)

    @staticmethod
    def _check_wad_existence(wad):
        """Check that the WAD exists locally.

        Download wad if it does not exist. Downloads will only be done from DSDA because in order
        for an upload to even be possible, we need the WAD to be on DSDA, in which case it would
        probably already be in the local config files anyway. Additionally, not every WAD is on
        idgames, and WADs on DSDA may not match the same name WADs on idgames anyway (which would be
        a problem but out of scope of this script). Additionally, a single download location is
        simpler.

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
                     os.path.join(CONFIG.dsda_doom_directory, os.path.basename(wad_file)))

        if local_wad_location:
            rmtree(local_wad_location)

    def _playback(self):
        """Play back demo and categorize it.

        :raises RuntimeError if the WAD could not be guessed for this demo
        """
        # TODO: If there is no complevel info and it's a vanilla complevel, probably should try to
        #       force every available complevel (2-4)
        for url, _ in self.wad_guesses.most_common():
            wad_guess = self.url_to_wad[url]
            # If this is a WAD update, the DSDA page may not be available yet.
            if not wad_guess.commercial and not 'update/' in wad_guess.playback_cmd_line:
                try:
                    self._check_wad_existence(wad_guess)
                except RuntimeError:
                    LOGGER.error('Wad %s not available.', wad_guess.name)
                    continue

            # Prefer the primary playback CMD line; if it doesn't work, look through the
            # alternatives
            playback_cmd_lines = [wad_guess.playback_cmd_line] + wad_guess.alt_playback_cmd_lines
            if CONFIG.always_try_solonet:
                if '-solo-net' not in self.base_command:
                    playback_cmd_lines.extend(
                        [f'{cmd} -solo-net' for cmd in playback_cmd_lines]
                    )
            # TASDooM demos sometimes require manually providing the complevel
            if self.demo_info.get('source_port') == 'TASDooM':
                playback_cmd_lines.extend(
                    [f'{cmd} -complevel 5' for cmd in playback_cmd_lines]
                )
            footer_files_lower = [footer_file.lower()
                                  for footer_file in self.demo_info.get('footer_files', [])]
            if 'good.deh' in footer_files_lower or CONFIG.always_try_good_at_doom:
                all_cmds_with_good_deh = [f'{cmd} -deh good' for cmd in playback_cmd_lines]
                playback_cmd_lines.extend([{cmd: 'Good at DooM: gib yourself to end the level.'}
                                           for cmd in all_cmds_with_good_deh])

            for cmd_line in playback_cmd_lines:
                if isinstance(cmd_line, dict):
                    cmd_line, cmd_line_info = get_single_key_value_dict(cmd_line)
                    if isinstance(cmd_line_info, str):
                        cmd_line_info = {'note': cmd_line_info}
                else:
                    cmd_line_info = None

                command = '{} -iwad commercial/{} {}'.format(self.base_command, wad_guess.iwad,
                                                             cmd_line)
                try:
                    run_cmd(command)
                except subprocess.CalledProcessError as e:
                    LOGGER.warning('Failed to play back demo %s.', self.lmp_path)
                    LOGGER.debug('Error message: %s.', e)
                # Technically, there could be edge cases where a levelstat could be generated even
                # if the wrong WAD is used (e.g., thissuxx map 1 will exit on pretty much any demo
                # that is long enough). If the run_through_all_cmd_line_options option is on, such
                # cases will be decided based on which playback completed the most maps. Otherwise,
                # we will just take the first playback that succeeds.
                if os.path.isfile(PlaybackData.LEVELSTAT_FILENAME):
                    with open(PlaybackData.LEVELSTAT_FILENAME) as levelstat_strm:
                        cur_levelstat = levelstat_strm.read()
                    with open(PlaybackData.ANALYSIS_FILENAME) as analysis_strm:
                        cur_analysis = analysis_strm.read()

                    cur_demo_playback = DemoPlayback(wad_guess, command, cur_levelstat,
                                                     cur_analysis, cmd_line_info=cmd_line_info)
                    wad_files = [os.path.basename(wad_file.lower())
                                 for wad_file in cur_demo_playback.wad.files.keys()]
                    unexpected_file = False
                    for footer_file in self.demo_info.get('footer_files', []):
                        footer_file_lower = os.path.basename(footer_file.lower())
                        footer_file_ext = os.path.splitext(footer_file_lower)[1]
                        if not footer_file_ext:
                            footer_file_lower = f'{footer_file_lower}.wad'
                            footer_file_ext = '.wad'
                        if (footer_file_lower not in wad_files and
                                footer_file_lower != f'{cur_demo_playback.wad.iwad}.wad' and
                                footer_file_lower not in PlaybackData.ALLOWED_FOOTER_FILES and
                                footer_file_ext in PlaybackData.FOOTER_WAD_EXTENSIONS):
                            if (cur_demo_playback.wad.iwad == 'chex' and
                                    footer_file_lower not in self.CHEX_ADDITIONAL_FOOTER_FILES):
                                LOGGER.error('Unexpected file %s found in footer for WAD %s.',
                                             footer_file, cur_demo_playback.wad.name)
                                unexpected_file = True
                                break

                    if unexpected_file:
                        continue

                    if not self._demo_playback or self._demo_playback < cur_demo_playback:
                        self._demo_playback = cur_demo_playback

                    self._cleanup()
                    if not CONFIG.run_through_all_cmd_line_options:
                        break

            if not CONFIG.run_through_all_cmd_line_options and self._demo_playback:
                break

        if self._demo_playback:
            if not self.playback_failed:
                if '-solo-net' in self._demo_playback.cmd:
                    self.demo_info['game_mode'] = 'coop'
                    self.data['is_solo_net'] = True
                    self.note_strings.add('Plays back with forced -solo-net')
                if '-complevel 5' in self._demo_playback.cmd:
                    self.note_strings.add('Plays back with forced -complevel 5')

                dsda_wad_name = (self._demo_playback.wad.dsda_name
                                 if self._demo_playback.wad.dsda_name
                                 else get_wad_name_from_dsda_url(self._demo_playback.wad.dsda_url))
                self.data['wad'] = dsda_wad_name
                self._parse_analysis()
                self._parse_levelstat()
                self._parse_raw_data()
                complevel = self.demo_info.get('complevel')
                if complevel:
                    if int(self._demo_playback.wad.complevel) != int(complevel):
                        self.note_strings.add('Incompatible')

                if self._demo_playback.cmd_line_info:
                    wad_update = self._demo_playback.cmd_line_info.get('update_wad')
                    note = self._demo_playback.cmd_line_info.get('note')
                    if wad_update:
                        self.data['wad'] = wad_update
                    if note:
                        self.note_strings.add(note)
        else:
            LOGGER.error('Could not guess wad for demo %s.', self.lmp_path)
            self.playback_failed = True

    def _parse_raw_data(self):
        """Parse additional info available in raw data.

        This is mostly for special cases that are not handled by DSDA-Doom as they depend on the
        WAD itself.
        """
        # TODO: Skipping multi-level runs for now, this needs to be refactored a bit to be cleaner
        #       first
        # TODO: Additional processing needed for maps that are max exceptions; for a
        #       complete fix, this will need DSDA-Doom to output missed monster/secret
        #       IDs
        if len(self.raw_data['affected_levels']) > 1:
            return

        map_info = self._demo_playback.wad.map_list_info.get_map_info(
            self.raw_data['affected_levels'][0]
        )
        skill = self.demo_info.get('skill')
        game_mode = self.demo_info.get('game_mode')

        # If a run was a valid Tyson (only Tyson weapons used and 100% kills) and the map is not
        # Tyson-only, we always choose the Tyson category for the final run instead of UV Max.
        if self.raw_data.get('tyson_weapons', False) and self.raw_data.get('100k', False):
            tyson_only = map_info.get_single_key_for_map('tyson_only', skill=skill,
                                                         game_mode=game_mode)
            if not tyson_only and self.data['category'] == 'UV Max':
                self.data['category'] = 'Tyson'

        is_nomo = self.raw_data.get('nomonsters', False)
        skip_reality = map_info.get_single_key_for_map('skip_reality', skill=skill,
                                                       game_mode=game_mode)
        skip_reality_categories = map_info.get_single_key_for_map('skip_reality_for_categories',
                                                                  skill=skill, game_mode=game_mode)
        skip_reality_final = skip_reality or (skip_reality_categories is not None and
                                              self.data['category'] in skip_reality_categories)
        if self.raw_data.get('reality', False):
            add_reality_tag = True
            if is_nomo and not map_info.get_single_key_for_map('add_reality_in_nomo', skill=skill,
                                                               game_mode=game_mode):
                add_reality_tag = False
            if skip_reality_final:
                add_reality_tag = False

            if add_reality_tag:
                self.note_strings.add('Also Reality')
        elif self.raw_data.get('almost_reality', False):
            add_almost_reality_tag = True
            skip_almost_reality = map_info.get_single_key_for_map('skip_almost_reality',
                                                                  skill=skill, game_mode=game_mode)
            skip_almost_reality_categories = map_info.get_single_key_for_map(
                'skip_almost_reality_for_categories', skill=skill, game_mode=game_mode
            )
            skip_almost_reality_final = (
                skip_almost_reality or (skip_almost_reality_categories is not None and
                                        self.data['category'] in skip_almost_reality_categories)
            )
            if is_nomo and not map_info.get_single_key_for_map('add_almost_reality_in_nomo',
                                                               skill=skill, game_mode=game_mode):
                add_almost_reality_tag = False
            if skip_reality_final or skip_almost_reality_final:
                add_almost_reality_tag = False

            if add_almost_reality_tag:
                self.note_strings.add('Also Almost Reality')

        # If a run was a Stroller, choose the Stroller category over UV-Speed, as this will happen
        # for maps with no monsters.
        if self.raw_data.get('stroller', True) and self.data['category'] == 'UV Speed':
            self.data['category'] = 'Stroller'

        skip_also_pacifist = map_info.get_single_key_for_map('skip_also_pacifist', skill=skill,
                                                             game_mode=game_mode)
        skip_also_pacifist_categories = map_info.get_single_key_for_map(
            'skip_also_pacifist_for_categories', skill=skill, game_mode=game_mode
        )
        skip_also_pacifist_final = skip_also_pacifist or (
            skip_also_pacifist_categories is not None and
            self.data['category'] in skip_also_pacifist_categories
        )
        # If a run is not UV-Speed/Pacifist or on nomonsters, add tag for Also Pacifist
        if not skip_also_pacifist_final and (self.raw_data.get('pacifist', False)
                                             and not self.raw_data.get('nomonsters', False) and
                                             self.data['category'] not in ['Pacifist', 'Stroller',
                                                                           'UV Speed']):
            self.note_strings.add('Also Pacifist')

        # Jumpwad has special rules for categories:
        #   - Pacifist doesn't exist.
        #   - UV-Max requires items.
        if self.data['wad'] == 'jumpwad':
            all_items = True
            for stats in self.raw_data['stats']:
                items_gotten, total_items = stats['items'].split('/')
                if items_gotten != total_items:
                    all_items = False
                    break

            if not all_items and self.data['category'] == 'UV Max':
                self.data['category'] = 'UV Speed'
            elif self.data['category'] == 'Pacifist':
                self.data['category'] = 'UV Speed'

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
        for line in self._demo_playback.analysis.splitlines():
            key, value = line.split(maxsplit=1)
            if key in self.BOOLEAN_INT_KEYS:
                value = False if int(value) == 0 else True
            if key == 'turbo' and value:
                # This will need manual effort to actually figure out what kind of turbo usage is
                # performed, which will be handled later.
                self.note_strings.add('Uses turbo')
            if key == 'category':
                # TODO: Heretic categories still incorrect in analysis, need DSDA-Doom fix
                self.data['category'] = PlaybackData.DOOM_CATEGORY_MAP.get(value, value)

            self.raw_data[key] = value

    def _parse_levelstat(self):
        """Parse levelstat info.

        Levelstat format:
          MAP01 - 1:23.00 (1:23)  K: 1337/1337  I: 69/69  S: 420/420
          MAP02 - 1:11.97 (2:34)  K: 0/0  I: 0/0  S: 0/0
        In case of co-op:
          E3M7 - 0:26.97 (0:26)  K: 3/38 (3+0)  I: 0/8 (0+0)  S: 0/4  (0+0)
        """
        levelstat = self._demo_playback.levelstat.splitlines()
        skill = self.demo_info.get('skill')
        game_mode = self.demo_info.get('game_mode')
        # IL run case
        if len(levelstat) == 1:
            levelstat_line_split = levelstat[0].split()
            self.data['level'] = self._get_level(levelstat_line_split, self._demo_playback.wad)
            self.data['secret_exit'] = self.data['level'].endswith('s')
            level_no_secret_exit_marker = self.data['level'].rstrip('s')
            map_info = self._demo_playback.wad.map_list_info.get_map_info(
                level_no_secret_exit_marker
            )
            # Not sure this should be the no-secret exit marker map, since some things can be
            # different depending on secret exit.
            self.raw_data['affected_levels'] = [level_no_secret_exit_marker]
            if (self.data['category'] in PlaybackData.ALL_KILLS_CATEGORIES or
                    self.data['category'] in PlaybackData.ALL_SECRETS_CATEGORIES or
                    map_info.get_single_key_for_map('mark_secret_exit_as_normal', skill=skill,
                                                    game_mode=game_mode)):
                self.data['level'] = self.data['level'].rstrip('s')

            time = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_TIME_IDX]
            self.data['time'] = time
            self.data['levelstat'] = time
            stats_dict = PlaybackData._get_stats_from_levelstat_line(levelstat[0])
            self.raw_data['stats'] = [stats_dict]
            self.data['kills'] = stats_dict['kills']
            self.data['items'] = stats_dict['items']
            self.data['secrets'] = stats_dict['secrets']
        else:
            self.data['secret_exit'] = False
            # Final time will be printed in parens on the last line of the levelstat.
            self.data['time'] = levelstat[-1].split()[
                PlaybackData.LEVELSTAT_LINE_TOTAL_TIME_IDX
            ].replace('(', '').replace(')', '')

            self.data['levelstat'] = ','.join(
                [line.split()[PlaybackData.LEVELSTAT_LINE_TIME_IDX].split('.')[0]
                 for line in levelstat]
            )

            map_list = []
            self.raw_data['stats'] = []
            for line in levelstat:
                level = self._get_level(line.split(), self._demo_playback.wad)
                map_list.append(level.rstrip('s'))
                self.raw_data['stats'].append(PlaybackData._get_stats_from_levelstat_line(line))

            self._detect_movie_type(self._demo_playback.wad, map_list)
            self.raw_data['affected_levels'] = map_list

    @staticmethod
    def _get_stats_from_levelstat_line(levelstat_line):
        """Get kills/items/secrets stats from levelstat line.

        :param levelstat_line: Levelstat line
        :return: Levelstat line stats as a dictionary
        """
        stats_dict = {}
        # For movie runs, the open parentheses get offset with whitespace, which messes with
        # splitting the line, so we need to remove the whitespace before splitting.
        levelstat_line = PlaybackData.PAREN_WITH_OFFSET_RE.sub('(', levelstat_line)
        levelstat_line_split = levelstat_line.split()
        stats_dict['kills'] = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_KILLS_IDX]
        levelstat_split_len = len(levelstat_line_split)
        if levelstat_split_len == 10:
            stats_dict['items'] = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_ITEMS_IDX]
            stats_dict['secrets'] = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_SECRETS_IDX]
        elif levelstat_split_len == 13:
            stats_dict['items'] = levelstat_line_split[PlaybackData.LEVELSTAT_LINE_ITEMS_COOP_IDX]
            stats_dict['secrets'] = levelstat_line_split[
                PlaybackData.LEVELSTAT_LINE_SECRETS_COOP_IDX
            ]
        else:
            raise RuntimeError(f'Unrecognized levelstat line format: {levelstat_line}.')

        return stats_dict

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
        map_ranges = wad.map_list_info.get_key('map_ranges')
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

    def _detect_movie_type(self, wad, map_list):
        """Detect movie type for a given demo.

        The format for maps in the map list is either Map xx or ExMx. Secret exit markers are
        assumed to have already been stripped.

        :param wad: WAD object
        :param map_list: Map list that is covered by the demo.
        """
        # TODO: This won't work for Hexen
        # Note that while this pulls from the secret exits dictionary, it is actually the exits
        # mapped to the maps they go to, and this pulls the values only
        secret_maps = wad.map_list_info.get_key('secret_exits').values()
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

        # In case a WAD is restricted to the secret maps (e.g., teeth.wad, maps 31-32) :^)
        if not first_non_secret_map and not last_non_secret_map:
            first_non_secret_map = map_list[0]
            last_non_secret_map = map_list[-1]

        has_required_secret_maps = self._has_required_secret_maps(wad, map_list)
        map_range = [first_non_secret_map, last_non_secret_map]
        if has_required_secret_maps:
            # If the config sets these settings, use them even if they evaluate to None/empty
            episodes = wad.map_list_info.get_key('episodes')
            d2all = wad.map_list_info.get_key('d2all')
            d1all = wad.map_list_info.get_key('d1all')
            if map_range == d2all:
                self.data['level'] = 'D2All'
            elif map_range == d1all:
                self.data['level'] = 'D1All'
            elif episodes:
                for idx, episode_range in enumerate(episodes):
                    if map_range == episode_range:
                        doom_1_map_match = PlaybackData.DOOM_1_MAP_RE.match(map_range[0])
                        episode_num = (doom_1_map_match.group('episode_num') if doom_1_map_match
                                       else idx + 1)

                        self.data['level'] = 'Episode {}'.format(episode_num)

            if not self.data.get('level'):
                self.data['level'] = 'Other Movie'
                self.note_strings.add('Other Movie {} - {}'.format(first_non_secret_map,
                                                                   last_non_secret_map))
        else:
            self.data['level'] = 'Other Movie'
            self.note_strings.add('Other Movie {} - {}'.format(first_non_secret_map,
                                                               last_non_secret_map))
            self.note_strings.add('Does not visit secret maps.')

    def _has_required_secret_maps(self, wad, map_list):
        """Determine whether all required secret maps (if any) were visited by the demo.

        :param wad: WAD object
        :param map_list: Map list that is covered by the demo.
        :return: Flag indicating if all required secret maps (if any) were visited by the demo.
        """
        category = self.data['category']
        if (category not in PlaybackData.ALL_SECRETS_CATEGORIES and
                category not in PlaybackData.ALL_KILLS_CATEGORIES):
            return True

        secret_exits = wad.map_list_info.get_key('secret_exits')
        if not secret_exits:
            return True

        skill = self.demo_info.get('skill')
        game_mode = self.demo_info.get('game_mode')
        secret_maps = []
        for secret_exit, secret_map in secret_exits.items():
            if secret_exit in map_list:
                if category in PlaybackData.ALL_SECRETS_CATEGORIES:
                    secret_maps.append(secret_map)
                else:
                    # Categories that do not require secrets do not need to visit nomonster maps.
                    map_info = wad.map_list_info.get_map_info(secret_map)
                    if not map_info.get_single_key_for_map('nomo_map', skill=skill,
                                                           game_mode=game_mode):
                        secret_maps.append(secret_map)

        for secret_map in secret_maps:
            if secret_map not in map_list:
                return False

        return True

    @staticmethod
    def _convert_level_to_dsda_format(level_str):
        """Convert level text from levelstat format to DSDA format.

        :param level_str: Level string from levelstat
        :return: Level string in DSDA format
        """
        # Doom 2/Final Doom case (MAP##)
        if 'MAP' in level_str:
            return level_str.replace('MAP', 'Map ')

        # Doom 1/Heretic/Hexen case (E#M#)
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


@dataclass
class DemoPlayback:
    """DemoPlayback data class."""
    wad: Wad
    cmd: str
    levelstat: str
    analysis: str
    levelstat_line_count: int = field(init=False)

    cmd_line_info: dict = field(default_factory=dict)

    def __post_init__(self):
        """Post-initialization steps for DemoPlayback class."""
        self.levelstat_line_count = len(self.levelstat.splitlines())

    def __lt__(self, other):
        """Less than overload for DemoPlayback.

        Based on levelstat line count (i.e., number of maps completed)

        :param other: Other DemoPlayback
        :return: Whether this DemoPlayback is less than the other
        """
        return self.levelstat_line_count < other.levelstat_line_count

    def __le__(self, other):
        """Less than or equal to overload for DemoPlayback.

        Based on levelstat line count (i.e., number of maps completed)

        :param other: Other DemoPlayback
        :return: Whether this DemoPlayback is less than or equal to the other
        """
        return self.levelstat_line_count <= other.levelstat_line_count

    def __gt__(self, other):
        """Greater than overload for DemoPlayback.

        Based on levelstat line count (i.e., number of maps completed)

        :param other: Other DemoPlayback
        :return: Whether this DemoPlayback is greater than the other
        """
        return self.levelstat_line_count > other.levelstat_line_count

    def __ge__(self, other):
        """Greater than or equal to overload for DemoPlayback.

        Based on levelstat line count (i.e., number of maps completed)

        :param other: Other DemoPlayback
        :return: Whether this DemoPlayback is greater than or equal to the other
        """
        return self.levelstat_line_count >= other.levelstat_line_count

    def __eq__(self, other):
        """Equal to overload for DemoPlayback.

        Based on levelstat line count (i.e., number of maps completed)

        :param other: Other DemoPlayback
        :return: Whether this DemoPlayback is equal to the other
        """
        return self.levelstat_line_count == other.levelstat_line_count

    def __ne__(self, other):
        """Not equal to overload for DemoPlayback.

        Based on levelstat line count (i.e., number of maps completed)

        :param other: Other DemoPlayback
        :return: Whether this DemoPlayback is not equal to the other
        """
        return self.levelstat_line_count != other.levelstat_line_count
