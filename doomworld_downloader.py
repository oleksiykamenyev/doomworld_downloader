"""
Doomworld downloader.
"""
# TODO: Consider defining custom exceptions everywhere

import argparse
import logging
import os
import re
import shutil

from datetime import datetime
from glob import glob
from zipfile import ZipFile, BadZipFile

import yaml

from doomworld_downloader.data_manager import DataManager
from doomworld_downloader.demo_json_constructor import DemoJsonConstructor
from doomworld_downloader.doomworld_data_retriever import get_new_posts, get_new_threads, \
    download_attachments, move_post_cache_to_failed, get_ad_hoc_posts, Post, Thread
from doomworld_downloader.lmp_parser import LMPData
from doomworld_downloader.playback_parser import PlaybackData
from doomworld_downloader.post_parser import PostData
from doomworld_downloader.textfile_parser import TextfileData
from doomworld_downloader.upload_config import CONFIG, set_up_configs, set_up_ad_hoc_config, \
    AD_HOC_UPLOAD_CONFIG_PATH
from doomworld_downloader.utils import get_filename_no_ext, demo_range_to_string, get_log_level, \
    get_main_file_from_zip, checksum
from doomworld_downloader.wad_guesser import get_wad_guesses


DOWNLOAD_INFO_FILE = 'doomworld_downloader/current_download.txt'
HEADER_FILENAME_RE = re.compile(r'filename="(.+)"')
DATETIME_FORMAT = 'YYYY'

LOGGER = logging.getLogger(__name__)


