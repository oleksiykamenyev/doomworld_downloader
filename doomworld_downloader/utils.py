"""
Various utilities for uploader.
"""

import hashlib
import logging
import os
import re
import shlex
import subprocess
import unicodedata

from datetime import datetime
from shutil import rmtree
from time import gmtime, strftime
from urllib.parse import parse_qs, urlparse, urlunparse

import requests

from bs4 import BeautifulSoup

from zipfile import ZipFile

# LMP: Standard demo file format (vanilla, Boom, MBF, (G)ZDoom, etc.)
# CDM: Doomsday demo format
# ZDD: ZDaemon new-style demo format
DEMO_FILE_TYPES = ['cdm', 'lmp', 'zdd']

HTTP_RE = re.compile(r'^https?://.+')
HEADER_FILENAME_RE = re.compile(r'filename="(.+)"')
IDGAMES_ID_URL_RE = re.compile(r'^https://www.doomworld.com/idgames/\?id=\d+$')

LOGGER = logging.getLogger(__name__)


def checksum(filename):
    """Get a checksum of provided filename.

    :param filename: File name to get checksum for.
    :return: Checksum of provided filename.
    """
    hash_md5 = hashlib.md5()
    with open(filename, 'rb') as file_stream:
        for chunk in iter(lambda: file_stream.read(4096), b""):
            hash_md5.update(chunk)

    return hash_md5.hexdigest()


def get_download_filename(response, default_filename=None):
    """Get download filename from response taken from web request.

    :param response: Response to check
    :param default_filename: Default filename if no download name can be found in response.
    :return: Download filename
    :raises RuntimeError if the download filename cannot be found in response and no default
                         filename is provided
    """
    if 'Content-Disposition' in response.headers:
        download_filename = HEADER_FILENAME_RE.findall(
            response.headers['Content-Disposition']
        )
    else:
        download_filename = []

    if len(download_filename) == 1:
        return download_filename[0]
    else:
        if default_filename:
            return default_filename
        else:
            LOGGER.error('Response headers: %s.', response.headers)
            raise RuntimeError(
                'Could not find filename from HTML response {}.'.format(response.url)
            )


def download_response(response, download_dir, download_filename, overwrite=False):
    """Download file from response.

    :param response: Response to download file from
    :param download_dir: Download directory to place download to
    :param download_filename: Download filename
    :param overwrite: Flag indicating whether to overwrite the local path if it exists
    :return: Path to local download
    """
    os.makedirs(download_dir, exist_ok=True)
    download_path = os.path.join(download_dir, download_filename)

    if os.path.exists(download_path):
        if overwrite:
            LOGGER.debug('Overwrite local download path %s.', download_path)
        else:
            raise OSError('Local download path {} already exists.'.format(download_path))

    with open(download_path, 'wb') as output_file:
        output_file.write(response.content)

    return download_path


def zip_extract(zip_path, extract_dir=None, extract_extension=None, overwrite=False):
    """Extract zipfile.

    :param zip_path: Path to zip that should be extracted
    :param extract_dir: Directory to extract to (default to the zip name)
    :param extract_extension: Can be set to limit which extension should be extracted from the zip,
                              default to all
    :param overwrite: Flag indicating to overwrite extraction directory
    :return: Directory of extracted contents
    :raises RuntimeError if there are no files to extract from directory with provided extension
            IOError if the provided extraction directory already exists and isn't a directory or
                    if the final extraction directory already exists
    """
    zip_file = ZipFile(zip_path)
    extract_members = []
    if extract_extension:
        if not extract_extension.startswith('.'):
            extract_extension = '.{}'.format(extract_extension)
        name_list = zip_file.namelist()
        for zip_file_member in name_list:
            if zip_file_member.lower().endswith(extract_extension):
                extract_members.append(zip_file_member)

        if not extract_members:
            raise RuntimeError('Nothing to extract from zip path {}.'.format(zip_path))

    zip_filename = os.path.basename(zip_path)
    if not extract_dir:
        extract_dir = os.path.join(os.path.dirname(zip_path), os.path.splitext(zip_filename)[0])
    else:
        if os.path.exists(extract_dir):
            if not os.path.isdir(extract_dir):
                raise IOError('Extraction path {} is not a directory.'.format(extract_dir))
        else:
            os.makedirs(extract_dir)

        extract_dir = os.path.join(extract_dir, zip_filename)

    if os.path.exists(extract_dir):
        if overwrite:
            rmtree(extract_dir)
        else:
            raise IOError('Extraction directory {} already exists.'.format(extract_dir))

    if extract_members:
        zip_file.extractall(path=extract_dir, members=extract_members)
    else:
        zip_file.extractall(path=extract_dir)
    zip_file.close()

    return extract_dir


