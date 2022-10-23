"""
Validate all configs for Doomworld downloader.
"""

import argparse
import logging
import os
import re

from urllib.parse import urlparse

import yaml

from doomworld_downloader.upload_config import set_up_configs, set_up_ad_hoc_config, \
    AD_HOC_UPLOAD_CONFIG, PLAYER_IGNORE_LIST, THREAD_MAP, THREAD_MAP_PATH, WAD_MAP_PATH
from doomworld_downloader.utils import get_log_level
from doomworld_downloader.wad import WadMapListInfo, WadMapInfo


ALLOWED_AD_HOC_KEYS = ['posts', 'threads']
ALLOWED_AD_HOC_THREAD_KEYS = ['pages', 'posts']

ALLOWED_THREAD_MAP_KEYS = ['additional_info', 'id', 'name']
ALLOWED_THREAD_MAP_INFO_KEYS = [
    'wad', 'wads', 'solo-net', 'category', 'tas_only', 'note', 'source_port', 'ignore', 'nomonsters'
]
ALLOWED_THREAD_WAD_DUPES = ['https://www.dsdarchive.com/wads/equinox',
                            'https://www.dsdarchive.com/wads/chex',
                            'https://www.dsdarchive.com/wads/twzone',
                            'https://www.dsdarchive.com/wads/eternal',
                            'https://www.dsdarchive.com/wads/doom',
                            'https://www.dsdarchive.com/wads/doom2',
                            'https://www.dsdarchive.com/wads/plutonia',
                            'https://www.dsdarchive.com/wads/tnt',
                            'https://www.dsdarchive.com/wads/av',
                            'https://www.dsdarchive.com/wads/hr',
                            'https://www.dsdarchive.com/wads/mm',
                            'https://www.dsdarchive.com/wads/mm2',
                            'https://www.dsdarchive.com/wads/requiem',
                            'https://www.dsdarchive.com/wads/scythe']
THREAD_MAP_BOOLEAN_KEYS = ['tas_only', 'ignore', 'nomonsters']
THREAD_MAP_STR_KEYS = ['category', 'note', 'source_port']

ALLOWED_WAD_KEYS = [
    'wad_name', 'iwad', 'wad_files', 'complevel', 'playback_cmd_line', 'map_list_info',
    'idgames_url', 'dsda_paginated', 'doomworld_thread', 'alt_playback_cmd_lines', 'dsda_name',
    'commercial'
]
ALLOWED_WAD_FILE_KEYS = ['checksum', 'not_required_for_playback', 'dupe_checksum', 'shared_wad']
ALLOWED_CMD_LINE_ARGS = ['-file', '-deh']
REQURED_WAD_KEYS = [
    'wad_name', 'iwad', 'wad_files', 'complevel', 'map_list_info'
]
ALLOWED_MAP_INFO_BOOLEAN_KEYS = [
    'add_almost_reality_in_nomo', 'add_reality_in_nomo', 'mark_secret_exit_as_normal', 'no_exit',
    'nomo_map', 'skip_almost_reality', 'skip_reality', 'tyson_only'
]
ALLOWED_MAP_INFO_LIST_KEYS = ['allowed_missed_monsters', 'allowed_missed_secrets']
ALLOWED_IWADS = ['chex', 'doom', 'doom2', 'hacx', 'heretic', 'hexen', 'plutonia', 'tnt']

ALPHANUMERIC_LOWER_RE = re.compile(r'^[a-z0-9]+$')
DOOM1_MAP_RE = re.compile(r'^E\dM\d$')
DOOM2_MAP_RE = re.compile(r'^Map \d{2}$')
DSDA_WAD_RE = re.compile(r'^https://www.dsdarchive.com/wads/[a-z0-9_\-]+$')
IDGAMES_URL_RE = re.compile(r'^https://www.doomworld.com/idgames/[A-Za-z0-9_\-/.]+$')
THREAD_URL_RE = re.compile(r'^https://www.doomworld.com/forum/topic/[A-Za-z0-9_\-/%]+$')
YAML_TOP_KEY_RE = re.compile(r'^[^#\s]+')

