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
from urllib.parse import urlparse
from zipfile import ZipFile, BadZipFile

import yaml

from doomworld_downloader.data_manager import DataManager
from doomworld_downloader.dsda import dsda_demo_page_to_json, download_demo_from_dsda, \
    get_wad_name_from_dsda_url, verify_dsda_url, conform_dsda_wad_url
from doomworld_downloader.demo_json_constructor import DemoJsonConstructor
from doomworld_downloader.doomworld_data_retriever import get_new_posts, get_new_threads, \
    download_attachments, move_post_cache_to_failed, get_ad_hoc_posts, Post, Thread
from doomworld_downloader.lmp_parser import LMPData
from doomworld_downloader.playback_parser import PlaybackData
from doomworld_downloader.post_parser import PostData
from doomworld_downloader.textfile_parser import TextfileData
from doomworld_downloader.upload_config import CONFIG, set_up_configs, set_up_ad_hoc_config, \
    AD_HOC_UPLOAD_CONFIG_PATH, DEMO_PACK_ADDITIONAL_INFO_MAP, DEMO_PACK_USER_MAP
from doomworld_downloader.utils import get_filename_no_ext, demo_range_to_string, get_log_level, \
    get_main_file_from_zip, checksum, is_demo_filename, convert_dsda_date_to_datetime
from doomworld_downloader.wad_guesser import get_wad_guesses


DOWNLOAD_INFO_FILE = 'doomworld_downloader/current_download.txt'
HEADER_FILENAME_RE = re.compile(r'filename="(.+)"')
DATETIME_FORMAT = 'YYYY'

LOGGER = logging.getLogger(__name__)