def run_cmd(cmd, get_output=False, dryrun=False):
    """Run provided command.

    :param cmd: Command to run (provided as string or list)
    :param get_output: Flag indicating whether to get output for command
    :param dryrun: Flag indicating whether to run in dryrun mode
    :return: Output from command if get_output and dryrun are turned on else None
    """
    if isinstance(cmd, list):
        cmd_str = ' '.join(cmd)
    else:
        cmd_str = cmd
        cmd = shlex.split(cmd)

    if dryrun:
        LOGGER.info('[DRYRUN] Running command "%s"', cmd_str)
    else:
        # Debug instead of info to minimize noise when running the script
        LOGGER.debug('Running command "%s"', cmd_str)
        if get_output:
            try:
                return subprocess.check_output(cmd).decode('utf-8')
            except UnicodeDecodeError:
                LOGGER.error('Command "%s" produced error.', cmd_str)
                return subprocess.check_output(cmd).decode('utf-8', errors='ignore')

        subprocess.check_call(cmd)

    return None


def parse_list_file(list_file_path):
    """Parse newline-separated list file.

    Empty/whitespace lines and comments (prefixed with #) are skipped.

    :param list_file_path: Path to list file
    :return: List file parsed as list
    """
    with open(list_file_path) as list_file_stream:
        list_file_lines = list_file_stream.read().splitlines()

    output_list = []
    for line in list_file_lines:
        line = line.strip()
        if line.startswith('#'):
            continue

        output_list.append(line)

    return output_list


def get_filename_no_ext(path):
    """Get filename of a path with no extension.

    :param path: Path to get no-extension filename for.
    :return: Filename for path with no extension.
    """
    return os.path.basename(os.path.splitext(path)[0])


def parse_range(range_to_parse, remove_non_numeric_chars=False):
    """Parse range of integers.

    Range provided may either be a list of one or two integers, a string in the format "#-#", or
    a single string/integer value. Single-value ranges are padded out to two integers.

    :param range_to_parse: Range of integers
    :param remove_non_numeric_chars: Flag indicating whether to remove non-numeric characters
    :return: Range of integers parsed to int
    :raises ValueError if the range is not defined or too long.
    """
    if not isinstance(range_to_parse, list):
        if '-' in range_to_parse:
            range_to_parse = range_to_parse.split('-')
        else:
            range_to_parse = [range_to_parse]

    if not range_to_parse or len(range_to_parse) > 2:
        raise ValueError('Invalid range {}.'.format(range_to_parse))
    if len(range_to_parse) == 1:
        range_to_parse.append(range_to_parse[0])

    if remove_non_numeric_chars:
        return [int(''.join(elem_char for elem_char in str(elem) if elem_char.isdigit()))
                for elem in range_to_parse]
    return [int(elem) for elem in range_to_parse]


def demo_range_to_string(start_date, end_date):
    """Convert demo time range to string.

    Uses ~ as a separator since datetimes already have - inside them.

    :param start_date: Start date
    :param end_date: End date
    :return: Demo time range as string
    """
    return '{}~{}'.format(start_date, end_date)


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


def get_main_file_from_zip(download, file_list, zip_no_ext, file_types):
    """Get main file from zip file.

    The main file is considered to be any file that matches the zip filename.

    :param download: Download path for logging
    :param file_list: File list to search through
    :param zip_no_ext: Zip filename without the .zip extension
    :param file_types: Type of file for logging, could be string with a single file type or list of
                       types
    :return: Main filename from zip file if available, or None
    """
    for cur_file in file_list:
        file_no_ext = get_filename_no_ext(cur_file)
        if file_no_ext.lower() == zip_no_ext.lower():
            LOGGER.debug('Download %s contains multiple files of type %s, parsing just file '
                         'matching the zip name.', download, file_types)
            return cur_file

    return None


def get_page(url):
    """Get page at URL as a parsed tree structure using BeautifulSoup.

    :param url: URL to get
    :return: Parsed tree structure
    """
    request_res = requests.get(url)
    page_text = str(request_res.text)
    return BeautifulSoup(page_text, features='lxml')


def convert_datetime_to_dsda_date(datetime_to_convert):
    return datetime_to_convert.strftime('%Y-%m-%d %H:%M:%S') + ' ' + strftime('%z', gmtime())


