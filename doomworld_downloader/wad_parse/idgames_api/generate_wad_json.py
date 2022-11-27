"""
Script to generate WAD json for given new wad config.

YAML syntax:
- wad_name
- idgames_url # format: https://www.doomworld.com/idgames/{file_path}

Usage: generate_wad_json.py wad_config
"""

import argparse
import glob
import json
import logging
import os
import re
import shutil

from datetime import datetime
from zipfile import ZipFile

import yaml

import omg

from idgames import get_file_id_from_idgames_url, IdgamesAPI


# The most conservative value here would be December 10, 1993 (i.e., the Doom release date), but
# practically speaking, the earliest wad file known that is available online is Origwad, which
# is already timestamped only as late as March 1993.
EARLIEST_WAD_TIME = datetime(year=1994, month=2, day=1)

RESOURCE_FILE_FORMATS = [
    # Basic PWAD/IWAD file regex
    re.compile(r'^.+\.wad$', re.IGNORECASE),
    # PK3 file regex, used by ZDoom-derivative ports
    re.compile(r'^.+\.pk3$', re.IGNORECASE),
    # PK7 file regex, used by ZDoom-derivative ports
    # Same as pk3, but uses 7-Zip for compression
    re.compile(r'^.+\.pk7$', re.IGNORECASE),
    # Eternity Engine file format
    re.compile(r'^.+\.pke$', re.IGNORECASE),
    # DeHackEd vanilla/limit-removing file format
    re.compile(r'^.+\.deh$', re.IGNORECASE),
    # Enhanced DeHackEd file format for source ports starting with Boom
    re.compile(r'^.+\.bex$', re.IGNORECASE)
]

LOGGER = logging.getLogger(__name__)


def parse_zip_info_date_time(zip_info_date_time):
    """Parse ZIP info date time.

    :param zip_info_date_time: ZIP info date time
    :return: ZIP info date time parsed into datetime object
    """
    return datetime(
        year=zip_info_date_time[0], month=zip_info_date_time[1], day=zip_info_date_time[2],
        hour=zip_info_date_time[3], minute=zip_info_date_time[4], second=zip_info_date_time[5]
    )


def parse_args():
    """Parse arguments to the script.

    :return: Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description='Generate WAD json.'
    )

    parser.add_argument('wad_config',
                        metavar='wad_config',
                        nargs=1,
                        help='Path to the WAD config to use.')
    parser.add_argument('--output-json',
                        dest='output_json',
                        required=False,
                        help='Output JSON to store to. Default to current batchdate. If file '
                             'exists, suffixed with count. Fail if output JSON exists.')
    parser.add_argument('--download-all',
                        dest='download_all',
                        required=False,
                        action='store_true',
                        help='Download all files for any wad search that returns multiple wads.')

    return parser.parse_args()


def main():
    """Main function"""
    args = parse_args()
    with open(args.wad_config[0]) as wad_config_stream:
        wad_list = yaml.safe_load(wad_config_stream)

    wad_id_list = []
    for wad in wad_list:
        if 'www.doomworld.com' in wad:
            file_id = get_file_id_from_idgames_url(wad)
            wad_id_list.append(file_id)
        else:
            file_search = IdgamesAPI.search(wad)
            if file_search.get('content'):
                files_info = file_search['content']['file']
                if not isinstance(files_info, list):
                    files_info = [files_info]

                if len(files_info) > 1 and not args.download_all:
                    raise RuntimeError(
                        'Found multiple matching wads for wad name {} during search.'.format(wad)
                    )

                wad_id_list.extend([file_info['id'] for file_info in files_info])

    wad_jsons = []
    for wad_id in wad_id_list:
        idgames_response, local_file_path = IdgamesAPI.download_file(file_id=wad_id, overwrite=True)
        file_info = idgames_response['content']

        file_creation_date = None
        tmp_extract_path = 'tmp_extraction'
        with ZipFile(local_file_path, 'r') as zip_file:
            info_list = zip_file.infolist()
            for file_zip_info in info_list:
                for resource_re in RESOURCE_FILE_FORMATS:
                    if resource_re.match(file_zip_info.filename):
                        if not file_creation_date:
                            file_creation_date = parse_zip_info_date_time(file_zip_info.date_time)
                        else:
                            cur_file_creation_date = parse_zip_info_date_time(
                                file_zip_info.date_time
                            )
                            if cur_file_creation_date > file_creation_date:
                                file_creation_date = cur_file_creation_date

            zip_file.extractall('tmp_extraction')

        wads_in_zip = glob.glob('{}/*.wad'.format(tmp_extract_path))
        num_maps = 0
        for wad in wads_in_zip:
            try:
                wad_object = omg.WAD(wad)
                num_maps += len(wad_object.maps)
            except ValueError:
                LOGGER.exception('Encountered error when parsing WAD %s.', wad)

        if num_maps < 1:
            LOGGER.error('No maps found for wad %s.', file_info['filename'])

        # idgames date format: YYYY-MM-DD
        # This expression splits the date by '-', converts each element to int, then passes the
        # values as args to the datetime constructor
        idgames_date = datetime(*map(int, file_info['date'].split('-')))
        idgames_year = idgames_date.year
        file_creation_year = file_creation_date.year
        if idgames_year != file_creation_year:
            LOGGER.error('Mismatched years in idgames date and file creation date for wad %s!',
                         file_info['filename'])
            LOGGER.error('Idgames year: %s, file creation year: %s.', idgames_year,
                         file_creation_year)

        wad_year = file_creation_year
        if file_creation_date < EARLIEST_WAD_TIME:
            wad_year = idgames_year

        wad_json = {
            'author': file_info['author'],
            'single_map': num_maps == 1,
            'iwad': file_info['dir'].split('/')[1],
            'name': file_info['title'],
            'short_name': os.path.splitext(file_info['filename'])[0],
            'year': wad_year,
            'file': {
                'name': local_file_path,
                'data': 'placeholder'
            }
        }
        wad_jsons.append(wad_json)

        shutil.rmtree(tmp_extract_path)

    wad_jsons = {'wads': wad_jsons}
    output_json = args.output_json
    if not output_json:
        output_json = '{}_upload.json'.format(datetime.today().strftime('%Y%m%d'))
        if os.path.exists(output_json):
            filename_no_ext = os.path.splitext(output_json)[0]
            alt_file_list = glob.glob('{}_*.json'.format(filename_no_ext))
            if not alt_file_list:
                output_json = '{}_2.json'.format(filename_no_ext)
            else:
                max_idx = max(int(os.path.splitext(filename)[0].split('_')[-1])
                              for filename in alt_file_list)
                output_json = '{}_{}.json'.format(filename_no_ext, max_idx + 1)

    if os.path.exists(output_json):
        raise OSError('Output JSON {} already exists!'.format(output_json))
    with open(output_json, 'w') as output_stream:
        json.dump(wad_jsons, output_stream, sort_keys=True, indent=2)


if __name__ == '__main__':
    main()
