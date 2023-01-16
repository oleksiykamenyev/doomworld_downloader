"""
Demo JSON dumper.

This will take a demo info or set of demo info objects, which should already be pre-processed to be
as accurate as reasonably possible with just the automated process and generate a demo JSON or set
of JSONs. The created JSONs may be updates or uploads, and may be both demo packs and single demos.

It will also keep track of any JSONs that require attention, so that further on they can
be stored separately for manual inspection.
"""

import json
import logging
import os
import re

from collections import defaultdict

from .upload_config import CONFIG, NEEDS_ATTENTION_PLACEHOLDER, MAYBE_CHEATED_DIR, \
    VALID_DEMO_PACK_DIR, VALID_ISSUE_DIR, VALID_NO_ISSUE_DIR, VALID_TAGS_DIR
from .utils import checksum


LOGGER = logging.getLogger(__name__)


class DemoJsonDumper:
    """Demo JSON dumper."""

    def __init__(self):
        """Initialize demo JSON dumper."""
        self.demo_location_to_jsons_map = defaultdict(list)

    def add_demo_json(self, demo_info, dedupe=True):
        """Add demo JSON to dumper.

        :param demo_info: Demo info object
        :param dedupe: Dedupe demos as part of the same zip (needed for co-op demos)
        """
        demo_json = DemoJson.from_demo_info(demo_info)
        if demo_info.zip_path:
            demo_path = demo_info.zip_path
        else:
            demo_path = demo_info.lmp_path

        if dedupe:
            for demo_json_existing in self.demo_location_to_jsons_map[demo_path]:
                if demo_json_existing.compare_to(demo_json, exclude_keys=['recorded_at']):
                    # Prune LMP files based on their recorded date, since it makes sense to take
                    # the earliest date of the same time if we have multiple. In case recorded_date
                    # comes up as UNKNOWN for any of the lmps, it should be sorted after actual
                    # dates, so I think this should work.
                    existing_recorded_date = demo_json_existing.demo_dict['recorded_at']
                    new_recorded_date = demo_json.demo_dict['recorded_at']
                    if existing_recorded_date <= new_recorded_date:
                        LOGGER.warning('Pruning LMP file %s in favor of identical LMP %s.',
                                       demo_json_existing.demo_info.lmp_metadata,
                                       demo_json.demo_info.lmp_metadata)
                        return
                    else:
                        LOGGER.warning('Pruning LMP file %s in favor of identical LMP %s.',
                                       demo_json.demo_info.lmp_metadata,
                                       demo_json_existing.demo_info.lmp_metadata)
                        self.demo_location_to_jsons_map[demo_path].remove(demo_json_existing)

        self.demo_location_to_jsons_map[demo_path].append(demo_json)

    def dump_json_uploads(self):
        """Dump demo JSONs as uploads.

        :raises RuntimeError if there are no demos to dump.
        """
        if not self.demo_location_to_jsons_map:
            raise RuntimeError('No demo JSONs to dump!')

        # TODO: For demo pack compilation, we need to handle moving stuff to main and leftovers zips
        if CONFIG.upload_type == 'demo_pack':
            combined_demo_json_map = defaultdict(list)
            for _, demo_jsons in self.demo_location_to_jsons_map.items():
                combined_demo_json_map[CONFIG.demo_pack_name].extend(demo_jsons)

        for demo_location, demo_jsons in self.demo_location_to_jsons_map.items():
            file_entry = {'file': {'name': '/'.join(os.path.split(demo_location))}}
            if len(demo_jsons) > 1:
                demo_list_entry = {'demos': []}
                player_info = None
                maybe_cheated = False
                has_issue = False
                has_tags = False
                for demo_json in demo_jsons:
                    demo_dict = {key: value for key, value in demo_json.demo_dict.items()}
                    if CONFIG.add_lmp_metadata_for_demo_packs:
                        demo_dict['lmp_metadata'] = demo_json.demo_info.lmp_metadata
                    demo_list_entry['demos'].append(demo_dict)

                    cur_player_info = '_' + '_'.join(demo_dict['players'])
                    if player_info is None:
                        player_info = cur_player_info
                    else:
                        if player_info != cur_player_info:
                            player_info = ''

                    maybe_cheated = demo_json.maybe_cheated or maybe_cheated
                    has_issue = demo_json.has_issue or has_issue
                    has_tags = demo_json.has_tags or has_tags

                demo_list_entry.update(file_entry)
                final_demo_json = {'demo_pack': demo_list_entry}
            else:
                demo_list_entry = demo_jsons[0].demo_dict
                demo_list_entry.update(file_entry)
                final_demo_json = {'demo': demo_list_entry}
                player_info = '_' + '_'.join(demo_list_entry['players'])
                maybe_cheated = demo_jsons[0].maybe_cheated
                has_issue = demo_jsons[0].has_issue
                has_tags = demo_jsons[0].has_tags

            # Set JSON filename to filename_playername_checksum. If the demo is a demo pack
            demo_filename = os.path.splitext(os.path.basename(demo_location))[0]
            demo_checksum = f'_{checksum(demo_location)}' if os.path.exists(demo_location) else ''
            json_filename = f'{demo_filename}{player_info}{demo_checksum}.json'
            if maybe_cheated:
                json_path = self._set_up_demo_json_file(json_filename, MAYBE_CHEATED_DIR)
            elif has_issue:
                json_path = self._set_up_demo_json_file(json_filename, VALID_ISSUE_DIR)
            elif has_tags:
                json_path = self._set_up_demo_json_file(json_filename, VALID_TAGS_DIR)
            elif CONFIG.upload_type == 'demo_pack':
                json_path = self._set_up_demo_json_file(json_filename, VALID_DEMO_PACK_DIR)
            else:
                json_path = self._set_up_demo_json_file(json_filename, VALID_NO_ISSUE_DIR)

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