FOUND_THREADS = set()
FOUND_THREAD_WADS = set()

FOUND_WADS = set()
FOUND_WAD_CHECKSUMS = set()

LOGGER = logging.getLogger(__name__)


def validate_dsda_wad_map():
    """Validate DSDA WAD map.

    :return: Flag indicating whether the validation passed
    """
    pass_validation = True

    with open(WAD_MAP_PATH, encoding='utf-8') as wad_map_stream:
        wad_map_lines = wad_map_stream.read().splitlines()
        wad_map_stream.seek(0)
        wad_map = yaml.safe_load(wad_map_stream)

    for line in wad_map_lines:
        if YAML_TOP_KEY_RE.match(line):
            wad = line.rstrip(':')
            if wad in FOUND_WADS:
                LOGGER.error('Duplicate WAD %s found in DSDA WAD map.', wad)
                pass_validation = False
            else:
                FOUND_WADS.add(wad)

    for wad, wad_dict in wad_map.items():
        if not isinstance(wad, str) or not DSDA_WAD_RE.match(wad):
            LOGGER.error('Invalid WAD %s found for DSDA WAD map.', wad)
            pass_validation = False

        for key in wad_dict:
            if key not in ALLOWED_WAD_KEYS:
                LOGGER.error('Unexpected key %s found in DSDA WAD %s config.', key, wad)
                pass_validation = False

        for key in REQURED_WAD_KEYS:
            if key not in wad_dict:
                LOGGER.error('Required key %s not found in DSDA WAD %s config.', key, wad)
                pass_validation = False

        iwad = wad_dict.get('iwad')
        if iwad is not None and iwad not in ALLOWED_IWADS:
            LOGGER.error('IWAD %s for WAD %s in DSDA WAD config is invalid.', iwad, wad)
            pass_validation = False

        idgames_url = wad_dict.get('idgames_url')
        if (idgames_url is not None and
                (not isinstance(idgames_url, str) or not IDGAMES_URL_RE.match(idgames_url))):
            LOGGER.error('Idgames URL %s for WAD %s in DSDA WAD config is invalid.', idgames_url,
                         wad)
            pass_validation = False

        doomworld_thread = wad_dict.get('doomworld_thread')
        if (doomworld_thread is not None and
                (not isinstance(doomworld_thread, str) or doomworld_thread not in THREAD_MAP)):
            LOGGER.error('Thread %s for WAD %s in DSDA WAD config is missing in thread map.',
                         doomworld_thread, wad)
            pass_validation = False

        wad_name = wad_dict.get('wad_name')
        if wad_name is not None and (not wad_name or not isinstance(wad_name, str)):
            LOGGER.error('WAD name %s for WAD %s in DSDA WAD config is invalid.', wad_name, wad)
            pass_validation = False
        dsda_name = wad_dict.get('dsda_name')
        if dsda_name is not None and (not dsda_name or not isinstance(dsda_name, str)):
            LOGGER.error('DSDA name %s for WAD %s in DSDA WAD config is invalid.', dsda_name, wad)
            pass_validation = False
        complevel = wad_dict.get('complevel')
        if complevel and not isinstance(complevel, int):
            LOGGER.error('Complevel %s for WAD %s in DSDA WAD config is invalid.', complevel, wad)
            pass_validation = False
        dsda_paginated = wad_dict.get('dsda_paginated')
        if dsda_paginated and not isinstance(dsda_paginated, bool):
            LOGGER.error('DSDA paginated flag %s for WAD %s in DSDA WAD config is invalid.',
                         dsda_paginated, wad)
            pass_validation = False

        wad_files = wad_dict.get('wad_files')
        wad_files_with_no_ext = []
        if isinstance(wad_files, dict):
            for wad_file, wad_file_dict in wad_files.items():
                wad_files_with_no_ext.append(os.path.splitext(os.path.basename(wad_file))[0])
                wad_files_with_no_ext.append(wad_file)
                if isinstance(wad_file_dict, dict):
                    for key in wad_file_dict:
                        if key not in ALLOWED_WAD_FILE_KEYS:
                            LOGGER.error(
                                'Unexpected key %s found for WAD file %s in DSDA WAD %s config.',
                                key, wad_file, wad
                            )
                            pass_validation = False
                    not_required_for_playback = wad_file_dict.get('not_required_for_playback')
                    if (not_required_for_playback and
                            not isinstance(not_required_for_playback, bool)):
                        LOGGER.error(
                            ('Not required for playback flag %s for WAD file %s in DSDA WAD %s '
                             'config is invalid.'), not_required_for_playback, wad_file, wad
                        )
                        pass_validation = False
                    dupe_checksum = wad_file_dict.get('dupe_checksum')
                    if dupe_checksum and not isinstance(dupe_checksum, bool):
                        LOGGER.error(
                            ('Dupe checksum flag %s for WAD file %s in DSDA WAD %s config is '
                             'invalid.'), dupe_checksum, wad_file, wad
                        )
                        pass_validation = False
                    shared_wad = wad_file_dict.get('shared_wad')
                    if shared_wad and not isinstance(shared_wad, bool):
                        LOGGER.error(
                            'Shared WAD flag %s for WAD file %s in DSDA WAD %s config is invalid.',
                            shared_wad, wad_file, wad
                        )
                        pass_validation = False

                    checksum = wad_file_dict.get('checksum')
                    if not ALPHANUMERIC_LOWER_RE.match(checksum):
                        LOGGER.error(
                            'Invalid checksum %s found for WAD file %s in DSDA WAD %s config.',
                                checksum, wad_file, wad
                        )
                        pass_validation = False
                    else:
                        if checksum in FOUND_WAD_CHECKSUMS and not dupe_checksum and not shared_wad:
                            LOGGER.error(
                                'Dupe checksum %s found for WAD file %s in DSDA WAD %s config.',
                                checksum, wad_file, wad
                            )
                            pass_validation = False
                        else:
                            FOUND_WAD_CHECKSUMS.add(checksum)
                else:
                    LOGGER.error(
                        'WAD file %s dict for WAD %s in DSDA WAD config must be a dictionary.',
                        wad_file, wad
                    )
                    pass_validation = False
        else:
            LOGGER.error('WAD files %s for WAD %s in DSDA WAD config must be a dictionary.',
                         wad_files, wad)
            pass_validation = False

        playback_cmd_line = wad_dict.get('playback_cmd_line')
        all_cmd_lines = []
        if playback_cmd_line:
            all_cmd_lines.append(playback_cmd_line)

        alt_playback_cmd_lines = wad_dict.get('alt_playback_cmd_lines')
        if alt_playback_cmd_lines:
            if isinstance(alt_playback_cmd_lines, dict):
                for cmd_line, note in alt_playback_cmd_lines.items():
                    all_cmd_lines.append(cmd_line)
                    if not note or not isinstance(note, str):
                        LOGGER.error(
                            'Cmd line note %s for WAD %s in DSDA WAD config must be a string.',
                            note, wad
                        )
                        pass_validation = False
            else:
                LOGGER.error(
                    'Alt playback cmd lines for WAD %s in DSDA WAD config must be a dictionary.',
                    alt_playback_cmd_lines, wad
                )
                pass_validation = False

        for cmd_line in all_cmd_lines:
            for arg in cmd_line.split():
                if (arg not in ALLOWED_CMD_LINE_ARGS and
                        os.path.basename(arg) not in wad_files_with_no_ext):
                    LOGGER.error(
                        'Invalid arg %s found for cmd line %s for WAD %s in DSDA WAD config.',
                        arg, cmd_line, wad
                    )
                    pass_validation = False

        map_list_info = WadMapListInfo(wad_dict.get('map_list_info'), wad_name,
                                       wad_dict.get('iwad'), fail_on_error=False)
        for key in map_list_info.keys():
            value = map_list_info.get_key(key, use_builtin_defaults=False)
            if key == 'complevel' and not isinstance(value, int):
                LOGGER.error('Complevel %s for WAD %s in DSDA WAD config must be an int.', value,
                             wad)
                pass_validation = False
            if key == 'd2all':
                if isinstance(value, list) and len(value) == 2:
                    for d2all_map in value:
                        if not isinstance(d2all_map, str) or not DOOM2_MAP_RE.match(d2all_map):
                            LOGGER.error(
                                'D2ALL %s for WAD %s in DSDA WAD config has invalid map %s.', value,
                                wad, d2all_map
                            )
                            pass_validation = False
                elif value is not None:
                    LOGGER.error(
                        'D2ALL %s for WAD %s in DSDA WAD config must be a list of two values.',
                        value, wad
                    )
                    pass_validation = False

            if key == 'episodes':
                if not isinstance(value, list):
                    LOGGER.error(
                        'Episodes list %s for WAD %s in DSDA WAD config must be a list.', value, wad
                    )
                    pass_validation = False
                else:
                    for episode_set in value:
                        if isinstance(episode_set, list) and len(episode_set) == 2:
                            for episode_map in episode_set:
                                if (not isinstance(episode_map, str) or
                                        (not DOOM1_MAP_RE.match(episode_map) and
                                         not DOOM2_MAP_RE.match(episode_map))):
                                    LOGGER.error(
                                        ('Episode %s for WAD %s in DSDA WAD config has invalid map '
                                         '%s.'), value, wad, episode_map
                                    )
                                    pass_validation = False
                        else:
                            LOGGER.error(
                                ('Episode %s for WAD %s in DSDA WAD config must be a list of two '
                                 'values.'), value, wad
                            )
                            pass_validation = False

            if key == 'map_ranges':
                if not isinstance(value, list):
                    LOGGER.error(
                        'Map ranges %s for WAD %s in DSDA WAD config must be a list.', value, wad
                    )
                    pass_validation = False
                else:
                    for map_range in value:
                        if isinstance(map_range, list) and len(map_range) in (1, 2):
                            for range_map in map_range:
                                if (isinstance(range_map, int) or
                                        (isinstance(range_map, str) and
                                         DOOM1_MAP_RE.match(range_map))):
                                    continue
                                LOGGER.error(
                                    ('Map range %s for WAD %s in DSDA WAD config has invalid '
                                     'map %s.'), value, wad, range_map
                                )
                                pass_validation = False
                        else:
                            LOGGER.error(
                                ('Episode %s for WAD %s in DSDA WAD config must be a list of two '
                                 'values.'), value, wad
                            )
                            pass_validation = False

            if key == 'secret_exits':
                if not isinstance(value, dict):
                    LOGGER.error(
                        'Secret exits %s for WAD %s in DSDA WAD config must be a dictionary.',
                        value, wad
                    )
                    pass_validation = False
                else:
                    for secret_exit_map, secret_map in value.items():
                        if isinstance(secret_exit_map, str) and isinstance(secret_map, str):
                            if (DOOM1_MAP_RE.match(secret_exit_map) and
                                    DOOM1_MAP_RE.match(secret_map)):
                                continue
                            if (DOOM2_MAP_RE.match(secret_exit_map) and
                                    DOOM2_MAP_RE.match(secret_map)):
                                continue

                        LOGGER.error(
                            ('Secret exits %s for WAD %s in DSDA WAD config contains invalid maps '
                             '%s and/or %s.'), value, wad, secret_exit_map, secret_map
                        )
                        pass_validation = False

        for map, map_info in map_list_info.map_info.items():
            for skill in WadMapInfo.SKILL_OPTIONS:
                for game_mode in WadMapInfo.GAME_MODE_OPTIONS:
                    for key in ALLOWED_MAP_INFO_BOOLEAN_KEYS:
                        value = map_info.get_single_key_for_map(
                            key, skill=skill, game_mode=game_mode, use_builtin_defaults=False
                        )
                        if value is not None and not isinstance(value, bool):
                            LOGGER.error(
                                ('Invalid value %s found for key %s for map info %s for WAD %s in '
                                 'DSDA WAD config.'), value, key, map_info.map, wad
                            )
                            pass_validation = False
                    for key in ALLOWED_MAP_INFO_LIST_KEYS:
                        value = map_info.get_single_key_for_map(
                            key, skill=skill, game_mode=game_mode, use_builtin_defaults=False
                        )
                        if value is not None and not isinstance(value, list):
                            LOGGER.error(
                                ('Invalid value %s found for key %s for map info %s for WAD %s in '
                                 'DSDA WAD config.'), value, key, map_info.map, wad
                            )
                            pass_validation = False

    return pass_validation


