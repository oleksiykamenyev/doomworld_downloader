"""
Doomworld downloader.
"""
# TODO: Consider defining custom exceptions everywhere

import argparse
import logging
import os

from datetime import datetime
from urllib.parse import urlparse

import yaml

from doomworld_downloader.dsda import dsda_demo_page_to_json, download_demo_from_dsda, \
    get_wad_name_from_dsda_url, verify_dsda_url, conform_dsda_wad_url
from doomworld_downloader.demo_json_dumper import DemoJsonDumper
from doomworld_downloader.demo_processor import DemoProcessor
from doomworld_downloader.doomworld_data_retriever import get_doomworld_posts, \
    move_post_cache_to_failed
from doomworld_downloader.upload_config import CONFIG, set_up_configs, set_up_ad_hoc_config, \
    AD_HOC_UPLOAD_CONFIG_PATH
from doomworld_downloader.utils import demo_range_to_string, get_log_level, checksum


DOWNLOAD_INFO_FILE = 'doomworld_downloader/current_download.txt'

LOGGER = logging.getLogger(__name__)


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
    if CONFIG.upload_type == 'date-based':
        search_start_date = datetime.strptime(CONFIG.search_start_date, '%Y-%m-%dT%H:%M:%SZ')
        search_end_date = datetime.strptime(CONFIG.search_end_date, '%Y-%m-%dT%H:%M:%SZ')
        current_download_info = demo_range_to_string(search_start_date, search_end_date)
    elif CONFIG.upload_type == 'ad-hoc':
        set_up_ad_hoc_config()
        current_download_info = checksum(AD_HOC_UPLOAD_CONFIG_PATH)
    elif CONFIG.upload_type == 'demo_pack':
        current_download_info = CONFIG.demo_pack_name
        if not CONFIG.demo_pack_input_folder or not CONFIG.demo_pack_output_folder:
            raise ValueError('Demo pack input and output folders must be set for demo_pack mode.')
    elif CONFIG.upload_type == 'dsda':
        current_download_info = CONFIG.dsda_mode_page
        if not CONFIG.dsda_mode_page:
            raise ValueError('DSDA page must be set for DSDA mode.')
    else:
        raise ValueError(f'Unknown demo processing type {CONFIG.upload_type} passed.')

    with open(DOWNLOAD_INFO_FILE) as cached_download_strm:
        cached_download_info = cached_download_strm.read().strip()

    use_cached_downloads = (not CONFIG.ignore_cache and cached_download_info and
                            current_download_info == cached_download_info)
    demo_json_dumper = DemoJsonDumper()
    if CONFIG.upload_type == 'demo_pack':
        # TODO: reimplement on new demo pack
        #
        # Expected process:
        #   - some utility downloads demos from temp demo pack location (e.g., Discord), populating
        #     a config with all of the info needed (recorded dates, player name, wad guesses)
        #   - the above utility also creates the demo list or downloads to local, and this script
        #     recursively grabs anything that looks like a demo from there
        #   - the demo list and config is passed here
        pass
        # demo_pack_demos = get_demo_pack_demos()
        # handle_demos(list(demo_pack_demos.keys()), demo_info_map=demo_pack_demos)
    elif CONFIG.upload_type == 'dsda':
        dsda_mode_demos = get_dsda_demos(use_cached_downloads)
        dsda_demo_processor = DemoProcessor(list(dsda_mode_demos.keys()))
        extra_wad_guess = None
        if verify_dsda_url(CONFIG.dsda_mode_page, page_types=['player', 'wad']) == 'wad':
            extra_wad_guess = conform_dsda_wad_url(CONFIG.dsda_mode_page)
        dsda_demo_processor.process_demos()
        #handle_demos(list(dsda_mode_demos.keys()), demo_info_map=dsda_mode_demos,
        #             extra_wad_guess=extra_wad_guess)
    else:
        posts = get_doomworld_posts(search_end_date, search_start_date, use_cached_downloads)
        for post in posts:
            post_demo_processor = DemoProcessor(post.cached_downloads)
            post_demo_processor.process_post(post)
            post_demo_processor.process_demos()
            if post_demo_processor.process_failed:
                move_post_cache_to_failed(post)
            else:
                for demo_info in post_demo_processor.demo_infos:
                    demo_json_dumper.add_demo_json(demo_info)

        demo_json_dumper.dump_json_uploads()

    if current_download_info:
        with open(DOWNLOAD_INFO_FILE, 'w') as current_download_strm:
            current_download_strm.write(current_download_info)


if __name__ == '__main__':
    main()
