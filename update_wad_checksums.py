"""
Update WAD checksums from DSDA in the DSDA URL to WAD info YAML.
"""
# TODO: Write utility to sort the WAD YAML

import argparse
import logging
import os
import re

from shutil import rmtree

import yaml

from doomworld_downloader.dsda import download_wad_from_dsda, get_wad_name_from_dsda_url
from doomworld_downloader.upload_config import CONFIG
from doomworld_downloader.utils import checksum, get_log_level, zip_extract


CHECKSUM_RE = re.compile(r'checksum: (null|\".*\")')
WAD_FILE_EXTENSIONS = ['.bex', '.deh', '.pk3', '.pk7', '.wad']

DSDA_URL_TO_WAD_INFO_FILE = 'doomworld_downloader/dsda_url_to_wad_info.yaml'
DSDA_URL_TO_WAD_INFO_BACKUP = 'doomworld_downloader/backup_dsda_url_to_wad_info.yaml'

LOGGER = logging.getLogger(__name__)


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(description='Update WAD checksums.')

    parser.add_argument('-v', '--verbose',
                        action='count',
                        default=0,
                        help='Control verbosity of output.')
    parser.add_argument('-s', '--skip-existing',
                        dest='skip_existing',
                        action='store_true',
                        help='Skip existing WAD downloads.')
    parser.add_argument('-o', '--update-specified-wads',
                        dest='update_specified_wads',
                        action='store_true',
                        help='Update only specified WADs. These can be marked in the YAML with the '
                             'key update: true.')

    return parser.parse_args()


def main():
    """Main function."""
    args = parse_args()
    log_level = get_log_level(args.verbose)
    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')
    with open(DSDA_URL_TO_WAD_INFO_FILE, encoding='utf-8') as wad_map_stream:
        wad_map_str = wad_map_stream.read()
        wad_map_stream.seek(0)
        wad_map_by_dsda_url_dict = yaml.safe_load(wad_map_stream)

    with open(DSDA_URL_TO_WAD_INFO_BACKUP, 'w', encoding='utf-8') as backup_stream:
        backup_stream.write(wad_map_str)

    wad_map_lines = wad_map_str.splitlines()
    in_wad_files = False
    local_wad_location = None
    cur_wad_url = None
    cur_wad_entry = None
    in_commercial_wad = False
    cur_download_dir = None
    new_wad_map_lines = []
    for line in wad_map_lines:
        line_strip = line.strip()
        if line_strip and not line_strip.startswith('#'):
            if line.startswith('"'):
                cur_wad_url = line.rstrip(':').replace('"', '')
                cur_wad_entry = wad_map_by_dsda_url_dict.get(cur_wad_url)
                in_commercial_wad = cur_wad_entry.get('commercial', False)
                wad_name = get_wad_name_from_dsda_url(cur_wad_url)
                cur_download_dir = os.path.join(CONFIG.wad_download_directory, wad_name)
                update_wad = cur_wad_entry.get('update', False)
                if (in_commercial_wad or (args.skip_existing and os.path.isdir(cur_download_dir)) or
                        (args.update_specified_wads and not update_wad)):
                    LOGGER.debug('Skip existing WAD %s.', cur_wad_url)
                    local_wad_location = None
                    new_wad_map_lines.append(line)
                    continue

                wad_download = download_wad_from_dsda(cur_wad_url)
                if not wad_download:
                    LOGGER.warning('Could not download WAD %s.', cur_wad_url)
                    local_wad_location = None
                    new_wad_map_lines.append(line)
                    continue
                try:
                    local_wad_location = zip_extract(wad_download, overwrite=True)
                except NotImplementedError:
                    LOGGER.exception('Issue extracting zip for WAD %s.', cur_wad_url)
                    local_wad_location = None
                    new_wad_map_lines.append(line)
                    continue

            if line == '  wad_files:':
                in_wad_files = True
                new_wad_map_lines.append(line)
                continue
            if in_wad_files and not line.startswith('    '):
                in_wad_files = False
                if local_wad_location and os.path.exists(local_wad_location):
                    wad_file_list = cur_wad_entry['wad_files'].keys()
                    for root, _, filenames in os.walk(local_wad_location):
                        for filename in filenames:
                            file_path = os.path.join(root, filename)
                            missing_file = file_path.replace(
                                local_wad_location, ''
                            ).replace('\\', '/').strip('/').lower()
                            if (missing_file not in wad_file_list and
                                    os.path.splitext(missing_file)[1] in WAD_FILE_EXTENSIONS):
                                LOGGER.info('Found missing WAD file %s in DSDA zip, adding.',
                                            missing_file)
                                new_wad_map_lines.append(
                                    (f'    {missing_file}: {{not_required_for_playback: true, '
                                     f'checksum: "{checksum(file_path)}"}}')
                                )
                    rmtree(local_wad_location)

            if in_wad_files and local_wad_location and not in_commercial_wad:
                wad_file, _ = line.split(':', 1)
                wad_file = wad_file.strip()
                wad_file_path = os.path.join(local_wad_location, wad_file)
                if not os.path.isfile(wad_file_path):
                    LOGGER.warning('Could not find WAD %s in download from %s.', wad_file,
                                   cur_wad_url)
                    new_wad_map_lines.append(line)
                    continue

                new_checksum = checksum(wad_file_path)

                line = CHECKSUM_RE.sub('checksum: "{}"'.format(new_checksum), line)

        new_wad_map_lines.append(line)

    with open(DSDA_URL_TO_WAD_INFO_FILE, 'w', encoding='utf-8') as wad_map_stream:
        wad_map_stream.write('\n'.join(new_wad_map_lines))


if __name__ == '__main__':
    main()