def handle_demos(demos, post_data=None, demo_info_map=None, extra_wad_guess=None):
    """Handle all demos for a particular upload.

    The upload could be a part of a post, demo pack, etc.

    :param demos: List of demos to handle
    :param post_data: Post data info if available
    :param demo_info_map: Demo info map for additional demo information during demo pack uploads
    :param extra_wad_guess: Extra WAD guess for demo playback
    :return: Flag indicating whether all demos were parsed from all downloads
    """
    for demo in demos:
        lmp_demo_info = {}
        is_demo_pack = False
        textfile_data = None
        if demo.endswith('.zip'):
            # Rename zip to account for any whitespace in the filename
            download_dir = os.path.dirname(demo)
            demo_location_filename = get_filename_no_ext(demo).replace(' ', '_')
            demo_location = os.path.join(download_dir, f'{demo_location_filename}.zip')
            zip_extract_dir = os.path.join(download_dir, demo_location_filename)
            if demo_location != demo and not os.path.exists(demo_location):
                os.makedirs(download_dir, exist_ok=True)
                shutil.move(demo, demo_location)

            try:
                zip_file = ZipFile(demo_location)
            except BadZipFile as bad_zip_err:
                LOGGER.error('Zip %s is a bad zip file, error message %s.', demo_location,
                             bad_zip_err)
                continue
            info_list = zip_file.infolist()
            lmp_files = {}
            txt_files = []
            for zip_file_member in info_list:
                zip_file_name = zip_file_member.filename
                if is_demo_filename(zip_file_name):
                    lmp_files[zip_file_name] = datetime(*zip_file_member.date_time)
                if zip_file_name.lower().endswith('.txt'):
                    txt_files.append(zip_file_name)

            if not lmp_files:
                LOGGER.warning('No lmp files found in download %s.', demo_location)
                continue
            if CONFIG.download_type != 'dsda' and not txt_files:
                LOGGER.error('No txt files found in download %s.', demo_location)
                continue

            if len(lmp_files) != 1:
                main_lmp = get_main_file_from_zip(demo_location, lmp_files, demo_location_filename,
                                                  file_types=['cdm', 'lmp', 'zdd'])
                if main_lmp:
                    lmp_files = {main_lmp: lmp_files[main_lmp]}
                else:
                    is_demo_pack = True
            if len(txt_files) != 1:
                main_txt = get_main_file_from_zip(demo_location, txt_files, demo_location_filename,
                                                  file_types='txt')
                if main_txt:
                    txt_files = [main_txt]
                else:
                    LOGGER.warning('Multiple txt files found in download %s with no primary txt '
                                   'found, skipping textfile parsing.', demo_location)

            if is_demo_pack:
                LOGGER.warning('Download %s is a demo pack zip.', demo_location)

            zip_file.extractall(path=zip_extract_dir, members=list(lmp_files.keys()) + txt_files)

            # Only cases with a single textfile are parsed.
            if len(txt_files) == 1:
                textfile_data = TextfileData(os.path.join(zip_extract_dir, txt_files[0]))
                if textfile_data:
                    textfile_data.analyze()

                    textfile_iwad = textfile_data.raw_data.get('iwad')
                    if textfile_iwad:
                        lmp_demo_info = {'iwad': textfile_iwad}
        elif is_demo_filename(demo):
            demo_date = demo_info_map.get(demo, {}).get('recorded_date')
            if not demo_date:
                raise RuntimeError(f'Non-zipped LMP {demo} requires date to be provided.')
            lmp_files = {demo: demo_date}
            zip_extract_dir = None
            demo_location = demo
            demo_location_filename = get_filename_no_ext(demo).replace(' ', '_')
        else:
            raise RuntimeError(f'Demo {demo} provided that is an unsupported filetype.')

        demo_info = {}
        if demo_info_map:
            demo_info = demo_info_map.get(demo, {})
            if isinstance(demo_info, list):
                # Only get demo ID from demo info if this is a demo pack.
                if len(demo_info) > 1:
                    demo_info = {key: value
                                 for key, value in demo_info[0].items() if key == 'demo_id'}
                else:
                    demo_info = demo_info[0]

        if demo_info.get('demo_id'):
            demo_id = demo_info['demo_id']
        else:
            demo_id = demo_location.rstrip(os.path.sep).split(os.path.sep)[-2]

        demo_json_constructor = DemoJsonConstructor(demo_location, demo_location_filename, demo_id)
        for lmp_file, recorded_date in lmp_files.items():
            lmp_path = os.path.join(zip_extract_dir, lmp_file) if zip_extract_dir else lmp_file
            lmp_data = LMPData(lmp_path, recorded_date, demo_info=lmp_demo_info)
            lmp_data.analyze()
            iwad = lmp_data.raw_data.get('iwad', '')
            demo_info_from_lmp = {
                'is_solo_net': lmp_data.data.get('is_solo_net', False),
                'complevel': lmp_data.raw_data.get('complevel'), 'iwad': iwad,
                'footer_files': lmp_data.raw_data['wad_strings'],
                'skill': lmp_data.raw_data.get('skill'),
                'num_players': lmp_data.raw_data.get('num_players'),
                'source_port': lmp_data.data.get('source_port')
            }
            post_wad_links = post_data.raw_data['wad_links'] if post_data else []
            textfile_wad_links = textfile_data.raw_data['wad_strings'] if textfile_data else []
            extra_wad_guesses = [extra_wad_guess] if extra_wad_guess else []
            wad_guesses = get_wad_guesses(
                post_wad_links, textfile_wad_links, lmp_data.raw_data['wad_strings'],
                extra_wad_guesses, iwad=iwad
            )

            playback_data = PlaybackData(lmp_path, wad_guesses, demo_info=demo_info_from_lmp)
            playback_data.analyze()
            if not CONFIG.skip_playback and playback_data.playback_failed:
                LOGGER.info('Skipping post with zip %s due to issues with playback.', demo_location)
                return False
            if is_demo_pack and CONFIG.skip_demo_pack_issues:
                LOGGER.info('Skipping demo %s in demo pack %s due to issues with playback.',
                            lmp_file, demo_location)
                return False

            data_manager = DataManager()
            lmp_data.populate_data_manager(data_manager)
            playback_data.populate_data_manager(data_manager)
            all_note_strings = set().union(lmp_data.note_strings, playback_data.note_strings)
            if textfile_data:
                textfile_data.populate_data_manager(data_manager)
                all_note_strings = all_note_strings.union(textfile_data.note_strings)
            if post_data:
                post_data.populate_data_manager(data_manager)
                all_note_strings = all_note_strings.union(post_data.note_strings)
            if demo_info.get('player_list'):
                data_manager.insert('player_list', demo_info['player_list'],
                                    DataManager.CERTAIN, source='extra_info')

            demo_json_constructor.parse_data_manager(data_manager, all_note_strings, lmp_file)

        demo_json_constructor.dump_demo_jsons()
        if zip_extract_dir:
            shutil.rmtree(zip_extract_dir)

    return True


