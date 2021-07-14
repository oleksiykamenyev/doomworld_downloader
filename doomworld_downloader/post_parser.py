"""
Parse data out of Doomworld demo post.
"""
# TODO: All of the parser classes can have stuff abstracted out.

import logging

from .data_manager import DataManager
from .upload_config import THREAD_MAP_KEYED_ON_ID


LOGGER = logging.getLogger(__name__)


class PostData:
    """Store all uploader-relevant data for a Doomworld post.

    This includes parsing the post based on the thread it was taken from.
    """

    CERTAIN_KEYS = ['is_tas', 'player_list']
    POSSIBLE_KEYS = ['is_solo_net', 'category', 'source_port', 'video_link']

    def __init__(self, post):
        """Initialize post data class.

        :param post: Post object.
        """
        self.data = {}
        self.note_strings = set()
        self.raw_data = {'wad_links': [], 'video_links': []}
        self.post = post

    def analyze(self):
        self._parse_post()

    def populate_data_manager(self, data_manager):
        # The following data points are set for the playback parser:
        #   - Certain: levelstat, time, level, kills, items, secrets, wad
        #   - Somewhat certain: category
        for key, value in self.data.items():
            if key in PostData.CERTAIN_KEYS:
                data_manager.insert(key, value, DataManager.CERTAIN, source='post')
            elif key in PostData.POSSIBLE_KEYS:
                data_manager.insert(key, value, DataManager.POSSIBLE, source='post')
            else:
                raise ValueError('Unrecognized key found in data dictionary: {}.'.format(key))

    def _parse_post(self,):
        """Parse post object."""
        # This is set to a tuple so that it is hashable for the data manager.
        self.data['player_list'] = (self.post.author_name,)
        for link in self.post.links:
            parsed = self._parse_youtube_url(link)
            if not parsed:
                if 'dsdarchive.com/wads' in link or 'doomworld.com/idgames' in link:
                    self.raw_data['wad_links'].append(link)
                else:
                    # TODO: Add more wad sites?
                    # TODO: Alert on Dropbox/Drive/other file hosting sites?
                    continue
        for embed in self.post.embeds:
            self._parse_youtube_url(embed)

        # Assume if there's a single video on the post, that it's the video for the demo attachment.
        if len(self.raw_data['video_links']) == 1:
            self.data['video_link'] = self.raw_data['video_links'][0]

        parent_thread_id = str(self.post.parent.id)
        if parent_thread_id in THREAD_MAP_KEYED_ON_ID:
            thread_info = THREAD_MAP_KEYED_ON_ID[parent_thread_id].get('additional_info', {})
            if thread_info.get('wad'):
                # If the thread has a single WAD attached to it, this is the priority choice for
                # playback testing
                self.raw_data['wad_links'].insert(0, thread_info['wad'])
            elif thread_info.get('wads'):
                self.raw_data['wad_links'].extend(thread_info['wads'])

            if thread_info.get('solo-net'):
                self.data['is_solo_net'] = True
            if thread_info.get('tas_only'):
                self.data['is_tas'] = True
            if thread_info.get('category'):
                self.data['category'] = thread_info['category']
            if thread_info.get('source_port'):
                self.data['source_port'] = thread_info['source_port']

            if thread_info.get('nomonsters'):
                self.raw_data['nomonsters'] = True
            if thread_info.get('note'):
                self.raw_data['note'] = thread_info['note']

    def _parse_youtube_url(self, link):
        """Parse YouTube URLs from a link.

        Return whether or not the URL is parsed so that if the URL wasn't a YT URL, it can be
        checked against other websites of interet.

        :param link: Link
        :return: Whether the link was parsed as a YouTube URL
        """
        parsed = False
        if 'youtube.com/' in link:
            self.raw_data['video_links'].append(link.split('watch?v=')[1])
            parsed = True
        elif 'youtu.be/' in link:
            self.raw_data['video_links'].append(link.split('youtu.be/')[1])
            parsed = True

        return parsed
