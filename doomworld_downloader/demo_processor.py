"""
Demo processor.

This module will contain the code responsible for processing each demo for upload or update on DSDA.
It will also contain supplementary info classes for containing all the info about an individual zip
or demo (which may be the only member of a zip or one of many).
"""

import logging
import os
import re
import shutil

from dataclasses import dataclass, field
from datetime import datetime, timedelta
from zipfile import ZipFile, BadZipFile

from .data_manager import DataManager
from .lmp_parser import LMPData
from .playback_parser import PlaybackData
from .post_parser import PostData
from .textfile_parser import TextfileData
from .upload_config import CONFIG
from .utils import convert_datetime_to_dsda_date, get_filename_no_ext, is_demo_filename, \
    get_single_key_value_dict
from .wad_guesser import get_wad_guesses


DOWNLOAD_INFO_FILE = 'doomworld_downloader/current_download.txt'
HEADER_FILENAME_RE = re.compile(r'filename="(.+)"')
DATETIME_FORMAT = 'YYYY'
ZIP_RE = re.compile(r'^.*\.zip$', re.IGNORECASE)

LOGGER = logging.getLogger(__name__)


class DemoProcessor:
    """Demo processor object."""

    def __init__(self, demos_to_process, additional_demo_info=None):
        """Initialize demo info object.

        :param demos_to_process: Demos to process
        :param additional_demo_info: Additional demo info, if available
        """
        # Inputs for demo upload
        self.demos_to_process = demos_to_process
        self.additional_demo_info = additional_demo_info if additional_demo_info else {}

        # Outputs after processing
        self.post_data = None
        self.demo_infos = []
        self.process_failed = False

    def process_post(self, post=None):
        """Process post, if available.

        :param post: Post info as a dictionary
        """
        if not post:
            return

        self.post_data = PostData(post)
        self.post_data.analyze()

    def process_demos(self):
        """Process demos."""
        for demo, input_demo_info in self.demos_to_process.items():
            if ZIP_RE.match(demo):
                demo_zip_info = DemoZipInfo(zip_path=demo, post_data=self.post_data,
                                            additional_info=input_demo_info)
                demo_zip_info.process_zip()
                if demo_zip_info.zip_process_failed:
                    continue

                lmp_to_info_map = demo_zip_info.lmp_to_info_map
                zip_path = demo
                primary_textfile_data = demo_zip_info.primary_textfile_data
                primary_textfile_date = demo_zip_info.primary_textfile_date
            elif is_demo_filename(demo):
                demo_date = self.additional_demo_info.get(demo, {}).get('recorded_date')
                if not demo_date:
                    raise RuntimeError(f'Non-zipped LMP {demo} requires date to be provided.')

                lmp_to_info_map = {demo: {'recorded_date': demo_date}, 'lmp_path': demo}
                zip_path = None
                primary_textfile_data = None
                primary_textfile_date = None
            else:
                raise RuntimeError(f'Demo {demo} provided that is an unsupported filetype.')

            for lmp, lmp_info in lmp_to_info_map.items():
                # Skip automatically created junk directories by Mac OS
                if os.path.basename(os.path.dirname(lmp)) == '__MACOSX':
                    continue

                lmp_info_player_list = lmp_info.get('player_list')
                if lmp_info_player_list:
                    extra_info_player_list = lmp_info_player_list
                else:
                    extra_info_player_list = self.additional_demo_info.get('player_list', [])

                demo_info_data = DemoInfoData(
                    recorded_date=lmp_info['recorded_date'],
                    txt_file_path=lmp_info.get('txt_file_path'),
                    txt_file_date=lmp_info.get('txt_file_date'),
                    player_list=extra_info_player_list,
                    extra_wad_guesses=self.additional_demo_info.get('extra_wad_guesses', [])
                )
                demo_info = DemoInfo(lmp_info['lmp_path'], demo_info_data, zip_path=zip_path,
                                     demo_id=lmp_info.get('demo_id'))
                demo_info.process_post_data(self.post_data)
                demo_info.process_textfile(default_textfile_data=primary_textfile_data,
                                           default_textfile_date=primary_textfile_date)
                demo_info.process_lmp()
                demo_info.process_additional_demo_info()
                if not CONFIG.skip_playback and demo_info.demo_process_failed:
                    self.process_failed = True
                    continue

                self.demo_infos.append(demo_info)


