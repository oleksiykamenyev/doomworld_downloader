"""
Doomworld downloader.

# TODO: Rename/reorganize this code
Specifically, I see the following structure making sense:
  - entry main code (probably rename this class to something like dsda_auto_updater)
    - this will contain just calls to the underlying stuff; i.e.:
      - get all of the relevant posts using the web parsing module and download demos
      - then use a separate interpolator module that takes the data from all the sources and mushes
        it together
"""

import argparse
import logging
import os
import re
import shutil

from datetime import datetime
from glob import glob
from zipfile import ZipFile

import yaml

from doomworld_downloader.data_manager import DataManager
from doomworld_downloader.demo_json_constructor import DemoJsonConstructor
from doomworld_downloader.doomworld_data_retriever import get_new_posts, get_new_threads, \
    download_attachments, Post, Thread
from doomworld_downloader.lmp_parser import LMPData
from doomworld_downloader.playback_parser import PlaybackData
from doomworld_downloader.post_parser import PostData
from doomworld_downloader.textfile_parser import TextfileData
from doomworld_downloader.upload_config import CONFIG, set_up_configs
from doomworld_downloader.utils import get_filename_no_ext
from doomworld_downloader.wad_guesser import get_wad_guesses


DOWNLOAD_INFO_FILE = 'doomworld_downloader/current_download.txt'
HEADER_FILENAME_RE = re.compile(r'filename="(.+)"')
DATETIME_FORMAT = 'YYYY'

LOGGER = logging.getLogger(__name__)


# TODO: Move to util class
def demo_range_to_string(start_date, end_date):
    """Convert demo time range to string.

    Uses ~ as a separator since datetimes already have - inside them.

    :param start_date: Start date
    :param end_date: End date
    :return: Demo time range as string
    """
    return '{}~{}'.format(start_date, end_date)


# TODO: Move to util class.
def get_log_level(verbose):
    """Get log level for logging module.

    Verbosity levels:
        0 = ERROR
        1 = WARNING
        2 = INFO
        3 = DEBUG

    :param verbose: Verbosity level as integer counting number of times the
                    argument was passed to the script
    :return: Log level
    """
    if verbose >= 3:
        return logging.DEBUG
    if verbose == 2:
        return logging.INFO
    if verbose == 1:
        return logging.WARNING

    return logging.ERROR


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Doomworld demo downloader.')

    parser.add_argument('-v', '--verbose',
                        action='count',
                        default=0,
                        help='Control verbosity of output.')

    return parser.parse_args()