def handle_downloads(downloads, post_data):
    """Handle all downloads for post.

    :param downloads: List of downloads to handle
    :param post_data: Post data info
    :return: Flag indicating whether all demos were parsed from all downloads
    """
    for download in downloads:
        # Rename zip to account for any whitespace in the filename
        zip_no_ext = get_filename_no_ext(download).replace(' ', '_')
        download_dir = os.path.dirname(download)
        out_path = os.path.join(download_dir, zip_no_ext)
        renamed_zip = '{}.zip'.format(out_path)
        if renamed_zip != download and not os.path.exists(renamed_zip):
            shutil.move(download, renamed_zip)

        try:
            zip_file = ZipFile(renamed_zip)
        except BadZipFile as bad_zip_err:
            LOGGER.error('Zip %s is a bad zip file, error message %s.', renamed_zip, bad_zip_err)
            continue
        info_list = zip_file.infolist()
        lmp_files = {}
        txt_files = []
        for zip_file_member in info_list:
            zip_file_name = zip_file_member.filename
            # LMP: Standard demo file format (vanilla, Boom, MBF, (G)ZDoom, etc.)
            # CDM: Doomsday demo format
            # ZDD: ZDaemon new-style demo format
            if (zip_file_name.lower().endswith('.lmp') or zip_file_name.endswith('.cdm') or
                    zip_file_name.endswith('.zdd')):
                lmp_files[zip_file_name] = datetime(*zip_file_member.date_time)
            if zip_file_name.lower().endswith('.txt'):
                txt_files.append(zip_file_name)

        if not lmp_files:
            LOGGER.warning('No lmp files found in download %s.', renamed_zip)
            continue
        if not txt_files:
            LOGGER.error('No txt files found in download %s.', renamed_zip)
            continue

        is_demo_pack = False
        if len(lmp_files) != 1:
            main_lmp = get_main_file_from_zip(renamed_zip, lmp_files, zip_no_ext,
                                              file_types=['cdm', 'lmp', 'zdd'])
            if main_lmp:
                lmp_files = {main_lmp: lmp_files[main_lmp]}
            else:
                is_demo_pack = True
        if len(txt_files) != 1:
            main_txt = get_main_file_from_zip(renamed_zip, txt_files, zip_no_ext, file_types='txt')
            if main_txt:
                txt_files = [main_txt]
            else:
                LOGGER.warning('Multiple txt files found in download %s with no primary txt '
                               'found, skipping textfile parsing.', renamed_zip)

        if is_demo_pack:
            LOGGER.warning('Download %s is a demo pack zip.', renamed_zip)

        zip_file.extractall(path=out_path, members=list(lmp_files.keys()) + txt_files)

        # There should really be only one textfile at this moment, so will assume this.
        textfile_data = (TextfileData(os.path.join(out_path, txt_files[0]))
                         if len(txt_files) == 1 else None)
        lmp_demo_info = {}
        if textfile_data:
            textfile_data.analyze()

            textfile_iwad = textfile_data.raw_data.get('iwad')
            if textfile_iwad:
                lmp_demo_info = {'iwad': textfile_iwad}

        demo_json_constructor = DemoJsonConstructor(renamed_zip, zip_no_ext)
        for lmp_file, recorded_date in lmp_files.items():
            lmp_path = os.path.join(out_path, lmp_file)
            lmp_data = LMPData(lmp_path, recorded_date, demo_info=lmp_demo_info)
            lmp_data.analyze()
            iwad = lmp_data.raw_data.get('iwad', '')
            demo_info = {
                'is_solo_net': lmp_data.data.get('is_solo_net', False),
                'complevel': lmp_data.raw_data.get('complevel'), 'iwad': iwad,
                'footer_files': lmp_data.raw_data['wad_strings'],
                'skill': lmp_data.raw_data.get('skill'),
                'num_players': lmp_data.raw_data.get('num_players')
            }
            if textfile_data:
                wad_guesses = get_wad_guesses(
                    post_data.raw_data['wad_links'], textfile_data.raw_data['wad_strings'],
                    lmp_data.raw_data['wad_strings'], iwad=iwad
                )
            else:
                wad_guesses = get_wad_guesses(
                    post_data.raw_data['wad_links'], lmp_data.raw_data['wad_strings'], iwad=iwad
                )
            playback_data = PlaybackData(lmp_path, wad_guesses, demo_info=demo_info)
            playback_data.analyze()
            if not CONFIG.skip_playback and playback_data.playback_failed:
                LOGGER.info('Skipping post with zip %s due to issues with playback.', renamed_zip)
                return False
            if is_demo_pack and CONFIG.skip_demo_pack_issues:
                LOGGER.info('Skipping demo %s in demo pack %s due to issues with playback.',
                            lmp_file, renamed_zip)
                return False

            data_manager = DataManager()
            post_data.populate_data_manager(data_manager)
            lmp_data.populate_data_manager(data_manager)
            playback_data.populate_data_manager(data_manager)
            all_note_strings = set().union(post_data.note_strings, lmp_data.note_strings,
                                           playback_data.note_strings)
            if textfile_data:
                textfile_data.populate_data_manager(data_manager)
                all_note_strings = all_note_strings.union(textfile_data.note_strings)

            demo_json_constructor.parse_data_manager(data_manager, all_note_strings, lmp_file)

        demo_json_constructor.dump_demo_jsons()
        shutil.rmtree(out_path)

    return True


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
    # TODO: Implement unit tests of some sort
    args = parse_args()
    log_level = get_log_level(args.verbose)
    # TODO: Skip noisy messages in underlying url libraries unless in very verbose mode
    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')

    set_up_configs()
    if CONFIG.download_type == 'date-based':
        search_start_date = datetime.strptime(CONFIG.search_start_date, '%Y-%m-%dT%H:%M:%SZ')
        search_end_date = datetime.strptime(CONFIG.search_end_date, '%Y-%m-%dT%H:%M:%SZ')
        current_download_info = demo_range_to_string(search_start_date, search_end_date)
    else:
        set_up_ad_hoc_config()
        current_download_info = checksum(AD_HOC_UPLOAD_CONFIG_PATH)

        # Setting these variables so linting tools don't get angry :p
        search_start_date = None
        search_end_date = None

    with open(DOWNLOAD_INFO_FILE) as cached_download_strm:
        cached_download_info = cached_download_strm.read().strip()

    use_cached_downloads = (not CONFIG.ignore_cache and cached_download_info and
                            current_download_info == cached_download_info)
    if use_cached_downloads:
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
        if CONFIG.download_type == 'date-based':
            threads = get_new_threads(search_start_date)
            posts = get_new_posts(search_start_date, search_end_date, threads)
        else:
            posts = get_ad_hoc_posts()

        for post in posts:
            download_attachments(post)
    with open(DOWNLOAD_INFO_FILE, 'w') as current_download_strm:
        current_download_strm.write(current_download_info)

    for post in posts:
        post_data = PostData(post)
        post_data.analyze()
        downloads_handled = handle_downloads(post.cached_downloads, post_data)
        if not downloads_handled:
            move_post_cache_to_failed(post)


if __name__ == '__main__':
    main()
