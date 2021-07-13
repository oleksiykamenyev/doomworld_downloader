"""
Various utilities for uploader.
"""
import hashlib
import logging
import os
import re
import subprocess

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
    if not extract_extension.startswith('.'):
        extract_extension = '.{}'.format(extract_extension)

    zip_file = ZipFile(zip_path)
    extract_members = []
    if extract_extension:
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
    # TODO: Verify type further?
    if isinstance(cmd, list):
        cmd_str = ' '.join(cmd)
    else:
        cmd_str = cmd
        cmd = cmd.split()

    DRYRUN_PREFIX = ''
    if dryrun:
        DRYRUN_PREFIX = '[DRYRUN] '

    LOGGER.debug('%sRunning command "%s"', DRYRUN_PREFIX, cmd_str)
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


def parse_range(range):
    """Parse range of integers.

    Range provided may either be a list of two integers or a string in the format "#-#".
    Single-value ranges are padded out to two integers.

    :param range: Range of integers
    :return: Range of integers parsed to int
    :raises ValueError if the range is not defined or too long.
    """
    if not isinstance(range, list):
        range = range.split('-')
    if not range or len(range) > 2:
        raise ValueError('Invalid range {}.'.format(range))
    if len(range) == 1:
        range.extend(range[0])

    return [int(elem) for elem in range]
