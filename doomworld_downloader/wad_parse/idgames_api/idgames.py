"""
IDGames API wrapper.

Internal idgames API documentation: https://www.doomworld.com/idgames/api/.
"""

import logging
import os
import requests
import urllib


LOGGER = logging.getLogger(__name__)


class IdgamesAPI():
    """
    IDGames API class.
    """
    IDGAMES_API_BASE = 'https://www.doomworld.com/idgames/api/api.php'
    IDGAMES_MIRRORS = [
        # Texas
        'http://ftp.mancubus.net/pub/idgames/{file_path}',
        # Germany (TLS)
        'https://www.quaddicted.com/files/idgames/{file_path}',
        # New York
        'http://youfailit.net/pub/idgames/{file_path}',
        # Virginia
        'http://www.gamers.org/pub/idgames/{file_path}'
    ]
    # Currently not used because the default requests module doesn't support these.
    # TODO: Try urllib3.request
    FTP_IDGAMES_MIRRORS = [
        # Berlin
        'ftp://ftp.fu-berlin.de/pc/games/idgames/{file_path}',
        # Idaho
        'ftp://mirrors.syringanetworks.net/idgames/{file_path}',
        # Greece
        'ftp://ftp.ntua.gr/pub/vendors/idgames/{file_path}'
    ]

    @classmethod
    def _call_api(cls, action, **params):
        """Make call to idgames API with given action and parameters.

        :param action: Action to call idgames API with
        :param params: Parameters to pass to call
        :return: Response from API
        """
        params_args = '&'.join(
            ['{name}={value}'.format(name=name, value=value)
             for name, value in params.items() if value is not None]
        )
        call_url = '{base_url}?action={action}&{params}&out=json'.format(
            base_url=cls.IDGAMES_API_BASE, action=action, params=params_args
        )

        return requests.get(call_url)

    @classmethod
    def _handle_response(cls, response):
        """Handle response from API call.

        :param response: Response object from API call
        :return: Response object converted to JSON if there was no error
        :raises RuntimeError if there as an error in the response object
        """
        response_json = response.json()
        if response_json.get('error'):
            error_type = response_json['error']['type']
            error_message = response_json['error']['message']
            raise RuntimeError('Received error in response!\n'
                               '[{type}] {message}'.format(type=error_type, message=error_message))
        if response_json.get('warning'):
            warning_type = response_json['warning']['type']
            warning_message = response_json['warning']['message']
            LOGGER.warning('Received warning in response.')
            LOGGER.warning('[%s] %s', warning_type, warning_message)

        return response_json

    @classmethod
    def ping(cls):
        """Ping idgames API."""
        response_json = cls._handle_response(cls._call_api('ping'))
        if response_json['content']['status'] == 'true':
            LOGGER.info('Ping successful! IDGames API server is up.')
        else:
            LOGGER.error('IDGames API server down!')

    @classmethod
    def dbping(cls):
        """Ping idgames database connection."""
        response_json = cls._handle_response(cls._call_api('dbping'))
        if response_json['content']['status'] == 'true':
            LOGGER.info('Ping successful! IDGames database connection is active.')
        else:
            LOGGER.error('IDGames database connection inactive!')

    @classmethod
    def about(cls):
        """Get the about info for the idgames API.

        :return: Response from idgames API as JSON
        """
        response_json = cls._handle_response(cls._call_api('about'))
        response_content = response_json['content']
        print('Credits: ' + response_content['credits'])
        print('Copyright: ' + response_content['copyright'])
        print('Additional info: ' + response_content['info'])
        return response_json

    @classmethod
    def get(cls, file_id=None, file_name=None):
        """Make get call to idgames API.

        Must pass either a file ID or file name, never both.

        :param file_id: File ID
        :param file_name: File name
        :return: Response from idgames API as JSON
        :raises ValueError if either both file name and file ID are passed or neither
        """
        if file_id and file_name:
            LOGGER.error('Both file ID %s and file name %s passed to get!', file_id, file_name)
            raise ValueError('Failed to get file!')
        if not (file_id or file_name):
            LOGGER.error('Either file ID or file name must be passed to get!')
            raise ValueError('Failed to get file!')

        if file_id:
            response = cls._call_api('get', id=file_id)
        else:
            response = cls._call_api('get', file=file_name)

        return cls._handle_response(response)

    @classmethod
    def getparentdir(cls, file_id=None, file_name=None):
        """Make getparentdir call to idgames API.

        Must pass either a file ID or file name, never both.

        :param file_id: File ID
        :param file_name: File name
        :return: Response from idgames API as JSON
        :raises ValueError if either both file name and file ID are passed or neither
        """
        if file_id and file_name:
            LOGGER.error('Both file ID %s and file name %s passed to getparentdir!',
                         file_id, file_name)
            raise ValueError('Failed to get parent directory for file!')
        if not (file_id or file_name):
            LOGGER.error('Either file ID or file name must be passed to getparentdir!')
            raise ValueError('Failed to get parent directory for file!')

        if file_id:
            response = cls._call_api('getparentdir', id=file_id)
        else:
            response = cls._call_api('getparentdir', file=file_name)

        return cls._handle_response(response)

    @classmethod
    def getdirs(cls, dir_id=None, dir_name=None):
        """Make getdirs call to idgames API.

        Must pass either a directory ID or directory name, never both.

        :param dir_id: Directory ID
        :param dir_name: Directory name
        :return: Response from idgames API as JSON
        :raises ValueError if either both directory name and directory ID are passed or neither
        """
        if dir_id and dir_name:
            LOGGER.error('Both directory ID %s and directory name %s passed to getdirs!',
                         dir_id, dir_name)
            raise ValueError('Failed to get directories under given directory!')
        if not (dir_id or dir_name):
            LOGGER.error('Either directory ID or directory name must be passed to getdirs!')
            raise ValueError('Failed to get directories under given directory!')

        if dir_id:
            response = cls._call_api('getdirs', id=dir_id)
        else:
            response = cls._call_api('getdirs', file=dir_name)

        return cls._handle_response(response)

    @classmethod
    def getfiles(cls, dir_id=None, dir_name=None):
        """Make getfiles call to idgames API.

        Must pass either a directory ID or directory name, never both.

        :param dir_id: Directory ID
        :param dir_name: Directory name
        :return: Response from idgames API as JSON
        :raises ValueError if either both directory name and directory ID are passed or neither
        """
        if dir_id and dir_name:
            LOGGER.error('Both directory ID %s and directory name %s passed to getfiles!',
                         dir_id, dir_name)
            raise ValueError('Failed to get files under given directory!')
        if not (dir_id or dir_name):
            LOGGER.error('Either directory ID or directory name must be passed to getfiles!')
            raise ValueError('Failed to get files under given directory!')

        if dir_id:
            response = cls._call_api('getfiles', id=dir_id)
        else:
            response = cls._call_api('getfiles', file=dir_name)

        return cls._handle_response(response)

    @classmethod
    def getcontents(cls, dir_id=None, dir_name=None):
        """Make getcontents call to idgames API.

        Must pass either a directory ID or directory name, never both.

        :param dir_id: Directory ID
        :param dir_name: Directory name
        :return: Response from idgames API as JSON
        :raises ValueError if either both directory name and directory ID are passed or neither
        """
        if dir_id and dir_name:
            LOGGER.error('Both directory ID %s and directory name %s passed to getcontents!',
                         dir_id, dir_name)
            raise ValueError('Failed to get contents under given directory!')
        if not (dir_id or dir_name):
            LOGGER.error('Either directory ID or directory name must be passed to getcontents!')
            raise ValueError('Failed to get contents under given directory!')

        if dir_id:
            response = cls._call_api('getcontents', id=dir_id)
        else:
            response = cls._call_api('getcontents', file=dir_name)

        return cls._handle_response(response)

    @classmethod
    def latestvotes(cls, limit=None):
        """Make latestvotes call to idgames API.

        May pass a limit argument to limit the number of results requested; however, idgames
        maintains an internal limit that is applied to the query if no limit is passed or the limit
        passed is too high.

        :param limit: Limit for results to return. (optional)
        :return: Response from idgames API as JSON
        """
        return cls._handle_response(cls._call_api('latestvotes', limit=limit))

    @classmethod
    def latestfiles(cls, limit=None, startid=None):
        """Make latestfiles call to idgames API.

        May pass a limit argument to limit the number of results requested; however, idgames
        maintains an internal limit that is applied to the query if no limit is passed or the limit
        passed is too high.

        :param limit: Limit for results to return. (optional)
        :param startid: Start ID for file from which to search for latest files. (optional)
        :return: Response from idgames API as JSON
        """
        return cls._handle_response(cls._call_api('latestfiles', limit=limit, startid=startid))

    @classmethod
    def search(cls, query, query_type=None, query_sort=None, query_dir=None):
        """Search for given query at the idgames API.

        Query string must be at least three characters.

        Query type options: filename, title, author, email, description, credits, editors, textfile.
        Query sort options: date, filename, size, rating.
        Query direction options: asc, desc.

        :param query: Query string to use for search.
        :param query_type: Query type to perform. (optional)
        :param query_sort: Query sort to use. (optional)
        :param query_dir: Query sort direction to use. (optional)
        :return: Response from idgames API as JSON
        :raises ValueError if query passed is not defined
        """
        if not query:
            raise ValueError('Please provide a query string for search!')

        return cls._handle_response(
            cls._call_api('search', query=query, type=query_type, sort=query_sort, dir=query_dir)
        )

    @classmethod
    def download_file(cls, file_name=None, file_id=None, overwrite=False, local_file_path=None):
        """Download file from idgames.

        Must pass either a file ID or file name, never both. The function will attempt to download
        from all of the known idgames mirrors.

        :param file_id: File ID
        :param file_name: File name
        :param overwrite: Flag indicating whether to overwrite file locally during download, default
                          to no overwrite
        :param local_file_path: Local file path to write to (default to the file name)
        :return: Tuple containing response from idgames API for requested file (may be empty or
                 include multiple files if the download didn't match a single file), local file path
        :raises ValueError if either both file name and file ID are passed or neither
        """
        if file_id and file_name:
            LOGGER.error('Both file ID %s and file name %s passed to download!', file_id, file_name)
            raise ValueError('Failed to download file!')
        if not (file_id or file_name):
            LOGGER.error('Either file ID or file name must be passed to download!')
            raise ValueError('Failed to download file!')

        if file_id:
            idgames_response = cls.get(file_id=file_id)
        else:
            idgames_response = cls.search(query=file_name)

        if not idgames_response.get('content'):
            LOGGER.info('No files found to download!')
            return idgames_response, None

        if idgames_response['content'].get('file'):
            files_info = idgames_response['content']['file']
            if isinstance(idgames_response['content']['file'], list):
                LOGGER.info('Multiple WAD files found! Please choose one of the below file IDs and '
                            'download by ID.')
                for file_info in files_info:
                    print(file_info['id'], os.path.join(file_info['dir'], file_info['filename']))

                return idgames_response, None
        else:
            files_info = idgames_response['content']

        file_path = os.path.join(files_info['dir'], files_info['filename'])
        for mirror in cls.IDGAMES_MIRRORS:
            wad_url = mirror.format(file_path=file_path)
            try:
                file_download = requests.get(wad_url)
                file_download.raise_for_status()
            except requests.exceptions.RequestException:
                LOGGER.exception('Caught request exception from idgames mirror %s.', wad_url)
                continue
            except requests.exceptions.HTTPError:
                LOGGER.exception('Request to idgames mirror unsuccessful: %s.', wad_url)
                continue

            break

        if not file_download:
            raise RuntimeError('Could not download file from any of the known mirrors!')

        if local_file_path is None:
            local_file_path = os.path.join(files_info['dir'], files_info['filename'])
        if os.path.exists(local_file_path) and not overwrite:
            raise OSError(
                'Local file path {} already exists and overwrite is not turned on!'.format(
                    local_file_path
                )
            )

        if os.path.dirname(local_file_path):
            os.makedirs(os.path.dirname(local_file_path), exist_ok=True)
        with open(local_file_path, 'wb') as file_stream:
            file_stream.write(file_download.content)

        return idgames_response, local_file_path


def get_file_id_from_idgames_url(idgames_url):
    url_parsed = urllib.parse.urlparse(idgames_url)
    if url_parsed.netloc != 'www.doomworld.com' or not url_parsed.path.startswith('/idgames/'):
        raise ValueError('Invalid idgames URL passed: {}'.format(idgames_url))

    file_name = os.path.basename(url_parsed.path)
    file_search = IdgamesAPI.search(file_name)
    if file_search.get('content'):
        files_info = file_search['content']['file']
        if not isinstance(files_info, list):
            files_info = [files_info]

        file_path = url_parsed.path[9:]
        for file_info in files_info:
            if file_path == os.path.join(file_info['dir'],
                                         os.path.splitext(file_info['filename'])[0]):
                return file_info['id']

        LOGGER.error('Could not find matching wad ID in file info list. File info list:\n',
                     files_info)
        raise ValueError('Could not get file ID for URL {}.'.format(idgames_url))

    LOGGER.info('No file ID found for given idgames URL %s!', idgames_url)
    return None