def validate_thread_map():
    """Validate thread map.

    :return: Flag indicating whether the validation passed
    """
    pass_validation = True

    with open(THREAD_MAP_PATH, encoding='utf-8') as thread_map_stream:
        thread_map_lines = thread_map_stream.read().splitlines()

    for line in thread_map_lines:
        if YAML_TOP_KEY_RE.match(line):
            thread = line.rstrip(':')
            if thread in FOUND_THREADS:
                LOGGER.error('Duplicate thread %s found in thread map.', thread)
                pass_validation = False
            else:
                FOUND_THREADS.add(thread)

    for thread, thread_dict in THREAD_MAP.items():
        for key in thread_dict:
            if key not in ALLOWED_THREAD_MAP_KEYS:
                LOGGER.error('Unexpected key %s found in thread config.', key)
                pass_validation = False

        if not isinstance(thread, str) or not THREAD_URL_RE.match(thread):
            LOGGER.error('Invalid thread %s found for in thread map.', thread)
            pass_validation = False

        thread_id = thread_dict.get('id')
        try:
            thread_id = int(thread_id)
        except (ValueError, TypeError):
            LOGGER.exception('Invalid thread ID %s found for thread %s.', thread_id, thread)
            pass_validation = False
            thread_id = None

        if thread_id:
            parsed_thread_id = int(thread.rstrip('/').split('/')[-1].split('-')[0])
            if thread_id != parsed_thread_id:
                LOGGER.error('Thread ID %s does not match thread URL %s.', thread_id, thread)
                pass_validation = False

        thread_name = thread_dict.get('name')
        if not thread_name or not isinstance(thread_name, str):
            LOGGER.error('Invalid thread name %s found for thread %s.', thread_name, thread)
            pass_validation = False

        additional_info = thread_dict.get('additional_info')
        if additional_info and not isinstance(additional_info, dict):
            LOGGER.error('Additional info must be a dictionary for thread %s.', thread)
            pass_validation = False
            additional_info = None
        if not additional_info:
            continue

        for key in additional_info:
            if key not in ALLOWED_THREAD_MAP_INFO_KEYS:
                LOGGER.error('Unexpected key %s found in thread %s additional info config.',
                             key, thread)
                pass_validation = False

        wad_value = additional_info.get('wad')
        wads_value = additional_info.get('wads')
        if wad_value and wads_value:
            LOGGER.error('Both wad and wads keys may not be provided for thread %s.', thread)
            pass_validation = False

        if wad_value or wads_value:
            if wad_value:
                wads = [wad_value]
            else:
                if isinstance(wads_value, list):
                    wads = wads_value
                else:
                    LOGGER.error('Invalid WADs setting %s found for thread %s.', wads_value, thread)
                    wads = []
                    pass_validation = False

            for wad in wads:
                if not isinstance(wad, str) or not DSDA_WAD_RE.match(wad):
                    LOGGER.error('Invalid WAD %s found for thread %s.', wad, thread)
                    pass_validation = False
                    continue
                if wad in FOUND_THREAD_WADS and wad not in ALLOWED_THREAD_WAD_DUPES:
                    LOGGER.error('WAD %s defined for multiple threads.', wad)
                    pass_validation = False
                    continue

                FOUND_THREAD_WADS.add(wad)

        for key in THREAD_MAP_BOOLEAN_KEYS:
            value = additional_info.get(key)
            if value and not isinstance(value, bool):
                LOGGER.error('Invalid value for key %s found for thread %s.', key, thread)
                pass_validation = False
        for key in THREAD_MAP_STR_KEYS:
            value = additional_info.get(key)
            if value and not isinstance(value, str):
                LOGGER.error('Invalid value for key %s found for thread %s.', key, thread)
                pass_validation = False

    return pass_validation


