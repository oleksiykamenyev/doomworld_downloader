"""
WAD object with supported data values mirroring what is available in the DSDA WAD config.
"""

import logging

from dataclasses import dataclass, field

from .utils import get_single_key_value_dict


LOGGER = logging.getLogger(__name__)


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
    map_list_info: dict
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
    alt_playback_cmd_lines: dict = field(default_factory=dict)
    # DSDA name of the WAD, in cases where the URL doesn't match it
    dsda_name: str = None


class WadMapListInfo:
    """WAD map list info object handler."""
    GAME_MODE_OPTIONS = ['single_player', 'coop']
    SKILL_OPTIONS = ['easy', 'medium', 'hard']
    TOP_LEVEL_KEYS = ['complevel', 'd1all', 'd2all', 'episodes', 'map_info', 'map_ranges',
                      'secret_exits']
    IWAD_TO_SECRET_EXIT_MAP = {
        'doom': {'E1M3': 'E1M9', 'E2M5': 'E2M9', 'E3M6': 'E3M9', 'E4M2': 'E4M9'},
        'doom2': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'plutonia': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'tnt': {'Map 15': 'Map 31', 'Map 31': 'Map 32'},
        'heretic': {'E1M6': 'E1M9', 'E2M4': 'E2M9', 'E3M4': 'E3M9', 'E4M4': 'E4M9', 'E5M3': 'E5M9'},
        # TODO: Handle Hexen
        'hexen': {},
        'chex': {}
    }
    D2ALL_DEFAULT = ['Map 01', 'Map 30']
    EPISODE_DEFAULTS = {
        'doom': [['E1M1', 'E1M8'], ['E2M1', 'E2M8'], ['E3M1', 'E3M8'], ['E4M1', 'E4M8']],
        'doom2': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        'plutonia': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        'tnt': [['Map 01', 'Map 10'], ['Map 11', 'Map 20'], ['Map 21', 'Map 30']],
        # One less map for episode 6 since E6M1 won't appear in the levelstat due to having no exit
        # TODO: Need to update DSDA-Doom to optionally force-levelstat for maps with no exit
        'heretic': [['E1M1', 'E1M8'], ['E2M1', 'E2M8'], ['E3M1', 'E3M8'], ['E4M1', 'E4M8'],
                    ['E5M1', 'E5M8'], ['E6M1', 'E6M2']],
        # TODO: Handle Hexen
        'hexen': [[]],
        'chex': [['E1M1', 'E1M5']]
    }

    def __init__(self, map_list_info_dict, wad_name, skip_validation=False):
        """Initialize WAD list map info object.

        :param map_list_info_dict: WAD map list info dictionary
        :param wad_name: WAD name for error logging purposes
        :param skip_validation: Flag indicating whether to skip validation of WAD map info object
        """
        self.map_list_info_dict = map_list_info_dict
        self.wad_name = wad_name
        parsed_map_infos = [WadMapInfo(map_info, wad_name, skip_validation=skip_validation)
                            for map_info in map_list_info_dict.get('map_info', {})]
        self.map_info = {wad_map_info.map: wad_map_info for wad_map_info in parsed_map_infos}
        if not skip_validation:
            self._validate()

    def _validate(self):
        """Validate WadMapListInfo object.

        :raises ValueError if unrecognized keys are found in the dictionary.
        """
        for key, value in self.map_list_info_dict.items():
            if key not in WadMapListInfo.TOP_LEVEL_KEYS:
                raise ValueError(f'Unexpected key found for WAD {self.wad_name}.')

    def get_key(self, key):
        
        return self.map_list_info_dict.get(key)

    def has_key(self, key):
        return key in self.map_list_info_dict

    def get_map_info(self, level):
        """Get WadMapInfo for provided level, if available.

        :param level: Level to get WadMapInfo for
        :return: WadMapInfo for provided level
        """
        return self.map_info.get(level)


