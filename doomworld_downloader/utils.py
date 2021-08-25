"""
Various utilities for uploader.
"""

import hashlib
import logging
import os
import re
import shlex
import subprocess

from time import gmtime, strftime
from urllib.parse import urlparse

import requests

from bs4 import BeautifulSoup

from zipfile import ZipFile


HEADER_FILENAME_RE = re.compile(r'filename="(.+)"')

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
            raise RuntimeError(
                'Could not find filename from HTML response {}.'.format(response.url)
            )


def download_response(response, download_dir, download_filename):
    """Download file from response.

    :param response: Responseto download file from
    :param download_dir: Download directory to place download to
    :param download_filename: Download filename
    :return: Path to local download
    """
    os.makedirs(download_dir, exist_ok=True)
    download_path = os.path.join(download_dir, download_filename)
    with open(download_path, 'wb') as output_file:
        output_file.write(response.content)

    return download_path


def zip_extract(zip_path, extract_dir=None, extract_extension=None):
    """Extract zipfile.

    :param zip_path: Path to zip that should be extracted
    :param extract_dir: Directory to extract to (default to the zip name)
    :param extract_extension: Can be set to limit which extension should be extracted from the zip,
                              default to all
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

    DRYRUN_PREFIX = ''
    if dryrun:
        DRYRUN_PREFIX = '[DRYRUN] '

    LOGGER.info('%sRunning command "%s"', DRYRUN_PREFIX, cmd_str)
    if not dryrun:
        if get_output:
            return subprocess.check_output(cmd).decode('utf-8')

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


def parse_range(range, remove_non_numeric_chars=False):
    """Parse range of integers.

    Range provided may either be a list of two integers or a string in the format "#-#".
    Single-value ranges are padded out to two integers.

    :param range: Range of integers
    :param remove_non_numeric_chars: Flag indicating whether to remove non-numeric characters
    :return: Range of integers parsed to int
    :raises ValueError if the range is not defined or too long.
    """
    if not isinstance(range, list):
        range = range.split('-')
    if not range or len(range) > 2:
        raise ValueError('Invalid range {}.'.format(range))
    if len(range) == 1:
        range.append(range[0])

    if remove_non_numeric_chars:
        return [int(''.join(elem_char for elem_char in str(elem) if elem_char.isdigit()))
                for elem in range]
    return [int(elem) for elem in range]


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


def get_main_file_from_zip(download, file_list, zip_no_ext, file_type):
    """Get main file from zip file.

    The main file is considered to be any file that matches the zip filename.

    :param download: Download path for logging
    :param file_list: File list to search through
    :param zip_no_ext: Zip filename without the .zip extension
    :param file_type: Type of file for logging
    :return: Main filename from zip file if available, or None
    """
    for cur_file in file_list:
        file_no_ext = get_filename_no_ext(cur_file)
        if file_no_ext.lower() == zip_no_ext.lower():
            LOGGER.debug('Download %s contains multiple files of type %s, parsing just file '
                         'matching the zip name.', download, file_type)
            return file_no_ext

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
    return datetime_to_convert.strftime('%Y-%m-%d %H:%M:%S') + ' ' + strftime("%z", gmtime())


def parse_youtube_url(url):
    """Parse YouTube URLs from a URL.

    Return whether or not the URL is parsed so that if the URL wasn't a YT URL, it can be
    checked against other websites of interet.

    :param url: URL
    :return: YouTube URL code if it the URL was detected as a YouTube URL, else None
    """
    if 'youtube.com/embed' in url:
        return urlparse(url).path.strip('/').split('/')[-1]
    elif 'youtube.com/' in url:
        return url.split('watch?v=')[1]
    elif 'youtu.be/' in url:
        return url.split('youtu.be/')[1]

    return None
