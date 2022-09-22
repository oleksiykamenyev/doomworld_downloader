"""
Demo JSON constructor.

This will take all of the data, which should already be pre-processed to be as accurate as
reasonably possible with just the automated process and generate the demo JSON. It will also keep
track of any JSONs that require attention, so that further on they can be stored separately for
manual inspection.
"""

import json
import logging
import os
import re

from collections import defaultdict

from .upload_config import CONFIG, NEEDS_ATTENTION_PLACEHOLDER
from .utils import freeze_obj


LOGGER = logging.getLogger(__name__)


class DemoJsonConstructor:
    """Construct demo JSON."""
    SKILL_CATEGORY_NOTE_RE = re.compile('^Skill \d .+$')

    MISC_NOTES = ['Also Reality', 'Also Almost Reality', 'Uses turbo', 'Uses longtics',
                  'Also Pacifist', 'Plays back with forced -complevel 5']
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
        'tas', 'solo_net', 'guys', 'version', 'wad', 'engine', 'time', 'level', 'levelstat',
        'category', 'secret_exit', 'recorded_at', 'players'
    ]

    MAYBE_CHEATED_DIR = 'maybe_cheated_jsons'
    VALID_DEMO_PACK_DIR = 'tmp_demo_pack_jsons'
    VALID_ISSUE_DIR = 'issue_jsons'
    VALID_NO_ISSUE_DIR = 'no_issue_jsons'
    VALID_TAGS_DIR = 'tags_jsons'

    def __init__(self, demo_location, demo_location_filename, demo_id):
        """Initialize demo JSON constructor.

        :param demo_location: Demo location (either zip file or lmp file directly)
        :param demo_location_filename: Location filename with no extension for constructing the JSON
                                       filename
        :param demo_id: Demo unique ID For demo storage
        """
        self.demo_location = demo_location
        self.demo_location_filename = demo_location_filename
        # Use "/" separator for path since the DSDA client prefers the paths provided this way.
        # If in demo pack mode, this may be incorrect as it could be an lmp alone; this is OK as a
        # separate utility will handle such files later.
        self.file_entry = {'file': {'name': '/'.join(os.path.split(demo_location))}}
        self.demo_jsons = {}
        self.has_issue = False
        self.has_tags = False
        self.maybe_cheated = False
        self.demo_id = demo_id

    def _set_has_issue(self):
        """Set has_issue flag if there is an issue with the JSON."""
        self.has_issue = True

    def parse_data_manager(self, data_manager, note_strings, lmp_file, extra_data={}):
        """Parse data from data manager.

        :param data_manager: Data manager object
        :param note_strings: List of note strings to parse into demo tags
        :param lmp_file: LMP file that is being parsed for
        :param extra_data: Extra data for verification
        :raises RuntimeError if there are required keys missing in the final demo JSON.
        """
        demo_json = {}
        for evaluation in data_manager:
            # Convert to JSON keys, default to value in the map.
            key_to_insert = self.KEY_TO_JSON_MAP.get(evaluation.key, evaluation.key)
            if evaluation.needs_attention:
                self._handle_needs_attention_entries(key_to_insert, evaluation, lmp_file, demo_json,
                                                     extra_data=extra_data)
            else:
                value = next(iter(evaluation.possible_values.keys()))
                if value == NEEDS_ATTENTION_PLACEHOLDER:
                    LOGGER.warning('LMP %s (location: %s) needs attention for following key: "%s".',
                                   lmp_file, self.demo_location, key_to_insert)
                    self._set_has_issue()

                demo_json[key_to_insert] = value

        for key, default in DemoJsonConstructor.KEY_TO_DEFAULT_MAP.items():
            if key not in demo_json:
                demo_json[key] = default

        for key in self.REQUIRED_KEYS:
            if key not in demo_json:
                LOGGER.error('Key %s not found in final demo JSON.', key)
                self._set_has_issue()
                demo_json[key] = ([NEEDS_ATTENTION_PLACEHOLDER]
                                  if key == 'players' else NEEDS_ATTENTION_PLACEHOLDER)

        # The players list is set to a tuple in the data manager so that it is a hashable type; we
        # need to convert it to a list to match the JSON spec.
        demo_json['players'] = list(demo_json['players'])

        if demo_json.get('category') == 'Other':
            self._set_has_issue()

        self._construct_tags(note_strings, lmp_file, demo_json)
        self.demo_jsons[lmp_file] = demo_json

    def dump_demo_jsons(self):
        """Parse data from data manager.

        :raises RuntimeError if there are no demos to dump.
        """
        if not self.demo_jsons:
            raise RuntimeError('No demo JSONs to dump!')

        # Before outputting, we need to dedupe the JSONs. This is important in cases where co-op
        # demos with multiple perspectives are present in the zip file, all of which would have the
        # same time and functionally be one demo. Alternatively, if someone were to include two
        # demos with the same exact time to the tic, there's no reason to display both.
        demo_jsons_prune = {}
        for lmp_file, json_dict in self.demo_jsons.items():
            # TODO: It might make sense to prune kills/items/secrets as well?
            # Prune the recording date from the deduping since, we don't really care about it
            demo_jsons_prune[lmp_file] = {key: value for key, value in json_dict.items()
                                          if key != 'recorded_at'}

        json_counts = defaultdict(list)
        for lmp_file, json_dict in demo_jsons_prune.items():
            json_counts[freeze_obj(json_dict)].append(lmp_file)

        for json_dict, lmp_files in json_counts.items():
            if len(lmp_files) > 1:
                # Prune LMP files based on their recorded date, since it makes sense to take the
                # earliest date of the same time if we have multiple. In case recorded_date comes
                # up as UNKNOWN for any of the lmps, it should be sorted after actual dates, so I
                # think this should work.
                lmp_files = sorted(lmp_files, key=lambda lmp: self.demo_jsons[lmp]['recorded_at'])
                lmp_file_kept = lmp_files[0]
                for lmp_file in lmp_files[1:]:
                    LOGGER.warning('Pruning LMP file %s in favor of matching category LMP %s.',
                                   lmp_file, lmp_file_kept)
                    self.demo_jsons.pop(lmp_file)

        demo_jsons = list(self.demo_jsons.values())
        if len(demo_jsons) > 1:
            demo_list_entry = {'demos': demo_jsons}
            demo_list_entry.update(self.file_entry)
            final_demo_json = {'demo_pack': demo_list_entry}
        else:
            demo_list_entry = demo_jsons[0]
            demo_list_entry.update(self.file_entry)
            final_demo_json = {'demo': demo_list_entry}

        # Set json filename to filename_playername_demoid
        player_info = '_'.join(demo_jsons[0]['players'])
        json_filename = f'{self.demo_location_filename}_{player_info}_{self.demo_id}.json'
        if self.maybe_cheated:
            json_path = self._set_up_demo_json_file(json_filename,
                                                    DemoJsonConstructor.MAYBE_CHEATED_DIR)
        elif self.has_issue:
            json_path = self._set_up_demo_json_file(json_filename,
                                                    DemoJsonConstructor.VALID_ISSUE_DIR)
        elif self.has_tags:
            json_path = self._set_up_demo_json_file(json_filename,
                                                    DemoJsonConstructor.VALID_TAGS_DIR)
        elif CONFIG.download_type == 'demo_pack':
            json_path = self._set_up_demo_json_file(json_filename,
                                                    DemoJsonConstructor.VALID_DEMO_PACK_DIR)
        else:
            json_path = self._set_up_demo_json_file(json_filename,
                                                    DemoJsonConstructor.VALID_NO_ISSUE_DIR)

        # If we are in demo pack mode, we should never overwrite any JSONs
        if CONFIG.download_type == 'demo_pack' and os.path.exists(json_path):
            raise RuntimeError(f'Demo pack JSON {json_path} will be ovewritten!')

        with open(json_path, 'w', encoding='utf-8') as out_stream:
            json.dump(final_demo_json, out_stream, indent=4, sort_keys=True)

    @staticmethod
    def _set_up_demo_json_file(json_filename, json_dir):
        """Set up demo JSON file creation.

        :param json_filename: JSON filename
        :param json_dir: Directory to create JSON under
        :return: Path to JSON file to create
        """
        json_dir = os.path.join(CONFIG.demo_download_directory, json_dir)
        os.makedirs(json_dir, exist_ok=True)
        json_path = os.path.join(json_dir, json_filename)
        return json_path

    def _handle_needs_attention_entries(self, key_to_insert, evaluation, lmp_file, demo_json,
                                        extra_data={}):
        """Handle entries that are marked as needing attention.

        :param key_to_insert: Key to insert into the demo JSON
        :param evaluation: Evaluation requiring attention
        :param lmp_file: LMP file that is being parsed for
        :param demo_json: JSON for the current demo
        :param extra_data: Extra data for verification
        """
        if evaluation.key == 'category':
            playback_category = None
            textfile_category = None
            for possible_value, sources in evaluation.possible_values.items():
                if 'playback' in sources:
                    playback_category = possible_value
                elif 'textfile' in sources:
                    textfile_category = possible_value

            # If the playback showed an all secrets category, it's guaranteed to be an accurate
            # category; it's safe to assume the textfile specified no secrets by error or because of
            # unavoidable secrets. Additionally, if the textfile indicated UV-Speed, but DSDA-Doom
            # confidently indicated Pacifist, we can assume Pacifist is correct.
            if ((playback_category == 'NoMo 100S' and textfile_category == 'NoMo') or
                    (playback_category == 'NM 100S' and textfile_category == 'NM Speed') or
                    (playback_category == 'Pacifist' and textfile_category == 'UV Speed')):
                LOGGER.info('Inferred %s category for zip file %s.',
                            playback_category, self.demo_location)
                demo_json[key_to_insert] = playback_category
                return

            no_kills = True
            no_secrets = True
            for stats in extra_data['stats']:
                if stats['kills'] != '0/0':
                    no_kills = False
                if stats['secrets'] != '0/0':
                    no_secrets = False

                if not no_kills and not no_secrets:
                    break

            # If the playback showed a no secrets category, and the map has no secrets, then we take
            # the playback value as the two categories are identical.
            if no_secrets and (
                    (playback_category == 'NoMo' and textfile_category == 'NoMo 100S') or
                    (playback_category == 'NM Speed' and textfile_category == 'NM 100S')
            ):
                LOGGER.info('Inferred %s category for zip file %s.',
                            playback_category, self.demo_location)
                demo_json[key_to_insert] = playback_category
                return

            # If the playback showed UV Speed and textfile showed UV Max, and the map has no kills
            # or secrets, the two categories are identical so we take the playback value.
            if (no_secrets and no_kills and
                    playback_category == 'UV Speed' and textfile_category == 'UV Max'):
                LOGGER.info('Inferred %s category for zip file %s.',
                            playback_category, self.demo_location)
                demo_json[key_to_insert] = playback_category
                return

        LOGGER.warning('LMP %s (location: %s) needs attention based on the following evaluation: '
                       '"%s".', lmp_file, self.demo_location, evaluation)
        # If there is a single possible evaluation, the data manager will indicate evaluation is
        # needed, but we should just add it to the JSON by default, in case the evaluation is
        # correct
        if len(evaluation.possible_values) == 1:
            demo_json[key_to_insert] = next(iter(evaluation.possible_values.keys()))
        else:
            demo_json[key_to_insert] = NEEDS_ATTENTION_PLACEHOLDER
        self._set_has_issue()

        # If we aren't sure this is a TAS (i.e., it's not in the TAS thread and not clearly marked
        # in the txt), the demo potentially needs investigation for cheating.
        if evaluation.key == 'is_tas':
            LOGGER.warning('LMP %s (location: %s) may need to be investigated for cheating.',
                           lmp_file, self.demo_location)
            self.maybe_cheated = True

    def _construct_tags(self, note_strings, lmp_file, demo_json):
        """Construct tags array for demo JSON

        Does nothing if there are no note strings passed to the constructor.

        :param note_strings: List of note strings to parse into demo tags
        :param lmp_file: LMP file that is being parsed for
        :param demo_json: JSON for the current demo
        """
        if not note_strings:
            return

        # This is inherently a bit wonky code, but I would prefer that all of the tags are
        # consistently placed in each entry, and there's no real way to do that without iterating
        # the note strings multiple times.
        final_tag = self._construct_other_movie_tag(note_strings)
        final_tag += self._construct_skill_tag(note_strings, lmp_file, demo_json)
        final_tag += self._construct_misc_tags(note_strings, lmp_file, demo_json)
        demo_json['tags'] = [{'show': True, 'text': final_tag.rstrip('\n')}]
        self.has_tags = True

    @staticmethod
    def _construct_other_movie_tag(note_strings):
        """Construct other movie tag.

        :param note_strings: List of note strings to parse into demo tags
        :return: Other movie tag.
        """
        other_movie = ''
        no_secret_maps = ''
        for note_string in note_strings:
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

    def _construct_skill_tag(self, note_strings, lmp_file, demo_json):
        """Construct skill tag.

        :param note_strings: List of note strings to parse into demo tags
        :param lmp_file: LMP file that is being parsed for
        :param demo_json: JSON for the current demo
        :return: Skill tag.
        :raises RuntimeError if there are mismatches between notes and other info in the class
        """
        category = demo_json['category']
        incompatible = False
        additional_info = ''
        for note_string in note_strings:
            if DemoJsonConstructor.SKILL_CATEGORY_NOTE_RE.match('note_string'):
                # Override category in case the category is Other and there's a note string that
                # indicates the actual category (e.g., in cases of wrong skill level).
                if category != 'Other':
                    raise RuntimeError(f'Other skill run found without Other category: {lmp_file} '
                                       f'(location: {self.demo_location}).')
                category = note_string
            if note_string == 'Incompatible':
                incompatible = True
                demo_json['category'] = 'Other'
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
        if skill_tag and skill_tag != demo_json['category']:
            return skill_tag + '\n'

        return ''

    def _construct_misc_tags(self, note_strings, lmp_file, demo_json):
        """Construct misc tags.

        All misc tags are just appended in alphabetical order and separated by newlines.

        :param note_strings: List of note strings to parse into demo tags
        :param lmp_file: LMP file that is being parsed for
        :param demo_json: JSON for the current demo
        :return: Misc tag.
        """
        misc_tags = []
        for note_string in note_strings:
            if note_string.startswith('Hexen class: '):
                misc_tags.append(note_string.split('Hexen class: ')[1])
            # Note: even though both Reality and Almost Reality are listed here, prior processing
            # should ensure that only one should be added to the notes.
            if (note_string in DemoJsonConstructor.MISC_NOTES or
                    note_string.startswith('Recorded in skill ') or
                    note_string.startswith('Plays back with ')):
                misc_tags.append(note_string)
                if note_string == 'Uses turbo':
                    LOGGER.warning('LMP %s (location: %s) has issue due to unclear turbo usage.',
                                   lmp_file, self.demo_location)
                    self._set_has_issue()
                if note_string == 'Uses longtics':
                    demo_json['category'] = 'Other'

        return '\n'.join(sorted(misc_tags))