def convert_dsda_date_to_datetime(dsda_date):
    return datetime.strptime(' '.join(dsda_date.split()[:-1]), '%Y-%m-%d %H:%M:%S')


def parse_youtube_url(url):
    """Parse YouTube URLs from a URL.

    Return whether or not the URL is parsed so that if the URL wasn't a YT URL, it can be
    checked against other websites of interet.

    :param url: URL
    :return: YouTube URL code if it the URL was detected as a YouTube URL, else None
    """
    url_parse = urlparse(url)
    if url_parse.hostname == 'youtu.be':
        if url_parse.path == '/watch':
            query_params = parse_qs(url_parse.query)
            if 'v' in query_params:
                return query_params['v'][0]
        else:
            return url_parse.path[1:]

    if url_parse.hostname and 'youtube' in url_parse.hostname:
        if url_parse.path == '/watch':
            query_params = parse_qs(url_parse.query)
            if 'v' in query_params:
                return query_params['v'][0]
        if url_parse.path[:3] == '/v/' or url_parse.path[:7] == '/embed/':
            return url_parse.path.split('/')[2]

    return None


def compare_iwad(demo_iwad, cmp_iwad):
    """Compare demo IWAD to given comparison IWAD.

    :param demo_iwad: Demo IWAD
    :param cmp_iwad: Comparison IWAD, passed in without the ".wad" extension
    :return: True if the IWADs are the same, false otherwise
    """
    return demo_iwad == cmp_iwad or demo_iwad == '{}.wad'.format(cmp_iwad)


def freeze_obj(obj):
    """Freeze object for hashing into a dictionary.

    :param obj: Object to freeze
    :return: Frozen object
    """
    if isinstance(obj, dict):
        return frozenset((key, freeze_obj(value)) for key, value in obj.items())
    elif isinstance(obj, list):
        return tuple(freeze_obj(elem) for elem in obj)

    return obj


def conform_url(url):
    """Conform URL to pre-defined standard.

    Make sure all of the parts of the URL are present to the following standard:
      https://www.website.domain/path/to/wherever?url=arg

    :param url: URL to conform
    :return: Conformed URL
    """
    # Assume scheme is https if not provided
    if not HTTP_RE.match(url):
        url = f'https://{url}'

    # Assume we always need to add "www." to URLs
    url_parse = urlparse(url)
    if not url_parse.netloc.startswith('www.'):
        url_parse = url_parse._replace(netloc=f'www.{url_parse.netloc}')

    return urlunparse(url_parse)


def conform_idgames_url(idgames_url):
    """Conform idgames URL.

    If the idgames URL is provided as an ID-based URL, this will try to access it and return the
    redirect URL (e.g., https://www.doomworld.com/idgames/?id=1234).

    For beta downloads URLs from Doomworld, they are so broken that I don't think there's any way to
    map them to legacy idgames URLs.

    :param url: Idgames URL
    :return: Conformed idgames URL
    """
    if IDGAMES_ID_URL_RE.match(idgames_url):
        response = requests.get(idgames_url)
        # Add an extra conform call just in case
        return conform_url(response.url)

    return idgames_url


def get_single_key_value_dict(dict_obj):
    """Get single key and its value from dictionary.

    Hack to get a single key and its value from a dictionary, intended for use with single-key
    dictionary configs where the key is treated as the name of the config mapped to its properties.

    If multiple keys are in the provided dictionary, any single key from the dictionary will be
    returned with no guarantee of consistency across different calls to the function.

    :param dict_obj: Dictionary
    :return: Single key, value pair out of the dictionary
    :raises: ValueError if an empty or null dictionary is passed in
    """
    if not dict_obj:
        raise ValueError('Empty or None config dictionary passed!')

    key = next(iter(dict_obj))
    return key, dict_obj[key]


def strip_accents(text):
    """Strip accents from string for safe directory creation.

    :param text: Text to strip accents from
    :return: Sanitized string
    """
    text = unicodedata.normalize('NFD', text).encode('ascii', 'ignore').decode('utf-8')
    return str(text)


def is_demo_filename(demo):
    """Check if provided demo has a supported filename.

    :param demo: Demo to check
    :return: True if provided demo has a supported filename, False otherwise
    """
    return os.path.splitext(demo.lower())[1].strip('.') in DEMO_FILE_TYPES


def get_orig_names_from_zip_info_map(zip_info_map):
    """Get original filenames from zip info map.

    :param zip_info_map: Zip info map
    :return: Original names from zip info map
    """
    return list(zip_member['orig_name'] for zip_member in zip_info_map.values())
