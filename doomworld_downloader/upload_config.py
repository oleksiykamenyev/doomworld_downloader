from configparser import ConfigParser, NoSectionError, NoOptionError


class UploadConfig:
    def __init__(self):
        self._config = ConfigParser()
        # TODO: Consider making this configurable
        self._config.read('doomworld_downloader/upload.ini')

    @property
    def search_start_date(self):
        return self._config.get('general', 'search_start_date')

    @property
    def search_end_date(self):
        return self._config.get('general', 'search_end_date')

    @property
    def prboom_plus_directory(self):
        return self._config.get('general', 'prboom_plus_directory')

    @property
    def parse_lmp_directory(self):
        return self._config.get('general', 'parse_lmp_directory')

    @property
    def testing_mode(self):
        try:
            return self._config.getboolean('general', 'testing_mode')
        except (NoSectionError, NoOptionError):
            return False


CONFIG = UploadConfig()
