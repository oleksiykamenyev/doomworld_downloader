"""
Update WAD checksums from DSDA in the DSDA URL to WAD info YAML.
"""

import argparse
import logging
import os
import re

from shutil import rmtree

from doomworld_downloader.dsda import download_wad_from_dsda
from doomworld_downloader.utils import checksum, get_log_level, zip_extract


CHECKSUM_RE = re.compile(r'checksum: (null|\".*\")')
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

    return parser.parse_args()


def main():
    """Main function."""
    args = parse_args()
    log_level = get_log_level(args.verbose)
    logging.basicConfig(level=log_level,
                        format='%(asctime)s - %(name)s - %(levelname)s: %(message)s')
    with open(DSDA_URL_TO_WAD_INFO_FILE, encoding='utf-8') as wad_map_stream:
        wad_map_str = wad_map_stream.read()

    with open(DSDA_URL_TO_WAD_INFO_BACKUP, 'w', encoding='utf-8') as backup_stream:
        backup_stream.write(wad_map_str)

    wad_map_lines = wad_map_str.splitlines()
    in_wad_files = False
    local_wad_location = None
    cur_wad_url = None
    new_wad_map_lines = []
    for line in wad_map_lines:
        line_strip = line.strip()
        if line_strip and not line_strip.startswith('#'):
            if line.startswith('"'):
                cur_wad_url = line.rstrip(':').replace('"', '')
                wad_download = download_wad_from_dsda(cur_wad_url)
                if not wad_download:
                    LOGGER.warning('Could not download WAD %s.', cur_wad_url)
                    local_wad_location = None
                    new_wad_map_lines.append(line)
                    continue
                local_wad_location = zip_extract(wad_download, overwrite=True)

            if line == '  wad_files:':
                in_wad_files = True
                new_wad_map_lines.append(line)
                continue
            if in_wad_files and not line.startswith('    '):
                in_wad_files = False
                if local_wad_location and os.path.exists(local_wad_location):
                    rmtree(local_wad_location)
            if in_wad_files and local_wad_location:
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
