"""
Demo JSON constructor.

This will take all of the data, which should already be pre-processed to be as accurate as
reasonably possible with just the automated process and generate the demo JSON. It will also keep
track of any JSONs that require attention, so that further on they can be stored separately for
manual inspection.
"""

import logging
import os
import re

from .upload_config import NEEDS_ATTENTION_PLACEHOLDER


LOGGER = logging.getLogger(__name__)


class DemoJsonConstructor:
    """Construct demo JSON."""
    SKILL_CATEGORY_NOTE_RE = re.compile('^Skill \d .+$')

    MISC_NOTES = ['Also Reality', 'Also Almost Reality', 'Uses turbo', 'Uses longtics']
    MISC_CATEGORY_NOTES = [
        '-altdeath', '-coop_spawns', '-fast', '-nomonsters', '-respawn', '-solo-net'
    ]
    # We could have all of these keys consistent with the JSON keys, but I find the verbose names
    # are more useful for searching/debugging.
    KEY_TO_JSON_MAP = {'is_tas': 'tas', 'is_solo_net': 'solo_net', 'num_players': 'guys',
                       'source_port': 'engine', 'player_list': 'players'}
    # Note: the version key is required by the uploader spec but is currently always hardcoded to 0.
    KEY_TO_DEFAULT_MAP = {'tas': False, 'solo_net': False, 'version': '0'}
    REQUIRED_KEYS = [
        'tas', 'solo_net', 'guys', 'version', 'wad', 'file', 'engine', 'time', 'level', 'levelstat',
        'category', 'secret_exit', 'recorded_at', 'players'
    ]

    def __init__(self, data_manager, note_strings, zip_file):
        """Initialized demo JSON constructor."""
        self.data_manager = data_manager
        self.note_strings = note_strings
        self.zip_file = zip_file
        # Use "/" separator for path since the DSDA client prefers it
        self.demo_json = {'file': {'name': '/'.join(os.path.split(zip_file))}}
        self.has_issue = False

        # TODO: This should probably be a public method called externally
        self._parse_data_manager()

    def _set_has_issue(self):
        """Set has_issue flag if there is an issue with the JSON."""
        self.has_issue = True

    def _parse_data_manager(self):
        """Parse data from data manager.

        :raises RuntimeError if there are required keys missing in the final demo JSON.
        """
        for evaluation in self.data_manager:
            # Convert to JSON keys, default to value in the map.
            key_to_insert = self.KEY_TO_JSON_MAP.get(evaluation.key, evaluation.key)
            if evaluation.needs_attention:
                self._handle_needs_attention_entries(key_to_insert, evaluation)
            else:
                value = next(iter(evaluation.possible_values.keys()))
                if value == NEEDS_ATTENTION_PLACEHOLDER:
                    LOGGER.warning('Zip file %s needs attention for following key: "%s". ',
                                   self.zip_file, key_to_insert)
                    self._set_has_issue()

                self.demo_json[key_to_insert] = value

        for key, default in DemoJsonConstructor.KEY_TO_DEFAULT_MAP.items():
            if key not in self.demo_json:
                self.demo_json[key] = default

        # The players list is set to a tuple in the data manager so that it is a hashable type; we
        # need to convert it to a list to match the JSON spec.
        self.demo_json['players'] = list(self.demo_json['players'])
        for key in self.REQUIRED_KEYS:
            if key not in self.demo_json:
                LOGGER.error('Key %s not found in final demo JSON.', key)
                self._set_has_issue()
                self.demo_json[key] = NEEDS_ATTENTION_PLACEHOLDER

        # TODO: Anything with tags should be placed in a separate dir for manual inspection
        self._construct_tags()
        # TODO: Should probably format it this way by default
        # Correct format for demo JSON
        self.demo_json = {'demo': self.demo_json}
        # TODO: If category is Other should just mark as has issue

    def _handle_needs_attention_entries(self, key_to_insert, evaluation):
        """Handle entries that are marked as needing attention.

        :param key_to_insert: Key to insert into the demo JSON
        :param evaluation: Evaluation requiring attention
        """
        if evaluation.key == 'category':
            playback_category = None
            textfile_category = None
            for possible_value, sources in evaluation.possible_values.items():
                if 'playback' in sources:
                    playback_category = possible_value
                elif 'textfile' in sources:
                    textfile_category = possible_value

            # If the playback showed an all secrets category, it's guaranteed to be an
            # accurate category; it's safe to assume the textfile specified no secrets by
            # error or because of unavoidable secrets.
            if ((playback_category == 'NoMo 100S' and textfile_category == 'NoMo') or
                    (playback_category == 'NM 100S' and textfile_category == 'NM Speed')):
                LOGGER.info('Inferred %s category for zip file %s.',
                            playback_category, self.zip_file)
                self.demo_json[key_to_insert] = playback_category
                return

        LOGGER.warning('Zip file %s needs attention based on the following '
                       'evaluation: "%s".', self.zip_file, evaluation)
        # If there is a single possible evaluation, the data manager will indicate evaluation is
        # needed, but we should just add it to the JSON by default, in case the evaluation is
        # correct
        if len(evaluation.possible_values) == 1:
            self.demo_json[key_to_insert] = next(iter(evaluation.possible_values.keys()))
        else:
            self.demo_json[key_to_insert] = NEEDS_ATTENTION_PLACEHOLDER
        self._set_has_issue()

    def _construct_tags(self):
        """Construct tags array for demo JSON

        Does nothing if there are no note strings passed to the constructor.
        """
        if not self.note_strings:
            return

        # This is inherently a bit wonky code, but I would prefer that all of the tags are
        # consistently placed in each entry, and there's no real way to do that without iterating
        # the note strings multiple times.
        final_tag = self._construct_other_movie_tag()
        final_tag += self._construct_skill_tag()
        final_tag += self._construct_misc_tags()
        self.demo_json['tags'] = [{'show': True, 'text': final_tag.rstrip('\n')}]

    def _construct_other_movie_tag(self):
        """Construct other movie tag.

        :return: Other movie tag.
        """
        other_movie = ''
        no_secret_maps = ''
        for note_string in self.note_strings:
            if note_string.startswith('Other Movie '):
                # We don't actually need the "Other Movie" part, as that info is present in the
                # level info; it is included so this note is more easy to detect in this function.
                other_movie = note_string.split('Other Movie ')[1]
            if note_string == 'Does not visit secret maps.':
                no_secret_maps = note_string

        if other_movie:
            if no_secret_maps:
                return other_movie + '. ' + no_secret_maps + '\n'

            return other_movie + '\n'

        return ''

    def _construct_skill_tag(self):
        """Construct skill tag.

        :return: Skill tag.
        :raises RuntimeError if there are mismatches between notes and other info in the class
        """
        category = self.demo_json['category']
        incompatible = False
        additional_info = ''
        for note_string in self.note_strings:
            if DemoJsonConstructor.SKILL_CATEGORY_NOTE_RE.match('note_string'):
                # Override category in case the category is Other and there's a note string that
                # indicates the actual category (e.g., in cases of wrong skill level).
                if category != 'Other':
                    raise RuntimeError('Other skill run found without Other category: {}.'.format(
                        self.zip_file
                    ))
                category = note_string
            if note_string == 'Incompatible':
                incompatible = True
                self.demo_json['category'] = 'Other'
            if note_string in DemoJsonConstructor.MISC_CATEGORY_NOTES:
                if not additional_info:
                    additional_info = ' with ' + note_string
                else:
                    additional_info += ' and ' + note_string

        if incompatible:
           category = 'Incompatible {}'.format(category)

        skill_tag = category + additional_info
        # If we didn't modify the tag at all from the original category, there was no new info
        # added, so we can skip adding this tag.
        if skill_tag and skill_tag != self.demo_json['category']:
            return skill_tag + '\n'

        return ''

    def _construct_misc_tags(self):
        """Construct misc tags.

        All misc tags are just appended in alphabetical order and separated by newlines.

        :return: Misc tag.
        """
        misc_tags = []
        for note_string in self.note_strings:
            if note_string.startswith('Hexen class: '):
                misc_tags.append(note_string.split('Hexen class: ')[1])
            # Note: even though both Reality and Almost Reality are listed here, prior processing
            # should ensure that only one should be added to the notes.
            if (note_string in DemoJsonConstructor.MISC_NOTES or
                    note_string.startswith('Recorded in skill ')):
                misc_tags.append(note_string)
                if note_string == 'Uses turbo':
                    LOGGER.warning('Zip file %s due to unclear turbo usage.', self.zip_file)
                    self._set_has_issue()
                if note_string == 'Uses longtics':
                    self.demo_json['category'] = 'Other'

        return '\n'.join(sorted(misc_tags))
