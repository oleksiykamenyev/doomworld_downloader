"""
Upload configuration class.
"""

from configparser import ConfigParser, NoSectionError, NoOptionError

from collections import defaultdict

import yaml

from .utils import parse_list_file
from .wad import Wad, WadMapListInfo


AD_HOC_UPLOAD_CONFIG_PATH = 'doomworld_downloader/ad_hoc_upload_config.yaml'
DEFAULT_UPLOAD_CONFIG_PATH = 'doomworld_downloader/upload.ini'
IGNORE_LIST_PATH = 'doomworld_downloader/player_ignore_list.txt'
THREAD_MAP_PATH = 'doomworld_downloader/thread_map.yaml'
WAD_MAP_PATH = 'doomworld_downloader/dsda_url_to_wad_info.yaml'

NEEDS_ATTENTION_PLACEHOLDER = 'UNKNOWN'

AD_HOC_UPLOAD_CONFIG = {}
PLAYER_IGNORE_LIST = []
THREAD_MAP = {}
THREAD_MAP_KEYED_ON_ID = {}
WAD_MAP_BY_DSDA_URL = {}
WAD_MAP_BY_IDGAMES_URL = {}

DEMO_PACK_ADDITIONAL_INFO_MAP = defaultdict(list)
DEMO_PACK_USER_MAP = {}


class UploadConfig:
    """Config class to manage all configurations pulled from the upload.ini file."""
    def __init__(self):
        """Initialize upload config class."""
        self._config = ConfigParser()
        self._config.read(DEFAULT_UPLOAD_CONFIG_PATH)

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
    def dsda_api_directory(self):
        """Get DSDA API directory (required).

        :return: DSDA API directory
        """
        try:
            return self._config.get('general', 'dsda_api_directory')
        except (NoSectionError, NoOptionError):
            return None

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
    def download_type(self):
        """Get download type from config (optional).

        Default to date-based.

        :return: Download type
        """
        try:
            return self._config.get('general', 'download_type')
        except (NoSectionError, NoOptionError):
            return 'date-based'

    @property
    def ignore_cache(self):
        """Ignore cache when doing the uploads (optional).

        Default to false, should only be on while testing.

        :return: Flag indicating whether to ignore cache when doing the uploads
        """
        try:
            return self._config.getboolean('general', 'ignore_cache')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def skip_playback(self):
        """Skip playback when doing the uploads (optional).

        Default to false, this will result in potentially incomplete JSONs output by the script,
        which will require manual processing.

        :return: Flag indicating whether to skip playback when doing the uploads
        """
        try:
            return self._config.getboolean('general', 'skip_playback')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def skip_demo_pack_issues(self):
        """Skip demos with issues in demo packs (optional).

        Default to false, this will result in faulty demos within the demo pack being ignored.

        :return: Flag indicating whether to skip demos with issues in demo packs
        """
        try:
            return self._config.getboolean('general', 'skip_demo_pack_issues')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def demo_date_cutoff(self):
        """Cutoff date for demo recorded_at info (optional).

        If demos have dates older than this date, the date will be treated as incorrect. Default to
        the 1994-01-01, i.e. around the time the first demos are expected to appear.

        :return: Cutoff date for demo recorded_at info
        """
        try:
            return self._config.get('general', 'demo_date_cutoff')
        except (NoSectionError, NoOptionError):
            return '1994-01-01T00:00:00Z'

    @property
    def always_try_solonet(self):
        """Always try to play demos back with -solo-net (optional).

        Default to false.

        :return: Flag indicating whether to always try to play demos back with -solo-net
        """
        try:
            return self._config.getboolean('general', 'always_try_solonet')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def demo_pack_input_folder(self):
        """Get demo pack input folder.

        Required for demo packs.

        :return: Demo pack input folder
        """
        try:
            return self._config.get('demo_pack', 'input_folder')
        except (NoSectionError, NoOptionError):
            return None

    @property
    def demo_pack_output_folder(self):
        """Get demo pack output folder.

        Required for demo packs.

        :return: Demo pack output folder
        """
        try:
            return self._config.get('demo_pack', 'output_folder')
        except (NoSectionError, NoOptionError):
            return None

    @property
    def demo_pack_user_map(self):
        """Get demo pack user map.

        Optional for demo packs. Maps username from folder to player name for final JSON to upload
        to DSDA.

        :return: Demo pack output folder
        """
        try:
            return self._config.get('demo_pack', 'user_map')
        except (NoSectionError, NoOptionError):
            return None

    @property
    def demo_pack_additional_info_map(self):
        """Get demo pack output folder.

        Optional for demo packs. Maps username from folder to player name for final JSON to upload
        to DSDA.

        :return: Demo pack output folder
        """
        try:
            return self._config.get('demo_pack', 'additional_info_map')
        except (NoSectionError, NoOptionError):
            return None

    @property
    def dsda_mode_page(self):
        """Get DSDA page to check demos for.

        :return: DSDA page to check demos for
        """
        try:
            return self._config.get('dsda_mode', 'page')
        except (NoSectionError, NoOptionError):
            return None

    @property
    def dsda_mode_download_directory(self):
        """Get download directory for DSDA mode demos.

        Default to ./dsda_demos.

        :return: Download directory for DSDA mode demos.
        """
        try:
            return self._config.get('demo_pack', 'download_directory')
        except (NoSectionError, NoOptionError):
            return 'dsda_demos'

    @property
    def dsda_mode_sync_only(self):
        """Check only whether demos sync on page.

        Alternative WADs for sync testing may be provided.

        :return: Flag indicating whether to check only whether demos sync
        """
        try:
            return self._config.get('demo_pack', 'sync_only')
        except (NoSectionError, NoOptionError):
            return None