def main():
    """Main function."""
    args = parse_args()
    log_level = get_log_level(args.verbose)
    logging.basicConfig(
        level=log_level,
        format='%(asctime)s - %(name)s - %(levelname)s: %(message)s'
    )

    # TODO:
    #   The config files (thread map, upload.ini, etc.) should eventually be moved to be managed by
    #   pkg_resources instead of relative paths
    testing_mode = CONFIG.testing_mode
    set_up_configs()

    search_start_date = datetime.strptime(CONFIG.search_start_date, '%Y-%m-%dT%H:%M:%SZ')
    search_end_date = datetime.strptime(CONFIG.search_end_date, '%Y-%m-%dT%H:%M:%SZ')
    demo_range = demo_range_to_string(search_start_date, search_end_date)

    with open(DOWNLOAD_INFO_FILE) as current_download_strm:
        current_download_info = current_download_strm.read().strip()
    if current_download_info and demo_range == current_download_info:
        # Use cached stuff if available
        post_cache_dir = os.path.join(CONFIG.demo_download_directory, 'post_cache')
        post_info_files = glob(post_cache_dir + '/**/*.yaml', recursive=True)
        posts = []
        for post_info_file in post_info_files:
            with open(post_info_file, encoding='utf-8') as post_info_stream:
                post_dict = yaml.safe_load(post_info_stream)
            post_dict['parent'] = Thread(**post_dict['parent'])
            posts.append(Post(**post_dict))
    else:
        threads = get_new_threads(search_start_date, testing_mode)
        posts = get_new_posts(search_end_date, search_start_date, testing_mode, threads)
    # TODO: Implement testing mode or unit tests of some sort
    # In case of testing, use no data for now
    if testing_mode:
        posts = []

    demo_jsons = []
    for post in posts:
        post_data = PostData(post)
        downloads = download_attachments(post)
        # TODO: This download section should probably be in some other module
        for download in downloads:
            # TODO: Handle demo packs
            is_demo_pack = False
            zip_file = ZipFile(download)
            info_list = zip_file.infolist()
            lmp_files = {}
            txt_files = []
            for zip_file_member in info_list:
                zip_file_name = zip_file_member.filename
                if zip_file_name.lower().endswith('.lmp'):
                    lmp_files[zip_file_name] = datetime(*zip_file_member.date_time)
                if zip_file_name.lower().endswith('.txt'):
                    # TODO: Keep track of textfile date; it might be useful if the lmp date needs
                    #       sanity checking
                    txt_files.append(zip_file_name)

            if not lmp_files:
                LOGGER.warning('No lmp files found in download %s.', download)
                continue
            if not txt_files:
                LOGGER.error('No txt files found in download %s.', download)
                continue

            zip_no_ext = get_filename_no_ext(download)
            if len(lmp_files) != 1:
                # TODO: Refactor to separate function with below txt file function
                main_lmp = None
                for lmp_file in lmp_files:
                    lmp_no_ext = get_filename_no_ext(lmp_file)
                    if lmp_no_ext == zip_no_ext:
                        LOGGER.debug('Download %s contains multiple demos, parsing just demo '
                                     'matching the zip name.', download)
                        main_lmp = lmp_no_ext
                        break

                if main_lmp:
                    lmp_files = {main_lmp: lmp_files[main_lmp]}
                else:
                    is_demo_pack = True

            if len(txt_files) != 1:
                main_txt = None
                for txt_file in txt_files:
                    txt_no_ext = get_filename_no_ext(txt_file)
                    if txt_no_ext == zip_no_ext:
                        LOGGER.debug('Download %s contains multiple txts, parsing just txt '
                                     'matching the zip name.', download)
                        main_txt = txt_no_ext
                        break

                if main_txt:
                    txt_files = [main_txt]
                else:
                    LOGGER.error('Multiple txt files found in download %s with no primary txt '
                                 'found.', download)
                    continue

            download_dir = os.path.dirname(download)
            out_path = os.path.join(download_dir, zip_no_ext)
            zip_file.extractall(path=out_path, members=list(lmp_files.keys()) + txt_files)

            # There should really be only one textfile at this moment, so will assume this.
            # TODO: Should just set textfile_data if txtfile list is len 1, otherwise None
            textfile_data = None
            for txt_file in txt_files:
                textfile_data = TextfileData(os.path.join(out_path, txt_file))

            for lmp_file, recorded_date in lmp_files.items():
                lmp_path = os.path.join(out_path, lmp_file)
                lmp_data = LMPData(lmp_path, recorded_date)
                demo_info = {'is_solo_net': lmp_data.data.get('is_solo_net', False),
                             'is_chex': lmp_data.raw_data.get('is_chex', False),
                             'is_heretic': lmp_data.raw_data.get('is_heretic', False),
                             'complevel': lmp_data.raw_data.get('complevel')}
                wad_guesses = get_wad_guesses(
                    post_data.raw_data['wad_links'], textfile_data.raw_data['wad_strings'],
                    lmp_data.raw_data['wad_strings']
                )
                playback_data = PlaybackData(lmp_path, wad_guesses, demo_info=demo_info)
                data_manager = DataManager()
                post_data.populate_data_manager(data_manager)
                textfile_data.populate_data_manager(data_manager)
                lmp_data.populate_data_manager(data_manager)
                playback_data.populate_data_manager(data_manager)
                all_note_strings = set().union(post_data.note_strings, textfile_data.note_strings,
                                               lmp_data.note_strings, playback_data.note_strings)
                demo_json_constructor = DemoJsonConstructor(data_manager, all_note_strings,
                                                            download)
                print(demo_json_constructor.demo_json)

            shutil.rmtree(out_path)

    with open(DOWNLOAD_INFO_FILE, 'w') as current_download_strm:
        current_download_strm.write(demo_range)


if __name__ == '__main__':
    main()