class DemoZipInfo:
    """Demo zip info object."""

    def __init__(self, zip_path, post_data=None, additional_info=None):
        """Initialize zip info object.

        :param zip_path: Path to the zip file for logging
        :param post_data: Data for post with the zip, if available
        :param demo_id: Demo ID if available, for DSDA update mode
        """
        # Inputs for demo upload
        self.zip_path = zip_path
        self.zip_filename = os.path.basename(zip_path)
        self.zip_extract_dir = os.path.join(os.path.dirname(zip_path),
                                            os.path.splitext(self.zip_filename)[0])
        self.post_data = post_data
        if additional_info:
            # In DSDA update mode, the demo ID may be passed to the demo processor in order to match
            # up to entries on DSDA in case of duplicate file names, etc.
            self._additional_info = {key: value for key, value in additional_info.items()
                                     if key in ['player_list', 'demo_id'] and value}
        else:
            self._additional_info = {}

        # Outputs after processing
        self.lmp_to_info_map = {}
        self.primary_textfile_data = None
        self.primary_textfile_date = None
        self.zip_process_failed = False

    def process_zip(self):
        """Process zip file."""
        try:
            zip_file = ZipFile(self.zip_path)
        except BadZipFile as bad_zip_err:
            LOGGER.error('Zip %s is a bad zip file, error message %s.', self.zip_path,
                         bad_zip_err)
            self.zip_process_failed = True
            return

        info_list = zip_file.infolist()
        main_lmp = None
        main_txt = None
        main_txt_date = None
        txt_file_info = {}
        zip_filename_no_ext = get_filename_no_ext(self.zip_filename).lower()
        for zip_file_info in info_list:
            zip_member_name = zip_file_info.filename
            zip_member_name_lower = zip_member_name.lower()
            if is_demo_filename(zip_member_name_lower):
                if get_filename_no_ext(zip_member_name_lower) == zip_filename_no_ext:
                    main_lmp = zip_member_name

                self.lmp_to_info_map[zip_member_name] = {
                    'recorded_date': datetime(*zip_file_info.date_time),
                    'lmp_path': os.path.join(self.zip_extract_dir, zip_member_name)
                }
            if zip_member_name_lower.endswith('.txt'):
                txt_date = datetime(*zip_file_info.date_time)
                if get_filename_no_ext(zip_member_name_lower) == zip_filename_no_ext:
                    main_txt = zip_member_name
                    main_txt_date = txt_date

                txt_file_info[zip_member_name] = {'recorded_date': txt_date}

        if not self.lmp_to_info_map:
            LOGGER.warning('No lmp files found in zip %s.', self.zip_path)
            self.zip_process_failed = True
            return
        if CONFIG.upload_type != 'dsda' and not txt_file_info:
            LOGGER.error('No txt files found in zip %s.', self.zip_path)
            self.zip_process_failed = True
            return

        if len(txt_file_info) == 1:
            main_txt, main_txt_info = get_single_key_value_dict(txt_file_info)
            main_txt_date = main_txt_info['recorded_date']
        if len(txt_file_info) > 1 and not main_txt:
            LOGGER.warning('Multiple txt files found in zip %s with no primary txt found.',
                           self.zip_path)
        if main_lmp:
            self.lmp_to_info_map = {main_lmp: self.lmp_to_info_map[main_lmp]}

        for lmp_file in self.lmp_to_info_map:
            for txt_file in txt_file_info:
                if get_filename_no_ext(lmp_file).lower() == get_filename_no_ext(txt_file).lower():
                    self.lmp_to_info_map[lmp_file].update(
                        {'txt_file_path': os.path.join(self.zip_extract_dir, txt_file),
                         'txt_file_date': txt_file_info[txt_file]['recorded_date']}
                    )

            self.lmp_to_info_map[lmp_file].update(self._additional_info)

        zip_file.extractall(path=self.zip_extract_dir,
                            members=list(self.lmp_to_info_map.keys()) + list(txt_file_info.keys()))

        if main_txt:
            self.primary_textfile_data = TextfileData(os.path.join(self.zip_extract_dir, main_txt))
            self.primary_textfile_data.analyze()
            self.primary_textfile_date = main_txt_date

    def clean(self):
        if os.path.exists(self.zip_extract_dir):
            shutil.rmtree(self.zip_extract_dir)


