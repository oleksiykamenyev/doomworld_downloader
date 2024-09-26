"""
WAD object with supported data values mirroring what is available in the DSDA WAD config.
"""

import logging

from dataclasses import dataclass, field


LOGGER = logging.getLogger(__name__)


class WadMapInfo:
    """WAD map info object handler."""
    GAME_MODE_OPTIONS = ['single_player', 'coop']
    SKILL_OPTIONS = ['easy', 'medium', 'hard']

    VALID_KEYS = {
        'add_almost_reality_in_nomo': False, 'add_reality_in_nomo': False,
        'allowed_missed_monsters': [], 'allowed_missed_secrets': [],
        'mark_secret_exit_as_normal': False, 'no_exit': False, 'nomo_map': False,
        'skip_almost_reality': False, 'skip_reality': False, 'tyson_only': False,
        'skip_reality_for_categories': None, 'skip_almost_reality_for_categories': None,
        'skip_also_pacifist': False, 'skip_also_pacifist_for_categories': None
    }

    def __init__(self, map_name, map_info_dict, wad_name, fail_on_error=False):
        """Initialize WAD map info object.

        :param map_info_dict: WAD map info dictionary
        :param wad_name: WAD name for error logging purposes
        :param fail_on_error: Flag indicating whether to fail on error when parsing map info
        """
        self.map = map_name
        self.map_info_dict = map_info_dict
        self.wad_name = wad_name
        self._fail_on_error = fail_on_error
        self._validate()

    def _validate(self):
        """Validate WadMapInfo object.

        :raises ValueError both a skill and game mod element is defined at the top level.
        """
        found_game_mode = False
        found_skill = False
        pass_validation = True
        for top_level_key, top_level_value in self.map_info_dict.items():
            if top_level_key in WadMapInfo.GAME_MODE_OPTIONS:
                found_game_mode = True
                for game_key, game_value in top_level_value.items():
                    if game_key in WadMapInfo.SKILL_OPTIONS:
                        for key in game_value:
                            pass_validation = pass_validation and self._validate_other_key(key)
                    else:
                        pass_validation = pass_validation and self._validate_other_key(game_key)
            elif top_level_key in WadMapInfo.SKILL_OPTIONS:
                found_skill = True
                for skill_key, skill_key in top_level_value.items():
                    if skill_key in WadMapInfo.GAME_MODE_OPTIONS:
                        for key in skill_key:
                            pass_validation = pass_validation and self._validate_other_key(key)
                    else:
                        pass_validation = pass_validation and self._validate_other_key(skill_key)
            else:
                pass_validation = pass_validation and self._validate_other_key(top_level_key)

        # If both game mode and skill elements are found at the top level of a WAD map info config,
        # we fail the validation
        if found_game_mode and found_skill:
            LOGGER.error('Game mode and skill must be at separate hierarchies for a single map '
                         'info object.')
            pass_validation = False

        if not pass_validation and self._fail_on_error:
            raise ValueError(
                f'Error parsing WAD map info for map {self.map} of WAD "{self.wad_name}".'
            )

    def _validate_other_key(self, key):
        """Validate any key other than the skill/game_mode keys.

        :param key: Key to validate
        :return: True if validation succeeded, false otherwise
        """
        if key not in WadMapInfo.VALID_KEYS:
            LOGGER.error('Unrecognized option %s provided for map %s of WAD "%s".', key, self.map,
                         self.wad_name)
            return False

        return True

    def get_single_key_for_map(self, key, skill=None, game_mode=None, use_builtin_defaults=True):
        """Get value of single key for the map info object.

        If skill and/or game_mode are provided, it will return the value for those arguments, else
        the default values excluding those arguments, else whatever is default for the current key.

        :param key: Key to get
        :param skill: Skill level (accepted options: easy, medium, hard)
        :param game_mode: Game mode (accepted options: single_player, coop)
        :param use_builtin_defaults: Flag indicating to use built-in defaults for keys that support
                                     default values
        :return: Value for requested key
        :raises ValueError if invalid key, skill, or game_mode are passed in
        """
        if key not in WadMapInfo.VALID_KEYS:
            raise ValueError(f'Invalid key {key} requested for wad {self.wad_name}.')

        if skill and skill not in WadMapInfo.SKILL_OPTIONS:
            raise ValueError(f'Invalid skill {skill} requested for wad {self.wad_name}.')
        if game_mode and game_mode not in WadMapInfo.GAME_MODE_OPTIONS:
            raise ValueError(f'Invalid game mode {game_mode} requested for wad {self.wad_name}.')

        # Each key may be specified under any level of the hierarchy; we will want to take the
        # deepest place it is defined as a non-null value within the hierarchy, else use whatever
        # the default value is for it. Both skill and game_mode may be defined at the top of the
        # hierarchy, and if either is at the top, the other one must be below it.
        if skill in self.map_info_dict:
            value_preferences = [self.map_info_dict.get(skill).get(game_mode, {}).get(key),
                                 self.map_info_dict.get(skill).get(key)]
        elif game_mode in self.map_info_dict:
            value_preferences = [self.map_info_dict.get(game_mode).get(skill, {}).get(key),
                                 self.map_info_dict.get(game_mode).get(key)]
        else:
            value_preferences = []

        value_preferences.append(self.map_info_dict.get(key))
        for possible_value in value_preferences:
            if possible_value is not None:
                return possible_value

        if use_builtin_defaults:
            return self.VALID_KEYS[key]

        return None