class WadMapInfo:
    """WAD map info object handler."""
    GAME_MODE_OPTIONS = ['single_player', 'coop']
    SKILL_OPTIONS = ['easy', 'medium', 'hard']

    # TODO: Implement:
    #         add_almost_reality_in_nomo
    #         allowed_missed_monsters
    #         allowed_missed_secrets
    #         mark_secret_exit_as_normal
    #         no_exit
    #         skip_almost_reality
    #         tyson_only
    VALID_KEYS = {
        'add_almost_reality_in_nomo': False, 'add_reality_in_nomo': False,
        'allowed_missed_monsters': [], 'allowed_missed_secrets': [],
        'mark_secret_exit_as_normal': False, 'no_exit': False, 'nomo_map': False,
        'skip_almost_reality': False, 'skip_reality': False, 'tyson_only': False
    }

    def __init__(self, map_info_dict, wad_name, skip_validation=False):
        """Initialize WAD map info object.

        :param map_info_dict: WAD map info dictionary
        :param wad_name: WAD name for error logging purposes
        :param skip_validation: Flag indicating whether to skip validation of WAD map info object
        """
        self.map, self.map_info_dict = get_single_key_value_dict(map_info_dict)
        self.wad_name = wad_name
        if not skip_validation:
            self._validate()

    def _validate(self):
        """Validate WadMapInfo object.

        :raises ValueError both a skill and game mod element is defined at the top level.
        """
        found_game_mode = False
        found_skill = False
        for top_level_key, top_level_value in self.map_info_dict.items():
            if top_level_key in WadMapListInfo.GAME_MODE_OPTIONS:
                found_game_mode = True
                for game_key, game_value in top_level_value.items():
                    if game_key in WadMapListInfo.SKILL_OPTIONS:
                        for key in game_value:
                            self._validate_other_key(key)
                    else:
                        self._validate_other_key(game_key)
            elif top_level_key in WadMapListInfo.SKILL_OPTIONS:
                found_skill = True
                for skill_key, skill_key in top_level_value.items():
                    if skill_key in WadMapListInfo.GAME_MODE_OPTIONS:
                        for key in skill_key:
                            self._validate_other_key(key)
                    else:
                        self._validate_other_key(skill_key)
            else:
                self._validate_other_key(top_level_key)

        if found_game_mode and found_skill:
            LOGGER.error('Game mode and skill must be at separate hierarchies for a single map '
                         'info object.')
            raise ValueError(f'Issue parsing map info for WAD {self.wad_name}.')

    def _validate_other_key(self, key):
        """Validate any key other than the skill/game_mode keys.

        :param key: Key to validate
        :raises ValueError if the key is invalid
        """
        if key not in WadMapInfo.VALID_KEYS:
            raise ValueError(f'Unrecognized option {key} provided for WAD {self.wad_name}.')

    def get_single_key_for_map(self, key, skill=None, game_mode=None):
        """Get value of single key for the map info object.

        If skill and/or game_mode are provided, it will return the value for those arguments, else
        the default values excluding those arguments, else whatever is default for the current key.

        :param key: Key to get
        :param skill: Skill level (accepted options: easy, medium, hard)
        :param game_mode: Game mode (accepted options: single_player, coop)
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
        # deepest place it is defined as a non-null value within the hiearachy, else use whatever
        # the default value is for it. Both skill and game_mode may be defined at the top of the
        # hierarchy, and if either is at the top, the other one must be below it.
        if skill in self.map_info_dict:
            value_preferences = [self.map_info_dict.get(skill).get(game_mode, {}).get(key),
                                 self.map_info_dict.get(skill).get(key)]
        else:
            value_preferences = [self.map_info_dict.get(game_mode).get(skill, {}).get(key),
                                 self.map_info_dict.get(game_mode).get(key)]

        value_preferences.append(self.map_info_dict.get(key))
        for possible_value in value_preferences:
            if possible_value is not None:
                return possible_value

        return self.VALID_KEYS[key]