class DemoInfo:
    """Demo info object."""

    DEMO_DATE_CUTOFF = datetime.strptime(CONFIG.demo_date_cutoff, '%Y-%m-%dT%H:%M:%SZ')
    FUTURE_CUTOFF = datetime.today() + timedelta(days=1)

    def __init__(self, lmp_path, demo_info_data, zip_path=None, demo_id=None):
        """Initialize demo info object.

        :param lmp_path: Path to the LMP file
        :param demo_info_data: Demo info data
        :param zip_path: Path to the zip file for logging, if available
        :param demo_id: Demo ID if available, for DSDA update mode
        """
        # Inputs for demo upload
        self.zip_path = zip_path
        self.lmp_path = lmp_path
        # LMP metadata for logging and final JSON storage in case we are uploading a demo pack and
        # the metadata option is turned on. This is set to the filename only if there's a zip, since
        # the zip is the primary identifier for the upload in that case; otherwise, it is set to the
        # full LMP path.
        self.lmp_metadata = os.path.basename(lmp_path) if zip_path else lmp_path
        self.demo_info_data = demo_info_data
        # In DSDA update mode, the demo ID may be passed to the demo processor in order to match up
        # to entries on DSDA in case of duplicate file names, etc.
        self.demo_id = demo_id

        # Outputs after processing
        self.data_manager = DataManager()
        self.note_strings = set()
        self.demo_process_failed = False
        self.additional_upload_info = {}

        # Intermediate info
        self._post_info = {'wad_guesses': []}
        self._textfile_info = {'wad_guesses': []}
        self._lmp_info = {}

    def process_post_data(self, post_data=None):
        """Process post data, if available.

        :param post_data: Post data
        """
        if not post_data:
            return

        self._post_info['wad_guesses'] = post_data.raw_data['wad_links']
        post_data.populate_data_manager(self.data_manager)
        self.note_strings = self.note_strings.union(post_data.note_strings)

    def process_textfile(self, default_textfile_data=None, default_textfile_date=None):
        """Process demo textfile, if available.

        :param default_textfile_data: Default textfile info, if the lmp is part of a demo pack with
                                      no individual txt available for the lmp
        :param default_textfile_date: Default textfile date
        """
        # Set this in all cases, since it is the final fallback for date processing even if the lmp
        # txt itself has a date parsed, since that could be an invalid date.
        self._textfile_info['primary_txt_date'] = default_textfile_date
        if self.demo_info_data.txt_file_path:
            textfile_data = TextfileData(self.demo_info_data.txt_file_path)
            textfile_data.analyze()
        elif default_textfile_data:
            textfile_data = default_textfile_data
        else:
            return

        self._textfile_info['wad_guesses'] = textfile_data.raw_data['wad_strings']
        textfile_iwad = textfile_data.raw_data.get('iwad')
        if textfile_iwad:
            self._textfile_info['iwad'] = textfile_iwad

        textfile_data.populate_data_manager(self.data_manager)
        self.note_strings = self.note_strings.union(textfile_data.note_strings)

    def process_lmp(self):
        """Process demo lmp."""
        lmp_data = LMPData(self.lmp_path, textfile_iwad=self._textfile_info.get('iwad'))
        lmp_data.analyze()
        self._lmp_info = {
            'complevel': lmp_data.raw_data.get('complevel'),
            'iwad': lmp_data.raw_data.get('iwad', ''),
            'footer_files': lmp_data.raw_data['wad_strings'],
            'skill': lmp_data.raw_data.get('skill'),
            'num_players': lmp_data.raw_data.get('num_players'),
            'source_port': lmp_data.data.get('source_port')
        }
        wad_guesses = get_wad_guesses(
            self._post_info['wad_guesses'], self._textfile_info['wad_guesses'],
            lmp_data.raw_data['wad_strings'], self.demo_info_data.extra_wad_guesses,
            iwad=self._lmp_info.get('iwad', self._textfile_info.get('iwad', ''))
        )

        playback_data = PlaybackData(self.lmp_path, wad_guesses, demo_info=self._lmp_info)
        playback_data.analyze()
        if not CONFIG.skip_playback and playback_data.playback_failed:
            additional_zip_msg = f' from zip {self.zip_path}' if self.zip_path else ''
            LOGGER.info('Skipping lmp %s%s due to issues with playback.', self.lmp_metadata,
                        additional_zip_msg)
            self.demo_process_failed = True
            return False

        lmp_data.populate_data_manager(self.data_manager)
        playback_data.populate_data_manager(self.data_manager)
        self.note_strings = self.note_strings.union(lmp_data.note_strings,
                                                    playback_data.note_strings)
        self.additional_upload_info['stats'] = playback_data.raw_data.get('stats', {})

    def process_additional_demo_info(self):
        """Process additional demo info."""
        if self.demo_info_data.player_list:
            self.data_manager.insert('player_list', self.demo_info_data.player_list,
                                     DataManager.CERTAIN, source='extra_info')

        lmp_date = self.demo_info_data.recorded_date
        txt_date = (self.demo_info_data.txt_file_date if self.demo_info_data.txt_file_date
                    else self._textfile_info.get('primary_txt_date'))
        dsda_date = convert_datetime_to_dsda_date(lmp_date)
        if not DemoInfo.DEMO_DATE_CUTOFF < lmp_date < DemoInfo.FUTURE_CUTOFF:
            LOGGER.warning('Found possibly incorrect lmp date "%s", trying txt date.', dsda_date)
            if CONFIG.check_txt_date and txt_date:
                dsda_date = convert_datetime_to_dsda_date(txt_date)
                if not DemoInfo.DEMO_DATE_CUTOFF < dsda_date < DemoInfo.FUTURE_CUTOFF:
                    LOGGER.error('Found possibly incorrect txt date, setting to UNKNOWN: "%s".',
                                 dsda_date)
                    dsda_date = 'UNKNOWN'
            else:
                LOGGER.error('Check txt date is not set or no txt date found, setting to UNKNOWN.')
                dsda_date = 'UNKNOWN'

        self.data_manager.insert('recorded_at', dsda_date, DataManager.CERTAIN,
                                 source='extra_info')


@dataclass
class DemoInfoData:
    """DemoInfo data class."""
    recorded_date: datetime or None
    txt_file_path: str or None
    txt_file_date: datetime or None

    player_list: list = field(default_factory=list)
    extra_wad_guesses: list = field(default_factory=list)