def validate_player_ignore_list():
    """Validate player ignore list.

    :return: Flag indicating whether the validation passed
    """
    pass_validation = True
    for player in PLAYER_IGNORE_LIST:
        try:
            int(player)
        except ValueError:
            LOGGER.exception('Found invalid player ID %s in ignore list.', player)
            pass_validation = False

    return pass_validation


def validate_ad_hoc_upload_config():
    """Validate ad-hoc upload config.

    :return: Flag indicating whether the validation passed
    """
    pass_validation = True

    for key in AD_HOC_UPLOAD_CONFIG:
        if key not in ALLOWED_AD_HOC_KEYS:
            LOGGER.error('Unexpected key %s found in ad-hoc config.', key)
            pass_validation = False

    post_list = AD_HOC_UPLOAD_CONFIG.get('posts')
    if post_list:
        if not isinstance(post_list, list):
            LOGGER.error('Ad-hoc post list %s is not a list.', post_list)
            pass_validation = False
        else:
            for post in post_list:
                try:
                    int(post)
                except (ValueError, TypeError):
                    try:
                        int(urlparse(post).path.strip('/').split('/')[-1])
                    except (ValueError, TypeError):
                        LOGGER.exception('Found invalid post %s in ad-hoc config.', post)
                        pass_validation = False

    thread_list = AD_HOC_UPLOAD_CONFIG.get('threads')
    if thread_list:
        if not isinstance(thread_list, list):
            LOGGER.error('Ad-hoc thread list %s is not a list.', thread_list)
            pass_validation = False
        else:
            for thread in thread_list:
                if isinstance(thread, dict):
                    # Just take the first element, since we expect this to be a single key/value
                    # dict
                    thread_base_url, thread_map = list(thread.items())[0]
                else:
                    thread_base_url = thread
                    thread_map = {}

                if not isinstance(thread_base_url, str):
                    LOGGER.error('Ad-hoc thread URL %s is not a string.', thread_base_url)
                    pass_validation = False

                for key in thread_map:
                    if key not in ALLOWED_AD_HOC_THREAD_KEYS:
                        LOGGER.error('Unexpected key %s found in ad-hoc thread %s config.', key,
                                     thread_base_url)
                        pass_validation = False

                pages_to_get = thread_map.get('pages')
                if not isinstance(pages_to_get, list):
                    LOGGER.error('Ad-hoc thread %s page list %s is not a list.', thread_base_url,
                                 pages_to_get)
                    pass_validation = False
                else:
                    for page in pages_to_get:
                        try:
                            int(page)
                        except (ValueError, TypeError):
                            LOGGER.exception('Found invalid page %s in ad-hoc thread %s config.',
                                             page, thread_base_url)
                            pass_validation = False

                post_list = thread_map.get('posts')
                if post_list:
                    if not isinstance(post_list, list):
                        LOGGER.error('Ad-hoc thread %s post list %s is not a list.',
                                     thread_base_url, post_list)
                        pass_validation = False
                    else:
                        for post in post_list:
                            try:
                                int(post)
                            except (ValueError, TypeError):
                                try:
                                    int(urlparse(post).path.strip('/').split('/')[-1])
                                except (ValueError, TypeError):
                                    LOGGER.exception(
                                        'Found invalid post %s in ad-hoc thread %s config.', post,
                                        thread_base_url
                                    )
                                    pass_validation = False

    return pass_validation


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Update WAD checksums.')

    parser.add_argument('-v', '--verbose',
                        action='count',
                        default=0,
                        help='Control verbosity of output.')

    return parser.parse_args()


def main():
    """Main function.

    :raises RuntimeError if any of the validations fail
    """
    args = parse_args()
    log_level = get_log_level(args.verbose)
    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')

    set_up_configs()
    set_up_ad_hoc_config()

    pass_validation = validate_ad_hoc_upload_config()
    pass_validation = pass_validation and validate_player_ignore_list()
    pass_validation = pass_validation and validate_thread_map()
    pass_validation = pass_validation and validate_dsda_wad_map()
    if not pass_validation:
        raise RuntimeError('Validation failed!')


if __name__ == '__main__':
    main()
