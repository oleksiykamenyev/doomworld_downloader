"""
Upload configuration class.
"""

from configparser import ConfigParser, NoSectionError, NoOptionError

import yaml

from .utils import parse_list_file
from .wad import Wad


DEFAULT_UPLOAD_CONFIG_PATH = 'doomworld_downloader/upload.ini'
IGNORE_LIST_PATH = 'doomworld_downloader/player_ignore_list.txt'
THREAD_MAP_PATH = 'doomworld_downloader/thread_map.yaml'
WAD_MAP_PATH = 'doomworld_downloader/dsda_url_to_wad_info.yaml'

NEEDS_ATTENTION_PLACEHOLDER = 'UNKNOWN'

PLAYER_IGNORE_LIST = []
THREAD_MAP = {}
THREAD_MAP_KEYED_ON_ID = {}
WAD_MAP_BY_DSDA_URL = {}
WAD_MAP_BY_IDGAMES_URL = {}


class UploadConfig:
    """Config class to manage all configurations pulled from the upload.ini file."""
    def __init__(self):
        """Initialize upload config class."""
        self._config = ConfigParser()

    def parse_config_file(self, upload_config_path=None):
        """Parse config file.

        Parses provided path if available, else uses default path.

        :param upload_config_path: Upload config path
        """
        upload_config_path = (upload_config_path if upload_config_path
                              else DEFAULT_UPLOAD_CONFIG_PATH)
        self._config.read(upload_config_path)

    @property
    def search_start_date(self):
        """Get search start date from config (required).

        :return: Search start date
        """
        return self._config.get('general', 'search_start_date')

    @property
    def search_end_date(self):
        """Get search end date from config (required).

        :return: Search end date
        """
        return self._config.get('general', 'search_end_date')

    @property
    def dsda_doom_directory(self):
        """Get DSDA-Doom directory from config (required).

        :return: DSDA-Doom directory
        """
        return self._config.get('general', 'dsda_doom_directory')

    @property
    def parse_lmp_directory(self):
        """Get parse LMP directory from config (required).

        :return: LMP parser directory
        """
        return self._config.get('general', 'parse_lmp_directory')

    @property
    def demo_download_directory(self):
        """Get demo download directory from config (optional).

        Default to ./demos_for_upload.

        :return: Demo download directory
        """
        try:
            return self._config.get('general', 'demo_download_directory')
        except (NoSectionError, NoOptionError):
            return 'demos_for_upload'

    @property
    def wad_download_directory(self):
        """Get WAD download directory from config (optional).

        Default to ./dsda_wads.

        :return: WAD download directory
        """
        try:
            return self._config.get('general', 'wad_download_directory')
        except (NoSectionError, NoOptionError):
            return 'dsda_wads'

    @property
    def testing_mode(self):
        """Get flag indicating testing mode from config (optional).

        Default to False.

        :return: Flag indicating testing mode
        """
        try:
            return self._config.getboolean('general', 'testing_mode')
        except (NoSectionError, NoOptionError):
            return False


CONFIG = UploadConfig()


def set_up_configs(upload_config_path=None):
    """Set up config classes for uploads.

    :param upload_config_path: Upload config path
    """
    # TODO:
    #   The config files (thread map, upload.ini, etc.) should eventually be moved to be managed by
    #   pkg_resources instead of relative paths
    CONFIG.parse_config_file(upload_config_path=upload_config_path)

    with open(THREAD_MAP_PATH, encoding='utf-8') as thread_map_stream:
        THREAD_MAP.update(yaml.safe_load(thread_map_stream))
    # TODO: I made the map keyed on URL, but depending on how we use it over time, might want to
    #       reformat the YAML to be keyed on ID
    for url, thread_dict in THREAD_MAP.items():
        THREAD_MAP_KEYED_ON_ID[thread_dict['id']] = {key: value
                                                     for key, value in thread_dict.items()}
        THREAD_MAP_KEYED_ON_ID['url'] = url

    PLAYER_IGNORE_LIST.extend(parse_list_file(IGNORE_LIST_PATH))

    with open(WAD_MAP_PATH, encoding='utf-8') as wad_stream:
        wad_map_by_dsda_url_raw = yaml.safe_load(wad_stream)

    for url, wad_dict in wad_map_by_dsda_url_raw.items():
        idgames_url = wad_dict['idgames_url']
        wad_info = Wad(
            name=wad_dict['wad_name'], iwad=wad_dict['iwad'], files=wad_dict['wad_files'],
            complevel=wad_dict['complevel'], map_info=wad_dict['map_info'],
            idgames_url=idgames_url, dsda_url=url, other_url='',
            dsda_paginated=wad_dict['dsda_paginated'],
            doomworld_thread=wad_dict['doomworld_thread'],
            playback_cmd_line=wad_dict.get('playback_cmd_line', ''),
            dsda_name=wad_dict.get('dsda_name')
        )
        WAD_MAP_BY_DSDA_URL[url] = wad_info
        WAD_MAP_BY_IDGAMES_URL[wad_dict['idgames_url']] = wad_info