CONFIG = UploadConfig()


def set_up_configs(upload_config_path=None):
    """Set up config classes for uploads.

    :param upload_config_path: Upload config path
    """
    # TODO:
    #   The config files (thread map, upload.ini, etc.) should eventually be moved to be managed by
    #   pkg_resources instead of relative paths
    with open(THREAD_MAP_PATH, encoding='utf-8') as thread_map_stream:
        THREAD_MAP.update(yaml.safe_load(thread_map_stream))
    # TODO: I made the map keyed on URL, but depending on how we use it over time, might want to
    #       reformat the YAML to be keyed on ID
    for url, thread_dict in THREAD_MAP.items():
        THREAD_MAP_KEYED_ON_ID[thread_dict['id']] = {key: value
                                                     for key, value in thread_dict.items()}
        THREAD_MAP_KEYED_ON_ID['url'] = url

    PLAYER_IGNORE_LIST.extend([int(player_id) for player_id in parse_list_file(IGNORE_LIST_PATH)])

    with open(WAD_MAP_PATH, encoding='utf-8') as wad_stream:
        wad_map_by_dsda_url_raw = yaml.safe_load(wad_stream)

    if CONFIG.demo_pack_additional_info_map:
        with open(CONFIG.demo_pack_additional_info_map, encoding='utf-8') as info_map_stream:
            demo_pack_additional_info_raw = yaml.safe_load(info_map_stream)

        for attach_info in demo_pack_additional_info_raw['attachments']:
            DEMO_PACK_ADDITIONAL_INFO_MAP[attach_info['author']].append(attach_info)
    if CONFIG.demo_pack_user_map:
        with open(CONFIG.demo_pack_user_map, encoding='utf-8') as user_map_stream:
            DEMO_PACK_USER_MAP.update(yaml.safe_load(user_map_stream))

    for url, wad_dict in wad_map_by_dsda_url_raw.items():
        idgames_url = wad_dict['idgames_url']
        wad_name = wad_dict['wad_name']
        iwad = wad_dict['iwad']
        map_list_info = WadMapListInfo(wad_dict['map_list_info'], wad_name, iwad,
                                       fail_on_error=True)
        wad_info = Wad(
            name=wad_name, iwad=iwad, files=wad_dict['wad_files'], complevel=wad_dict['complevel'],
            map_list_info=map_list_info, idgames_url=idgames_url, dsda_url=url, other_url='',
            dsda_paginated=wad_dict['dsda_paginated'],
            doomworld_thread=wad_dict['doomworld_thread'],
            playback_cmd_line=wad_dict.get('playback_cmd_line', ''),
            alt_playback_cmd_lines=wad_dict.get('alt_playback_cmd_lines', {}),
            dsda_name=wad_dict.get('dsda_name'), commercial=wad_dict.get('commercial', False),
            parent=wad_dict.get('parent')
        )
        WAD_MAP_BY_DSDA_URL[url] = wad_info
        WAD_MAP_BY_IDGAMES_URL[wad_dict['idgames_url']] = wad_info


def set_up_ad_hoc_config():
    """Set up ad-hoc upload config."""
    with open(AD_HOC_UPLOAD_CONFIG_PATH, encoding='utf-8') as ad_hoc_config_stream:
        AD_HOC_UPLOAD_CONFIG.update(yaml.safe_load(ad_hoc_config_stream))