class DemoJson:
    """Demo JSON wrapper class."""
    SKILL_CATEGORY_NOTE_RE = re.compile('^Skill \d .+$')

    MISC_NOTES = ['Also Reality', 'Also Almost Reality', 'Uses turbo', 'Uses -longtics',
                  'Also Pacifist', 'Plays back with forced -complevel 5']
    MISC_CATEGORY_NOTES = [
        '-altdeath', '-coop_spawns', '-fast', '-nomonsters', '-respawn', '-solo-net'
    ]
    # We could have all of these keys consistent with the JSON keys, but I find the verbose
    # names are more useful for searching/debugging.
    KEY_TO_JSON_MAP = {'is_tas': 'tas', 'is_solo_net': 'solo_net', 'num_players': 'guys',
                       'source_port': 'engine', 'player_list': 'players'}
    # Note: the version key is required by the uploader spec but is currently always hardcoded
    # to 0.
    KEY_TO_DEFAULT_MAP = {'tas': False, 'solo_net': False, 'version': '0'}
    REQUIRED_KEYS = [
        'tas', 'solo_net', 'guys', 'version', 'wad', 'engine', 'time', 'level', 'levelstat',
        'category', 'secret_exit', 'recorded_at', 'players'
    ]
    OPTIONAL_KEYS = ['items', 'kills', 'secrets', 'tags', 'video_link', 'suspect', 'cheated']

    def __init__(self, demo_info=None, demo_dict=None):
        """Initialize demo JSON.

        :param demo_info: Demo info object
        :param demo_dict: Demo dictionary, will be copied into a class with unspecified fields set
                          to UNKNOWN
        """
        self.demo_info = demo_info
        self.input_demo_dict = demo_dict
        self.zip_msg = f' from zip {demo_info.zip_path}' if demo_info and demo_info.zip_path else ''
        self.demo_dict = {}
        self.has_issue = False
        self.has_tags = False
        self.maybe_cheated = False

    @classmethod
    def from_demo_info(cls, demo_info):
        """Initialize demo JSON from demo info.

        :param demo_info: Demo info object
        """
        demo_json = cls(demo_info=demo_info)
        demo_json._parse_demo_info()
        return demo_json

    @classmethod
    def from_demo_dict(cls, demo_dict):
        """Initialize demo JSON from demo dict.

        :param demo_dict: Demo dict
        """
        demo_json = cls(demo_dict=demo_dict)
        demo_json._parse_demo_dict()
        return demo_json

    def compare_to(self, other_demo_json, exclude_keys=()):
        """Compare to another demo JSON.

        Allows excluding keys for comparison.

        :param other_demo_json: Demo JSON to compare to
        :param exclude_keys: Keys to exclude comparison for
        """
        demo_json_compare = {key: value for key, value in self.demo_dict.items()
                             if key not in exclude_keys}
        other_demo_json_compare = {key: value for key, value in other_demo_json.demo_dict.items()
                                   if key not in exclude_keys}
        if demo_json_compare == other_demo_json_compare:
            return True

        return False

    def _parse_demo_dict(self):
        """Parse data from demo dict."""
        self.demo_dict.update(self.input_demo_dict)
        for key in self.REQUIRED_KEYS + self.OPTIONAL_KEYS:
            if key not in self.demo_dict:
                self.demo_dict[key] = NEEDS_ATTENTION_PLACEHOLDER

    def _parse_demo_info(self):
        """Parse data from demo info."""
        for evaluation in self.demo_info.data_manager:
            # Convert to JSON keys, default to value in the map.
            key_to_insert = self.KEY_TO_JSON_MAP.get(evaluation.key, evaluation.key)
            if evaluation.needs_attention:
                self._handle_needs_attention_entry(key_to_insert, evaluation)
            else:
                value = next(iter(evaluation.possible_values.keys()))
                if value == NEEDS_ATTENTION_PLACEHOLDER:
                    LOGGER.warning('LMP %s%s needs attention for following key: "%s".',
                                   self.demo_info.lmp_metadata, self.zip_msg, key_to_insert)
                    self._set_has_issue()

                self.demo_dict[key_to_insert] = value

        for key, default in self.KEY_TO_DEFAULT_MAP.items():
            if key not in self.demo_dict:
                self.demo_dict[key] = default

        for key in self.REQUIRED_KEYS:
            if key not in self.demo_dict:
                LOGGER.error('Key %s for LMP %s%s not found in final demo JSON.',
                             key, self.demo_info.lmp_metadata, self.zip_msg)
                self._set_has_issue()
                self.demo_dict[key] = ([NEEDS_ATTENTION_PLACEHOLDER]
                                       if key == 'players' else NEEDS_ATTENTION_PLACEHOLDER)

        # The players list is set to a tuple in the data manager so that it is a hashable type;
        # we need to convert it to a list to match the JSON spec.
        self.demo_dict['players'] = list(self.demo_dict['players'])

        if self.demo_dict.get('category') == 'Other':
            self._set_has_issue()

        self._construct_tags()

    def _handle_needs_attention_entry(self, key_to_insert, evaluation):
        """Handle entries that are marked as needing attention.

        :param key_to_insert: Key to insert into the demo JSON
        :param evaluation: Evaluation requiring attention
        """
        if key_to_insert == 'category':
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
                self._handle_inferred_category(playback_category)
                return

            no_kills = True
            no_secrets = True
            for stats in self.demo_info.additional_upload_info['stats']:
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
                self._handle_inferred_category(playback_category)
                return

            # If the playback showed UV Speed and textfile showed UV Max, and the map has no kills
            # or secrets, the two categories are identical so we take the playback value.
            if (no_secrets and no_kills and
                    playback_category == 'UV Speed' and textfile_category == 'UV Max'):
                self._handle_inferred_category(playback_category)
                return

        LOGGER.warning('LMP %s%s needs attention based on the following evaluation: "%s".',
                       self.demo_info.lmp_metadata, self.zip_msg, evaluation)
        # If there is a single possible evaluation, the data manager will indicate evaluation is
        # needed, but we should just add it to the JSON by default, in case the evaluation is
        # correct
        if len(evaluation.possible_values) == 1:
            self.demo_dict[key_to_insert] = next(iter(evaluation.possible_values.keys()))
        else:
            self.demo_dict[key_to_insert] = NEEDS_ATTENTION_PLACEHOLDER
        self._set_has_issue()

        # If we aren't sure this is a TAS (i.e., it's not in the TAS thread and not clearly marked
        # in the txt), the demo potentially needs investigation for cheating.
        if evaluation.key == 'is_tas':
            LOGGER.warning('LMP %s%s may need to be investigated for cheating.',
                           self.demo_info.lmp_metadata, self.zip_msg)
            self.maybe_cheated = True

    def _handle_inferred_category(self, category):
        """Handle entries with an inferred category.

        :param category: Category that was inferred for the demo.
        """
        LOGGER.info('Inferred %s category for zip file %s%s.', category,
                    self.demo_info.lmp_metadata, self.zip_msg)
        self.demo_dict['category'] = category

    def _construct_tags(self):
        """Construct tags array for demo JSON

        Does nothing if there are no note strings passed to the constructor.
        """
        if not self.demo_info.note_strings:
            return

        final_tag = self._construct_other_movie_tag()
        final_tag += self._construct_skill_tag()
        final_tag += self._construct_misc_tags()
        self.demo_dict['tags'] = [{'show': True, 'text': final_tag.rstrip('\n')}]
        self.has_tags = True

    def _construct_other_movie_tag(self):
        """Construct other movie tag."""
        other_movie = ''
        no_secret_maps = ''
        for note_string in self.demo_info.note_strings:
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

        :raises RuntimeError if there are mismatches between notes and other info in the class
        """
        category = self.demo_dict['category']
        incompatible = False
        additional_info = ''
        for note_string in self.demo_info.note_strings:
            if self.SKILL_CATEGORY_NOTE_RE.match('note_string'):
                # Override category in case the category is Other and there's a note string that
                # indicates the actual category (e.g., in cases of wrong skill level).
                if category != 'Other':
                    raise RuntimeError(
                        f'Other skill run found without Other category: '
                        f'{self.demo_info.lmp_metadata}{self.zip_msg}.'
                    )
                category = note_string
            if note_string == 'Incompatible':
                incompatible = True
                self.demo_dict['category'] = 'Other'
            if note_string in self.MISC_CATEGORY_NOTES:
                if not additional_info:
                    additional_info = ' with ' + note_string
                else:
                    additional_info += ' and ' + note_string

        if incompatible:
           category = 'Incompatible {}'.format(category)

        skill_tag = category + additional_info
        # If we didn't modify the tag at all from the original category, there was no new info
        # added, so we can skip adding this tag.
        if skill_tag and skill_tag != self.demo_dict['category']:
            return skill_tag + '\n'

        return ''

    def _construct_misc_tags(self):
        """Construct misc tags.

        All misc tags are just appended in alphabetical order and separated by newlines.
        """
        misc_tags = []
        for note_string in self.demo_info.note_strings:
            if note_string.startswith('Hexen class: '):
                misc_tags.append(note_string.split('Hexen class: ')[1])
            # Note: even though both Reality and Almost Reality are listed here, prior processing
            # should ensure that only one should be added to the notes.
            if (note_string in self.MISC_NOTES or
                    note_string.startswith('Recorded in skill ') or
                    note_string.startswith('Plays back with ')):
                misc_tags.append(note_string)
                if note_string == 'Uses turbo':
                    LOGGER.warning('LMP %s%s has issue due to unclear turbo usage.',
                                   self.demo_info.lmp_metadata, self.zip_msg)
                    self._set_has_issue()
                if note_string == 'Uses -longtics':
                    self.demo_dict['category'] = 'Other'
                    self._set_has_issue()

        return '\n'.join(sorted(misc_tags))

    def _set_has_issue(self):
        """Set has_issue flag if there is an issue with the JSON."""
        self.has_issue = True
