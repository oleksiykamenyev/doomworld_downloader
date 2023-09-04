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

MAYBE_CHEATED_DIR = 'maybe_cheated_jsons'
UPDATE_JSON_DIR = 'demos_for_upload/update_jsons'
VALID_DEMO_PACK_DIR = 'tmp_demo_pack_jsons'
VALID_ISSUE_DIR = 'issue_jsons'
VALID_NO_ISSUE_DIR = 'no_issue_jsons'
VALID_TAGS_DIR = 'tags_jsons'

FAILED_UPLOADS_FILE = 'failed_uploads.json'
FAILED_UPLOADS_LOG_DIR = 'failed_uploads_dir'

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
    def upload_type(self):
        """Get upload type from config (optional).

        Default to date-based.

        :return: Upload type
        """
        try:
            return self._config.get('general', 'upload_type')
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
        the 1994-01-01, i.e. around the time the first demos are expected to appear. For DSDA mode,
        it is possible to override this cutoff date separately.

        :return: Cutoff date for demo recorded_at info
        """
        try:
            if self.upload_type == 'dsda':
                return self._config.get('dsda_mode', 'demo_date_cutoff')
            else:
                return self._config.get('general', 'demo_date_cutoff')
        except (NoSectionError, NoOptionError):
            return '1994-01-01T00:00:00Z'

    @property
    def check_txt_date(self):
        """Check txt date (optional).

        If the lmp date looks wrong, this will check txt date as a fallback. Default to false.

        :return: Flag indicating whether to check txt date
        """
        try:
            return self._config.getboolean('general', 'check_txt_date')
        except (NoSectionError, NoOptionError):
            return False

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
    def add_lmp_metadata_for_demo_packs(self):
        """Add lmp metadata to demo pack JSONs

        LMP file will be stored to resulting JSON in extra lmp_metadata key. This may be useful for
        manual verification during either demo pack compilation or processing demo packs posted to
        Doomworld, but should not be turned on for the final upload (or cleaned before upload).

        :return: Flag indicating whether to add lmp metadata to demo pack JSONs
        """
        try:
            return self._config.getboolean('general', 'add_lmp_metadata')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def run_through_all_cmd_line_options(self):
        """Run through all command line options.

        This will run through all command line options on playback, even if it finds one that syncs.
        If multiple sync, it will choose the longest by map count as the "true" playback option. If
        the longest does not exist, it will choose at random.

        :return: Flag indicating run through all command line options
        """
        try:
            return self._config.getboolean('general', 'run_through_all_cmd_line_options')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def add_all_bonus_demos(self):
        """Add all bonus demos from a zip.

        The uploader has a default setting that it only tracks lmps named identically as the zip
        by default. If this flag is turned on, it will add other lmps as well.

        :return: Flag indicating whether to add all bonus demos from a zip
        """
        try:
            return self._config.getboolean('general', 'add_all_bonus_demos')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def exclude_demos_that_failed_playback(self):
        """Exclude demos that failed playback.

        In this mode, any demo that failed playback will be entirely excluded from the final output
        JSONs (normally, the script places a JSON anyway with any info it can gather about it
        without a successful playback).

        :return: Flag indicating whether to exclude demos that failed playback
        """
        try:
            return self._config.getboolean('general', 'exclude_demos_that_failed_playback')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def always_try_good_at_doom(self):
        """Always try to play back demos with good.deh.

        :return: Flag indicating whether to always try to play back demos with good.deh
        """
        try:
            return self._config.getboolean('general', 'always_try_good_at_doom')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def dedupe_demos(self):
        """Dedupe demos on upload.

        On by default to dedupe co-op demos.

        :return: Flag indicating whether to dedupe demos on upload
        """
        try:
            return self._config.getboolean('general', 'dedupe_demos')
        except (NoSectionError, NoOptionError):
            return True

    @property
    def additional_info_map(self):
        """Get additional info map when needed (e.g., for demo pack uploads).

        Optional for demo packs. Can override player info and recorded date for demos.

        :return: Additional info map
        """
        try:
            return self._config.get('general', 'additional_info_map')
        except (NoSectionError, NoOptionError):
            return None

    @property
    def trust_dsda_doom_category(self):
        """Trust DSDA-Doom category.

        Off by default to cross-check against the txt category.

        :return: Trust DSDA-Doom category
        """
        try:
            return self._config.getboolean('general', 'trust_dsda_doom_category')
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
    def demo_pack_name(self):
        """Get demo pack name.

        Required for demo packs. Appends zip for final upload.

        :return: Demo pack name
        """
        try:
            demo_pack_name = self._config.get('demo_pack', 'name')
            if not demo_pack_name.endswith('.zip'):
                demo_pack_name = f'{demo_pack_name}.zip'

            return demo_pack_name
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
            return self._config.get('dsda_mode', 'download_directory')
        except (NoSectionError, NoOptionError):
            return 'dsda_demos'

    @property
    def dsda_mode_sync_only(self):
        """Check only whether demos sync on page.

        Alternative WADs for sync testing may be provided.

        :return: Flag indicating whether to check only whether demos sync
        """
        try:
            return self._config.getboolean('dsda_mode', 'sync_only')
        except (NoSectionError, NoOptionError):
            return None

    @property
    def dsda_mode_replace_zips(self):
        """Replace zips mode.

        If set, this will look for all the zips in the replace_zips_dir location and generate delete
        JSONs for them on DSDA then create replacement upload JSONs.

        Only matching zip filenames will be tested, and only the replacement ones; the DSDA ones
        will be cross-verified based on the info available on DSDA but not run in this mode.

        :return: Flag indicating whether to use replace zips mode
        """
        try:
            return self._config.getboolean('dsda_mode', 'replace_zips')
        except (NoSectionError, NoOptionError):
            return None

    @property
    def dsda_mode_replace_zips_dir(self):
        """Replace zips directory.

        Default to ./replace_zips.

        :return: Flag indicating whether to use replace zips mode
        """
        try:
            return self._config.get('dsda_mode', 'replace_zips_dir')
        except (NoSectionError, NoOptionError):
            return 'replace_zips'

    @property
    def dsda_mode_mark_advanced_demos_incompatible(self):
        """Mark advanced port demos incompatible.

        Default to False.

        :return: Flag indicating whether to mark advanced demos incompatible
        """
        try:
            return self._config.getboolean('dsda_mode', 'mark_advanced_demos_incompatible')
        except (NoSectionError, NoOptionError):
            return False

    @property
    def dsda_mode_skip_unknowns(self):
        """Skip unknowns for updates in DSDA mode.

        Default to False.

        :return: Flag indicating whether to skip unknowns for updates in DSDA mode
        """
        try:
            return self._config.getboolean('dsda_mode', 'skip_unknowns')
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
            alt_playback_cmd_lines=wad_dict.get('alt_playback_cmd_lines', []),
            dsda_name=wad_dict.get('dsda_name'), commercial=wad_dict.get('commercial', False),
            parent=wad_dict.get('parent')
        )
        WAD_MAP_BY_DSDA_URL[url] = wad_info
        WAD_MAP_BY_IDGAMES_URL[wad_dict['idgames_url']] = wad_info


def set_up_ad_hoc_config():
    """Set up ad-hoc upload config."""
    with open(AD_HOC_UPLOAD_CONFIG_PATH, encoding='utf-8') as ad_hoc_config_stream:
        AD_HOC_UPLOAD_CONFIG.update(yaml.safe_load(ad_hoc_config_stream))
