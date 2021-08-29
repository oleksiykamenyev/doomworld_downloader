"""
Doomworld downloader.
"""
# TODO: Consider defining custom exceptions everywhere

import argparse
import json
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
    download_attachments, move_post_cache_to_failed, Post, Thread
from doomworld_downloader.lmp_parser import LMPData
from doomworld_downloader.playback_parser import PlaybackData
from doomworld_downloader.post_parser import PostData
from doomworld_downloader.textfile_parser import TextfileData
from doomworld_downloader.upload_config import CONFIG, set_up_configs
from doomworld_downloader.utils import get_filename_no_ext, demo_range_to_string, get_log_level, \
    get_main_file_from_zip
from doomworld_downloader.wad_guesser import get_wad_guesses


DOWNLOAD_INFO_FILE = 'doomworld_downloader/current_download.txt'
HEADER_FILENAME_RE = re.compile(r'filename="(.+)"')
DATETIME_FORMAT = 'YYYY'
VALID_ISSUE_DIR = 'issue_jsons'
VALID_NO_ISSUE_DIR = 'no_issue_jsons'

LOGGER = logging.getLogger(__name__)


def set_up_demo_json_file(json_filename, json_dir):
    """Set up demo JSON file creation.

    :param json_filename: JSON filename
    :param json_dir: Directory to create JSON under
    :return: Path to JSON file to create
    """
    json_dir = os.path.join(CONFIG.demo_download_directory, json_dir)
    os.makedirs(json_dir, exist_ok=True)
    json_path = os.path.join(json_dir, json_filename)
    return json_path


def handle_downloads(downloads, post_data):
    """Handle all downloads for post.

    :param downloads: List of downloads to handle
    :param post_data: Post data info
    :return: Flag indicating whether all demos were parsed from all downloads
    """
    for download in downloads:
        # TODO: Handle demo packs
        # Rename zip to account for any whitespace in the filename
        zip_no_ext = get_filename_no_ext(download).replace(' ', '_')
        download_dir = os.path.dirname(download)
        out_path = os.path.join(download_dir, zip_no_ext)
        renamed_zip = '{}.zip'.format(out_path)
        shutil.move(download, renamed_zip)

        zip_file = ZipFile(renamed_zip)
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
            LOGGER.warning('No lmp files found in download %s.', renamed_zip)
            continue
        if not txt_files:
            LOGGER.error('No txt files found in download %s.', renamed_zip)
            continue

        is_demo_pack = False
        if len(lmp_files) != 1:
            main_lmp = get_main_file_from_zip(renamed_zip, lmp_files, zip_no_ext, file_type='lmp')
            if main_lmp:
                lmp_files = {main_lmp: lmp_files[main_lmp]}
            else:
                is_demo_pack = True
        if len(txt_files) != 1:
            main_txt = get_main_file_from_zip(renamed_zip, txt_files, zip_no_ext, file_type='txt')
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

        for lmp_file, recorded_date in lmp_files.items():
            lmp_path = os.path.join(out_path, lmp_file)
            lmp_data = LMPData(lmp_path, recorded_date, demo_info=lmp_demo_info)
            lmp_data.analyze()
            iwad = lmp_data.raw_data.get('iwad', '')
            demo_info = {'is_solo_net': lmp_data.data.get('is_solo_net', False),
                         'complevel': lmp_data.raw_data.get('complevel'),
                         'iwad': iwad, 'footer_files': lmp_data.raw_data['wad_strings']}
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
            if playback_data.playback_failed:
                LOGGER.info('Skipping post with zip %s due to issues with playback.',
                            renamed_zip)
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

            demo_json_constructor = DemoJsonConstructor(data_manager, all_note_strings,
                                                        renamed_zip)
            download_split = renamed_zip.rstrip(os.path.sep).split(os.path.sep)
            # Download path sample: demos_for_upload/PlayerName/123456/demo.zip
            # Set json filename to demo_PlayerName_123456
            json_filename = '{}_{}_{}.json'.format(zip_no_ext, download_split[-3],
                                                   download_split[-2])
            json_path = (set_up_demo_json_file(json_filename, VALID_ISSUE_DIR)
                         if demo_json_constructor.has_issue
                         else set_up_demo_json_file(json_filename, VALID_NO_ISSUE_DIR))

            with open(json_path, 'w', encoding='utf-8') as out_stream:
                json.dump(demo_json_constructor.demo_json, out_stream, indent=4, sort_keys=True)

        shutil.rmtree(out_path)

    return True


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Doomworld demo downloader.')

    parser.add_argument('-c', '--upload-config',
                        dest='upload_config',
                        help='Path to the upload configuration for the downloader.')
    parser.add_argument('-v', '--verbose',
                        action='count',
                        default=0,
                        help='Control verbosity of output.')

    return parser.parse_args()


def main():
    """Main function."""
    args = parse_args()
    log_level = get_log_level(args.verbose)
    # TODO: Skip noisy messages in underlying url libraries unless in very verbose mode
    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')

    set_up_configs(upload_config_path=args.upload_config)
    testing_mode = CONFIG.testing_mode

    search_start_date = datetime.strptime(CONFIG.search_start_date, '%Y-%m-%dT%H:%M:%SZ')
    search_end_date = datetime.strptime(CONFIG.search_end_date, '%Y-%m-%dT%H:%M:%SZ')
    demo_range = demo_range_to_string(search_start_date, search_end_date)

    with open(DOWNLOAD_INFO_FILE) as current_download_strm:
        current_download_info = current_download_strm.read().strip()

    use_cached_downloads = current_download_info and demo_range == current_download_info
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
        threads = get_new_threads(search_start_date, testing_mode)
        posts = get_new_posts(search_start_date, search_end_date, testing_mode, threads)
    # TODO: Implement testing mode or unit tests of some sort
    # In case of testing, use no data for now
    if testing_mode:
        posts = []

    for post in posts:
        download_attachments(post)
    with open(DOWNLOAD_INFO_FILE, 'w') as current_download_strm:
        current_download_strm.write(demo_range)

    for post in posts:
        post_data = PostData(post)
        post_data.analyze()
        downloads_handled = handle_downloads(post.cached_downloads, post_data)
        if not downloads_handled:
            move_post_cache_to_failed(post)


if __name__ == '__main__':
    main()