class WadMapListInfo:
    """WAD map list info object handler."""
    TOP_LEVEL_KEYS = ['complevel', 'd1all', 'd2all', 'episodes', 'map_info', 'map_ranges',
                      'secret_exits']

    D2ALL_DEFAULT = ['Map 01', 'Map 30']
    D2ALL_IWADS = ['doom2', 'plutonia', 'tnt']
    EPISODE_DEFAULTS = {
        'doom': [['E1M1', 'E1M8'], ['E2M1', 'E2M8'], ['E3M1', 'E3M8'], ['E4M1', 'E4M8']],
        'doom2': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        'plutonia': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        'tnt': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        # One less map for episode 6 since E6M1 won't appear in the levelstat due to having no exit
        'heretic': [['E1M1', 'E1M8'], ['E2M1', 'E2M8'], ['E3M1', 'E3M8'], ['E4M1', 'E4M8'],
                    ['E5M1', 'E5M8'], ['E6M1', 'E6M2']],
        # TODO: Handle Hexen
        'hexen': [[]],
        'chex': [['E1M1', 'E1M5']]
    }
    SECRET_EXIT_DEFAULTS = {
        'doom': {'E1M3': 'E1M9', 'E2M5': 'E2M9', 'E3M6': 'E3M9', 'E4M2': 'E4M9'},
        'doom2': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'plutonia': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'tnt': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'heretic': {'E1M6': 'E1M9', 'E2M4': 'E2M9', 'E3M4': 'E3M9', 'E4M4': 'E4M9', 'E5M3': 'E5M9'},
        # TODO: Handle Hexen
        'hexen': {},
        'chex': {}
    }

    def __init__(self, map_list_info_dict, wad_name, iwad, fail_on_error=True):
        """Initialize WAD list map info object.

        :param map_list_info_dict: WAD map list info dictionary
        :param wad_name: WAD name for error logging purposes
        :param iwad: IWAD the WAD belongs to
        :param fail_on_error: Flag indicating whether to fail on error when parsing map list info
        """
        self.map_list_info_dict = map_list_info_dict
        self.wad_name = wad_name
        parsed_map_infos = [
            WadMapInfo(map_name, map_info, wad_name, fail_on_error=fail_on_error)
            for map_name, map_info in map_list_info_dict.get('map_info', {}).items()
        ]
        self.map_info = {wad_map_info.map: wad_map_info for wad_map_info in parsed_map_infos}
        self.iwad = iwad
        self._fail_on_error = fail_on_error
        self._validate()

    def _validate(self):
        """Validate WadMapListInfo object.

        :raises ValueError if unrecognized keys are found in the dictionary.
        """
        pass_validation = True
        for key, value in self.map_list_info_dict.items():
            if key not in WadMapListInfo.TOP_LEVEL_KEYS:
                LOGGER.error('Unexpected key %s found for WAD %s.', key, self.wad_name)
                pass_validation = False

        if not pass_validation and self._fail_on_error:
            raise ValueError(f'Error parsing WAD map list info for WAD "{self.wad_name}".')

    def get_key(self, key, use_builtin_defaults=True):
        """Get value for provided key.

        :param key: Key to get value for
        :param use_builtin_defaults: Flag indicating to use built-in defaults for keys that support
                                     default values
        :return: Value for provided key
        """
        # If we shouldn't use the built-in defaults or the key is set in the config (regardless of
        # whether it has a null/empty value), get the key from the config
        if not use_builtin_defaults or self.has_key(key):
            return self.map_list_info_dict.get(key)

        if key == 'd2all' and self.iwad in WadMapListInfo.D2ALL_IWADS:
            return self.D2ALL_DEFAULT
        if key == 'episodes':
            return WadMapListInfo.EPISODE_DEFAULTS.get(self.iwad)
        if key == 'secret_exits':
            return WadMapListInfo.SECRET_EXIT_DEFAULTS.get(self.iwad)

        return None

    def has_key(self, key):
        """Get flag indicating whether the provided key is set.

        :param key: Key
        :return: Flag indicating whether the provided key is set
        """
        return key in self.map_list_info_dict

    def get_map_info(self, level):
        """Get WadMapInfo for provided level, if available.

        By default, this returns an empty WAD map info object so the calls to the return value still
        work.

        :param level: Level to get WadMapInfo for
        :return: WadMapInfo for provided level
        """
        return self.map_info.get(
            level, WadMapInfo(level, {}, self.wad_name, fail_on_error=self._fail_on_error)
        )

    def keys(self):
        """Return all keys for the WAD map list info.

        :return: All keys for the WAD map list info
        """
        return self.map_list_info_dict.keys()


@dataclass
class Wad:
    """WAD data class."""
    # Name, mostly for logging (e.g., Scythe)
    name: str
    iwad: str
    # Files needed for the wad mapped to their MD5 hashes (e.g., scythe.wad: {hash})
    files: dict
    # Complevel needed for the wad (e.g., 2)
    complevel: int
    # Special info on the different maps in the wad; for example, whether any maps are nomo, etc.
    map_list_info: WadMapListInfo
    idgames_url: str
    dsda_url: str
    # If this wad isn't on idgames or DSDA, it may have some other URL to download it.
    other_url: str
    # Whether the DSDA page for this wad has multiple pages
    dsda_paginated: bool
    doomworld_thread: str

    # Playback command line for the wad (e.g., "-file scythe")
    playback_cmd_line: str = ''
    # Alternative command lines (e.g., for fixwad cases like "-file tnt tnt31")
    # This is a dict as each playback command line is mapped to an optional note to include in case
    # it is needed. If no note is needed, the cmd line option should be mapped to none.
    alt_playback_cmd_lines: list = field(default_factory=list)
    # DSDA name of the WAD, in cases where the URL doesn't match it
    dsda_name: str = None
    # Whether or not a WAD is commercial (AKA, whether it is possible to download from DSDA)
    commercial: bool = False
    # Parent WAD if it is applicable; if a WAD has a parent, its parent will be used to test syncing
    # before the WAD itself
    parent: str = None