def get_demo_pack_demos():
    """Get demo pack demos mapped to their info map for demo pack mode.

    :return: Demo pack demos mapped to their info map for demo pack mode
    """
    input_folder_dirname = os.path.basename(CONFIG.demo_pack_input_folder)
    demo_pack_demos = {}
    for path, _, files in os.walk(CONFIG.demo_pack_input_folder):
        player_name = os.path.basename(path)
        # Skip top-level directory
        if player_name == input_folder_dirname:
            continue

        player_info = DEMO_PACK_USER_MAP.get(player_name, {})
        player_discord_name = player_info.get('discord', player_name)
        player_dsda_name = player_info.get('dsda', player_name)
        player_attach_infos = DEMO_PACK_ADDITIONAL_INFO_MAP.get(player_discord_name)
        if not player_attach_infos:
            LOGGER.error('Player %s found with no attachments.', player_name)
            continue

        player_attachments = {}
        for attach_info in player_attach_infos:
            attach_name = attach_info['attach_name']
            if attach_info.get('ignore', False):
                continue
            if attach_name.endswith('.zip') or is_demo_filename(attach_name):
                final_filenames = attach_info.get('final_filenames')
                final_filename = attach_info.get('final_filename')
                if final_filenames:
                    for final_filename in final_filenames:
                        player_attachments[final_filename] = attach_info['time']
                elif final_filename:
                    player_attachments[final_filename] = attach_info['time']
                else:
                    player_attachments[attach_name.lower()] = attach_info['time']

        if isinstance(player_dsda_name, list):
            player_dsda_name = tuple(player_dsda_name)
        else:
            player_dsda_name = (player_dsda_name,)

        for demo_file in files:
            if demo_file.endswith('.zip') or is_demo_filename(demo_file):
                demo_info = {'player_list': player_dsda_name}
                if demo_file not in player_attachments:
                    LOGGER.error(
                        "Demo %s found in player %s folder not in player's attachments..",
                        demo_file, player_name
                    )
                else:
                    demo_info['recorded_date'] = convert_dsda_date_to_datetime(
                        player_attachments[demo_file]
                    )

                demo_pack_demos[os.path.join(path, demo_file)] = demo_info
    return demo_pack_demos


def get_dsda_demos(use_cached_downloads):
    """Get demos for DSDA mode mapped to their info map.

    :param use_cached_downloads: Flag indicating to use cached download info
    :return: Demos for DSDA mode mapped to their info map
    """
    dsda_mode_demos = {}
    dsda_mode_cache = os.path.join(CONFIG.dsda_mode_download_directory, 'demo_info.yaml')
    replacement_zips = []
    if CONFIG.dsda_mode_replace_zips:
        replacement_zips = [filename for filename in os.listdir(CONFIG.dsda_mode_replace_zips_dir)]

    if use_cached_downloads:
        with open(dsda_mode_cache) as cache_stream:
            dsda_mode_demos = yaml.safe_load(cache_stream)

        for demo, demo_list in dsda_mode_demos.items():
            for demo_dict in demo_list:
                demo_dict['player_list'] = tuple(demo_dict['player_list'])
    else:
        dsda_page_info = dsda_demo_page_to_json(CONFIG.dsda_mode_page)
        for dsda_row in dsda_page_info:
            download_link = next(iter(dsda_row['Time'].links.values()))
            download_filename = urlparse(download_link).path.strip('/').split('/')[-1]
            if not replacement_zips or download_filename in replacement_zips:
                local_path = download_demo_from_dsda(download_link,
                                                     CONFIG.dsda_mode_download_directory,
                                                     overwrite=True)
                if download_filename in replacement_zips:
                    local_path = os.path.join(CONFIG.dsda_mode_replace_zips_dir, download_filename)
            else:
                continue

            dsda_info = {}
            for key, value in dsda_row.items():
                if key == 'Player(s)':
                    continue

                if isinstance(value, list):
                    text = '\n'.join(cell.text for cell in value)
                else:
                    text = value.text

                dsda_info[key.lower()] = text

            if dsda_row['video'].links:
                video_link = next(iter(dsda_row['video'].links.values()))
                dsda_info['video_link'] = video_link.split('=')[1]
            if not dsda_info.get('wad'):
                dsda_info['wad'] = get_wad_name_from_dsda_url(CONFIG.dsda_mode_page)
            if not dsda_info.get('tags'):
                dsda_info['tags'] = None

            demo_info_map = {'player_list': tuple(dsda_row['Player(s)'].text.split('\n')),
                             'demo_id': urlparse(download_link).path.strip('/').split('/')[-2],
                             'dsda_info': dsda_info}
            if local_path in dsda_mode_demos:
                dsda_mode_demos[local_path].append(demo_info_map)
            else:
                dsda_mode_demos[local_path] = [demo_info_map]

        with open(dsda_mode_cache, 'w', encoding='utf-8') as cache_stream:
            yaml.safe_dump(dsda_mode_demos, cache_stream)
    return dsda_mode_demos


