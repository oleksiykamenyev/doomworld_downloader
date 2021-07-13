"""
Upload configuration class.
"""
from configparser import ConfigParser, NoSectionError, NoOptionError

import yaml

from .utils import parse_list_file
from .wad import Wad


class UploadConfig:
    """Config class to manage all configurations pulled from the upload.ini file."""
    def __init__(self):
        """Initialize upload config class."""
        self._config = ConfigParser()
        # TODO: Consider making this configurable
        self._config.read('doomworld_downloader/upload.ini')

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

PLAYER_IGNORE_LIST = []
THREAD_MAP = {}
THREAD_MAP_KEYED_ON_ID = {}
WAD_MAP_BY_DSDA_URL = {}
WAD_MAP_BY_IDGAMES_URL = {}


def set_up_configs():
    """Set up config classes for uploads."""
    # TODO: Make the config locations global/conf variables?
    with open('doomworld_downloader/thread_map.yaml', encoding='utf-8') as thread_map_stream:
        THREAD_MAP.update(yaml.safe_load(thread_map_stream))
    # TODO: I made the map keyed on URL, but depending on how we use it over time, might want to
    #       reformat the YAML to be keyed on ID
    for url, thread_dict in THREAD_MAP.items():
        THREAD_MAP_KEYED_ON_ID[thread_dict['id']] = {key: value
                                                     for key, value in thread_dict.items()}
        THREAD_MAP_KEYED_ON_ID['url'] = url

    PLAYER_IGNORE_LIST.extend(parse_list_file('doomworld_downloader/player_ignore_list.txt'))

    with open('doomworld_downloader/dsda_url_to_wad_info.yaml', encoding='utf-8') as wad_stream:
        wad_map_by_dsda_url_raw = yaml.safe_load(wad_stream)

    # TODO: WAD files in the config should be expanded to have an option of specifying which are
    #       needed for playback and a full list of files; this will help with guessing WADs while
    #       not restricting every single WAD/file in a zip to be present in the DSDA-Doom directory
    for url, wad_dict in wad_map_by_dsda_url_raw.items():
        idgames_url = wad_dict['idgames_url']
        wad_info = Wad(
            name=wad_dict['wad_name'], iwad=wad_dict['iwad'], files=wad_dict['wad_files'],
            complevel=wad_dict['complevel'], playback_cmd_line=wad_dict['playback_cmd_line'],
            map_info=wad_dict['map_info'], idgames_url=idgames_url, dsda_url=url, other_url='',
            dsda_paginated=wad_dict['dsda_paginated'], doomworld_thread=wad_dict['doomworld_thread']
        )
        WAD_MAP_BY_DSDA_URL[url] = wad_info
        WAD_MAP_BY_IDGAMES_URL[wad_dict['idgames_url']] = wad_info