def get_doomworld_posts(search_end_date, search_start_date, use_cached_downloads):
    """Get Doomworld posts for download.

    :param search_start_date: Search start date
    :param search_end_date: Search end date
    :param use_cached_downloads: Flag indicating to use cached download info
    :return: Doomworld post list
    """
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
    return posts


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
    # Setting these variables always so linting tools don't get angry :p
    search_start_date = None
    search_end_date = None
    if CONFIG.download_type == 'date-based':
        search_start_date = datetime.strptime(CONFIG.search_start_date, '%Y-%m-%dT%H:%M:%SZ')
        search_end_date = datetime.strptime(CONFIG.search_end_date, '%Y-%m-%dT%H:%M:%SZ')
        current_download_info = demo_range_to_string(search_start_date, search_end_date)
    elif CONFIG.download_type == 'ad-hoc':
        set_up_ad_hoc_config()
        current_download_info = checksum(AD_HOC_UPLOAD_CONFIG_PATH)
    elif CONFIG.download_type == 'demo_pack':
        current_download_info = None
        if not CONFIG.demo_pack_input_folder or not CONFIG.demo_pack_output_folder:
            raise ValueError('Demo pack input and output folders must be set for demo_pack mode.')
    elif CONFIG.download_type == 'dsda':
        current_download_info = CONFIG.dsda_mode_page
        if not CONFIG.dsda_mode_page:
            raise ValueError('DSDA page must be set for DSDA mode.')
    else:
        raise ValueError(f'Unknown demo processing type {CONFIG.download_type} passed.')

    with open(DOWNLOAD_INFO_FILE) as cached_download_strm:
        cached_download_info = cached_download_strm.read().strip()

    use_cached_downloads = (not CONFIG.ignore_cache and cached_download_info and
                            current_download_info == cached_download_info)
    if CONFIG.download_type == 'demo_pack':
        demo_pack_demos = get_demo_pack_demos()
        handle_demos(list(demo_pack_demos.keys()), demo_info_map=demo_pack_demos)
    elif CONFIG.download_type == 'dsda':
        dsda_mode_demos = get_dsda_demos(use_cached_downloads)
        extra_wad_guess = None
        if verify_dsda_url(CONFIG.dsda_mode_page, page_types=['player', 'wad']) == 'wad':
            extra_wad_guess = conform_dsda_wad_url(CONFIG.dsda_mode_page)
        handle_demos(list(dsda_mode_demos.keys()), demo_info_map=dsda_mode_demos,
                     extra_wad_guess=extra_wad_guess)
    else:
        posts = get_doomworld_posts(search_end_date, search_start_date, use_cached_downloads)
        for post in posts:
            post_data = PostData(post)
            post_data.analyze()
            downloads_handled = handle_demos(post.cached_downloads, post_data=post_data)
            if not downloads_handled:
                move_post_cache_to_failed(post)

    if current_download_info:
        with open(DOWNLOAD_INFO_FILE, 'w') as current_download_strm:
            current_download_strm.write(current_download_info)


if __name__ == '__main__':
    main()
