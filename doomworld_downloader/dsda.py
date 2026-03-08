"""
Various utilities to parse DSDA pages
"""

import logging
import os
import re
import string

from collections import defaultdict
from dataclasses import dataclass

import requests

from urllib.parse import urlparse, urlunparse, urljoin

from doomworld_downloader.upload_config import CONFIG
from doomworld_downloader.utils import get_download_filename, download_response, get_page


LOGGER = logging.getLogger(__name__)

DSDA_GROUP_PAGE_REGEXES = [
    re.compile(r'^Map Select$'), re.compile(r'^Episode \d+ ILs$'), re.compile(r'^Movies$')
]

DSDA_START = 'https://www.dsdarchive.com'
DSDA_PLAYER_URL = f'{DSDA_START}/players'
DSDA_PLAYER_API_URL = f'{DSDA_START}/api/players'
DSDA_WAD_URL = f'{DSDA_START}/wads'


@dataclass
class DSDACell:
    """DSDA cell data class."""
    # Cell text
    text: str
    # Cell links, as a dictionary mapping the link text or info to the link
    links: dict
    # Cell labels (i.e., record, dubious, etc.)
    labels: list


def verify_dsda_url(url, page_types=None):
    """Verify that given DSDA URL is actually a URL for the DSDA.

    Supported page type options:
      - wad: check if it is a WAD URL (note: only default view).
      - player: check if it is a player URL (note: excluding stats view).

    :param url: URL
    :param page_types: Page types to check for
    :raises ValueError if provided URL isn't a DSDA URL of the requested type.
    :return Actual type of URL found
    """
    url_parsed = urlparse(url)
    if not url_parsed.netloc.endswith('dsdarchive.com'):
        raise ValueError(f'URL "{url}" is not a DSDA URL.')

    if page_types:
        path_split = url_parsed.path.strip('/').split('/')
        path_split_len = len(path_split)
        actual_type = 'UNKNOWN'
        if path_split_len >= 2:
            if path_split[0] == 'wads':
                if path_split_len > 2:
                    raise ValueError(f'Only WAD URLs in default view supported, got "{url}".')
                actual_type = 'wad'
            elif path_split[0] == 'players':
                if path_split_len > 2 and path_split[2] not in ['history', 'record_view']:
                    raise ValueError(f'Unsupported player URL view for URL "{url}".')
                actual_type = 'player'

        if actual_type not in page_types:
            raise ValueError(
                f'Incorrect DSDA URL {url}; wanted one of {page_types}, got {actual_type}.'
            )

        return actual_type


def fix_dsda_link(link_url):
    """Fix link on DSDA to be full URL path.

    :param link_url: DSDA link URL
    :return: Fixed DSDA link URL
    """
    if link_url.startswith('/'):
        link_url = DSDA_START + link_url
    return link_url


def parse_dsda_cell(cell):
    """Parse single cell on DSDA page.

    :param cell: DSDA cell element
    :return: DSDA cell object
    """
    cell_text = cell.getText().strip()
    cell_links = cell.find_all('a')
    links = {}
    if cell_links:
        for cell_link in cell_links:
            link_text = cell_link.getText().strip()
            if not link_text:
                link_span = cell_link.find('span')
                link_text = link_span.get('aria-label').lower()

            if not link_text:
                raise ValueError(f'Cell {cell} has link with unclear info.')
            link_url = fix_dsda_link(cell_link['href'])
            links[link_text] = link_url

    # Span element info is kept track of for dubious/WR/etc. notes.
    cell_spans = cell.find_all('span')
    labels = [span.get('aria-label') for span in cell_spans] if cell_spans else []
    return DSDACell(text=cell_text, links=links, labels=labels)


def parse_page_top(page_soup):
    """Parse top of a demo page on DSDA.

    The following info is parsed:
      - WAD/player name
      - WAD link
      - WAD author
      - New WAD link for deprecated pages
      - Total demo count/total time

    :param page_soup: DSDA page soup
    :return: Parsed top of a demo pag
    """
    divs = page_soup.findAll('div', {'class': 'center-text'})
    parsed_headers = {}
    for div in divs:
        # All DSDA demo pages have a single empty header for some reason.
        div_text = div.getText().strip()
        if not div_text:
            continue

        page_title = div.find('h1')
        title_link = page_title.find('a')
        # WAD pages always have the primary header link somewhere, so we can assume if there's a
        # link, it must be a WAD page, otherwise, it is a player page.
        if title_link:
            parsed_headers['wad_name'] = title_link.getText().strip()
            parsed_headers['wad_url'] = title_link['href']
            parsed_headers['wad_author'] = page_title.find('small').getText().strip()
        else:
            parsed_headers['player_name'] = page_title.getText().strip()

        # WADs with newer versions will have an alert div at the top of the page linking to the new
        # version of the WAD.
        deprecated_wad_info = div.find('div', {'class': 'alert-danger'})
        if deprecated_wad_info:
            parsed_headers['new_wad_url'] = deprecated_wad_info.find('a')['href']

        # Sample text:
        #   2 demos, 3:27.91 | Table View | Leaderboard | Stats | Map Select
        table_info = div.find('p', {'class': 'p-short one-line'})
        stats = table_info.getText().split('|')[0].split(',')
        parsed_headers['demo_count'] = int(stats[0].split(' ')[0].strip())
        parsed_headers['demo_time'] = stats[1].strip()

    return parsed_headers


def extract_demos_from_demo_table(dsda_url, soup=None):
    """Parse demo table from DSDA page.

    :param dsda_url: DSDA URL
    :param soup: Full DSDA page parsed into a BeautifulSoup object, if the page was already parsed by the calling
                 function.
    :return: Demos JSON of demos on the page.
    """
    if not soup:
        verify_dsda_url(dsda_url, page_types=['player', 'wad'])
        soup = get_page(dsda_url)

    demo_table = soup.find('table')
    table_header = demo_table.find('thead')
    header_cols = table_header.find('tr').find_all('th')
    col_names = []
    for col in header_cols:
        header_cell = parse_dsda_cell(col)
        # Handle columns that are denoted by an icon (e.g., video icon)
        if header_cell.text:
            col_names.append(header_cell.text)
        elif header_cell.labels:
            col_names.append(header_cell.labels[0])
        else:
            raise ValueError(f'Unclear header cell {col} found on page {dsda_url}.')
    rows = demo_table.find('tbody').find_all('tr')
    col_len = len(col_names)
    demo_list = []
    for row in rows:
        if not row.getText():
            continue

        cols = row.find_all('td')
        # Tag columns are placed in a row after the previous demo; in this case, we need to modify
        # the previous element in the list.
        tag_cols = [col for col in cols if 'tag-text' in col.get('class', '')]
        if tag_cols:
            demo_list[-1]['Tags'] = [parse_dsda_cell(col) for col in tag_cols]
        else:
            # Some columns will apply to a number of demos; in these cases, the row will only have
            # a subset of the columns, so we place those at the end of the row, and fill the
            # beginning with the previous row's values up to the number of columns.
            cur_row_values = [parse_dsda_cell(col) for col in cols]
            if demo_list:
                shared_values = list(demo_list[-1].values())[:col_len - len(cur_row_values)]
                row_values = shared_values + cur_row_values
            else:
                row_values = cur_row_values
            demo_list.append(dict(zip(col_names, row_values)))

    return demo_list


def parse_dsda_demo_page(dsda_url, parse_all_pages=False):
    """Parse DSDA page.

    :param dsda_url: DSDA URL
    :param parse_all_pages: Flag indicating to parse all pages in cases of DSDA pages that are paginated
    :return: Parse DSDA page, including headers and demos JSON
    """
    verify_dsda_url(dsda_url, page_types=['player', 'wad'])
    soup = get_page(dsda_url)
    parsed_demo_page = {'headers': parse_page_top(soup)}
    page_short_name = get_wad_or_player_name_from_dsda_url(dsda_url)
    parsed_demo_page['headers']['short_name'] = page_short_name

    dsda_map_pages_to_urls = {}
    button_groups = soup.find_all('div', class_='btn-group')
    for button_group in button_groups:
        button = button_group.find('button')
        if button and button.text.strip() == 'Map Select':
            for page_link in button_group.find_all('a'):
                page_name = page_link.text
                skip_page = False
                for group_page_regex in DSDA_GROUP_PAGE_REGEXES:
                    if group_page_regex.match(page_name):
                        skip_page = True
                        break

                if skip_page:
                    continue

                dsda_map_pages_to_urls[page_name] = urljoin(dsda_url, page_link['href'])

    demo_list = extract_demos_from_demo_table(dsda_url, soup=soup)
    parsed_levels = set([demo['Level'].text for demo in demo_list])
    parsed_level_count = len(parsed_levels)
    if parse_all_pages and parsed_level_count < len(dsda_map_pages_to_urls):
        LOGGER.info('Paginated DSDA WAD detected.')
        parsed_level = next(iter(parsed_levels))
        LOGGER.info('Level %s already parsed.', parsed_level)

        for page_name, additional_url in dsda_map_pages_to_urls.items():
            if page_name != parsed_level:
                demo_list.extend(extract_demos_from_demo_table(additional_url))

    parsed_demo_page['demo_list'] = demo_list
    return parsed_demo_page


def parse_dsda_demo_page_with_annotation(dsda_url, parse_all_pages=False, grant_index_from_cheated_demos=False):
    """Parse DSDA page with code-created annotation.

    Demos will be annotated as records, basic checks will be performed, record index calculated, etc.

    :param dsda_url: DSDA URL
    :param parse_all_pages: Flag indicating to parse all pages in cases of DSDA pages that are paginated
    :param grant_index_from_cheated_demos: Flag indicating whether to grant demos index from cheated and dubious demos
    :return: Parse DSDA page, including headers and demos JSON with additional annotation.
    """
    parsed_demo_page = parse_dsda_demo_page(dsda_url, parse_all_pages=parse_all_pages)
    demo_list = parsed_demo_page['demo_list']
    unchanged_demos = []
    for entry in list(demo_list):
        time_str_split = entry['Time'].text.split(':')
        if len(time_str_split) == 3:
            hours, mins, secs = time_str_split
            hours = int(hours)
        else:
            hours = 0
            mins, secs = time_str_split

        mins = int(mins)
        if '.' in secs:
            secs, millis = secs.split('.')
        else:
            millis = '0'

        secs = int(secs)
        time_in_seconds = hours * 3600 + mins * 60 + secs
        entry['time_in_seconds'] = float(f'{time_in_seconds}.{millis}')

        entry_notes = entry['Note'].text.split()
        num_players = 1
        if '2P' in entry_notes:
            num_players = 2
        if '3P' in entry_notes:
            num_players = 3
        if '4P' in entry_notes:
            num_players = 4

        entry['num_players'] = num_players

        if 'SN' in entry_notes or 'TAS' in entry_notes:
            entry['record_index'] = 0
            entry['is_record'] = False
            unchanged_demos.append(entry)
            demo_list.remove(entry)

        # Default values.
        entry['is_record'] = False
        entry['cheated_record'] = False
        entry['record_index'] = 0
        entry['potential_record_index'] = 0
        entry['actual_record'] = None
        entry['supersedes'] = None
        entry['faster_cheated_record'] = None

    category_level_num_players_pairs = list(set([(entry['Category'].text, entry['Level'].text, entry['num_players'])
                                                 for entry in demo_list]))
    split_lists = []
    for category, level, num_players in category_level_num_players_pairs:
        split_lists.append(
            [entry for entry in demo_list
             if entry['Category'].text == category and entry['Level'].text == level and
             entry['num_players'] == num_players]
        )

    final_demo_list = []
    record_references = defaultdict(dict)
    for split_list in split_lists:
        if split_list:
            # For Other/Other Movie demos, no annotation can be performed.
            if split_list[0]['Category'].text == 'Other' or split_list[0]['Level'].text == 'Other Movie':
                final_demo_list.extend(split_list)
            else:
                split_list_sorted = sorted(split_list, key=lambda entry_key: entry_key['time_in_seconds'])
                list_index_of_record = 0
                list_index_of_cheated_record = 0
                found_record = False
                found_cheated_record = False
                top_record_index = 0
                top_potential_record_index = 0
                for idx, entry in enumerate(split_list_sorted):
                    labels_joined = '\n'.join(entry['Note'].labels)
                    if 'Dubious' in labels_joined or 'Cheated' in labels_joined:
                        if not found_record and not found_cheated_record:
                            list_index_of_cheated_record = idx
                            found_cheated_record = True
                        else:
                            if grant_index_from_cheated_demos:
                                top_record_index += 1
                                top_potential_record_index += 1
                    else:
                        if not found_record:
                            list_index_of_record = idx
                            found_record = True
                            if found_cheated_record:
                                top_potential_record_index += 1
                        else:
                            top_record_index += 1
                            top_potential_record_index += 1

                # It's possible we won't find any record, e.g., if every demo for a category/level is cheated or
                # dubious.
                if found_record:
                    if found_cheated_record:
                        split_list_sorted[list_index_of_record]['faster_cheated_record'] = split_list_sorted[
                            list_index_of_cheated_record
                        ]

                    split_list_sorted[list_index_of_record]['is_record'] = True
                    split_list_sorted[list_index_of_record]['record_index'] = top_record_index

                    record_level = split_list_sorted[list_index_of_record]['Level'].text
                    record_category = split_list_sorted[list_index_of_record]['Category'].text
                    record_num_players = split_list_sorted[list_index_of_record]['num_players']
                    if record_category not in record_references[record_level]:
                        record_references[record_level][record_category] = defaultdict(dict)
                    if record_num_players not in record_references[record_level][record_category]:
                        record_references[record_level][record_category][record_num_players] = defaultdict(dict)

                    record_references[record_level][record_category][record_num_players] = split_list_sorted[
                        list_index_of_record
                    ]
                if found_cheated_record:
                    split_list_sorted[list_index_of_cheated_record]['cheated_record'] = True
                    split_list_sorted[list_index_of_cheated_record]['potential_record_index'] = top_potential_record_index

                final_demo_list.extend(split_list_sorted)

    for level in record_references:
        for possible_num_players in range(1, 5):
            # Handle Pacifist -> UV-Speed crosslist
            possible_pacifist_record = record_references[level].get('Pacifist', {}).get(possible_num_players, {})
            if possible_pacifist_record:
                possible_speed_record = record_references[level].get('UV Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    if possible_pacifist_record['time_in_seconds'] < possible_speed_record['time_in_seconds']:
                        # Add 1 because this demo should take on all of the record index of anything it supersedes +
                        # the demo it beats.
                        possible_pacifist_record['record_index'] += possible_speed_record['record_index'] + 1
                        possible_pacifist_record['supersedes'] = possible_speed_record
                        possible_speed_record['is_record'] = False
                        possible_speed_record['record_index'] = 0
                        possible_speed_record['actual_record'] = possible_pacifist_record

                possible_speed_record = record_references[level].get('SM Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    if possible_pacifist_record['time_in_seconds'] < possible_speed_record['time_in_seconds']:
                        # Add 1 because this demo should take on all of the record index of anything it supersedes +
                        # the demo it beats.
                        possible_pacifist_record['record_index'] += possible_speed_record['record_index'] + 1
                        possible_pacifist_record['supersedes'] = possible_speed_record
                        possible_speed_record['is_record'] = False
                        possible_speed_record['record_index'] = 0
                        possible_speed_record['actual_record'] = possible_pacifist_record

                possible_speed_record = record_references[level].get('Sk4 Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    if possible_pacifist_record['time_in_seconds'] < possible_speed_record['time_in_seconds']:
                        # Add 1 because this demo should take on all of the record index of anything it supersedes +
                        # the demo it beats.
                        possible_pacifist_record['record_index'] += possible_speed_record['record_index'] + 1
                        possible_pacifist_record['supersedes'] = possible_speed_record
                        possible_speed_record['is_record'] = False
                        possible_speed_record['record_index'] = 0
                        possible_speed_record['actual_record'] = possible_pacifist_record

            # Handle Stroller -> Pacifist crosslist
            possible_stroller_record = record_references[level].get('Stroller', {}).get(possible_num_players, {})
            if possible_stroller_record:
                if possible_pacifist_record:
                    if possible_stroller_record['time_in_seconds'] < possible_pacifist_record['time_in_seconds']:
                        # Add 1 because this demo should take on all of the record index of anything it supersedes +
                        # the demo it beats.
                        possible_stroller_record['record_index'] += possible_pacifist_record['record_index'] + 1
                        possible_stroller_record['supersedes'] = possible_pacifist_record
                        possible_pacifist_record['is_record'] = False
                        possible_pacifist_record['record_index'] = 0
                        possible_pacifist_record['actual_record'] = possible_stroller_record
                        if possible_pacifist_record['supersedes']:
                            possible_pacifist_record['supersedes']['actual_record'] = possible_stroller_record

            # Handle UV-Max -> UV-Speed potential crosslist
            possible_uv_max_record = record_references[level].get('UV Max', {}).get(possible_num_players, {})
            if possible_uv_max_record:
                possible_speed_record = record_references[level].get('UV Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    max_time_in_seconds = possible_uv_max_record['time_in_seconds']
                    if max_time_in_seconds < possible_speed_record['time_in_seconds']:
                        possible_pacifist_record = possible_speed_record.get('actual_record')
                        if (not possible_pacifist_record or (
                                possible_pacifist_record and
                                (max_time_in_seconds < possible_pacifist_record['time_in_seconds'])
                        )):
                            LOGGER.warning('Potential faster UV Max record found than UV Speed!')
                            LOGGER.warning('WAD: %s, level: %s.', dsda_url, level)

            possible_sm_max_record = record_references[level].get('SM Max', {}).get(possible_num_players, {})
            if possible_sm_max_record:
                possible_speed_record = record_references[level].get('SM Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    max_time_in_seconds = possible_sm_max_record['time_in_seconds']
                    if max_time_in_seconds < possible_speed_record['time_in_seconds']:
                        possible_pacifist_record = possible_speed_record.get('actual_record')
                        if (not possible_pacifist_record or (
                                possible_pacifist_record and
                                (max_time_in_seconds < possible_pacifist_record['time_in_seconds'])
                        )):
                            LOGGER.warning('Potential faster SM Max record found than SM Speed!')
                            LOGGER.warning('WAD: %s, level: %s.', dsda_url, level)

            possible_sk4_max_record = record_references[level].get('Sk4 Max', {}).get(possible_num_players, {})
            if possible_sk4_max_record:
                possible_speed_record = record_references[level].get('Sk4 Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    max_time_in_seconds = possible_sk4_max_record['time_in_seconds']
                    if max_time_in_seconds < possible_speed_record['time_in_seconds']:
                        possible_pacifist_record = possible_speed_record.get('actual_record')
                        if (not possible_pacifist_record or (
                                possible_pacifist_record and
                                (max_time_in_seconds < possible_pacifist_record['time_in_seconds'])
                        )):
                            LOGGER.warning('Potential faster Sk4 Max record found than Sk4 Speed!')
                            LOGGER.warning('WAD: %s, level: %s.', dsda_url, level)

            possible_bp_max_record = record_references[level].get('BP Max', {}).get(possible_num_players, {})
            if possible_bp_max_record:
                possible_speed_record = record_references[level].get('BP Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    if possible_bp_max_record['time_in_seconds'] < possible_speed_record['time_in_seconds']:
                        LOGGER.warning('Potential faster BP Max record found than BP Speed!')
                        LOGGER.warning('WAD: %s, level: %s.', dsda_url, level)

            possible_sk5_max_record = record_references[level].get('Sk5 Max', {}).get(possible_num_players, {})
            if possible_sk5_max_record:
                possible_speed_record = record_references[level].get('Sk5 Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    if possible_sk5_max_record['time_in_seconds'] < possible_speed_record['time_in_seconds']:
                        LOGGER.warning('Potential faster Sk5 Max record found than Sk5 Speed!')
                        LOGGER.warning('WAD: %s, level: %s.', dsda_url, level)

            possible_nm100_record = record_references[level].get('NM 100S', {}).get(possible_num_players, {})
            if possible_nm100_record:
                possible_speed_record = record_references[level].get('NM Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    if possible_nm100_record['time_in_seconds'] < possible_speed_record['time_in_seconds']:
                        LOGGER.warning('Potential faster NM 100S record found than NM Speed!')
                        LOGGER.warning('WAD: %s, level: %s.', dsda_url, level)

            possible_nomo100_record = record_references[level].get('NoMo 100S', {}).get(possible_num_players, {})
            if possible_nm100_record:
                possible_speed_record = record_references[level].get('NoMo Speed', {}).get(possible_num_players, {})
                if possible_speed_record:
                    if possible_nomo100_record['time_in_seconds'] < possible_speed_record['time_in_seconds']:
                        LOGGER.warning('Potential faster NoMo 100S record found than NoMo Speed!')
                        LOGGER.warning('WAD: %s, level: %s.', dsda_url, level)

    final_demo_list.extend(unchanged_demos)
    return {'headers': parsed_demo_page['headers'], 'demo_list': final_demo_list}


def get_wad_or_player_name_from_dsda_url(dsda_url):
    """Get WAD or player name from DSDA URL.

    :param dsda_url: DSDA URL
    :return: WAD or player name from DSDA URL
    """
    # https://www.dsdarchive.com/wads/scythe:
    #   path: /wads/scythe
    # https://www.dsdarchive.com/players/---:
    #   path: /players/---
    return urlparse(dsda_url).path.strip('/').split('/')[1]


def download_wad_from_dsda(dsda_url, overwrite=True):
    """Download WAD from DSDA URL.

    :param dsda_url: DSDA URL
    :param overwrite: Flag indicating whether to overwrite the local path if it exists
    :return: Path to local wad download from DSDA
    :raises ValueError if a non-wad URL is provided to this function
    """
    verify_dsda_url(dsda_url, page_types=['wad'])
    soup = get_page(dsda_url)
    wad_url = parse_page_top(soup).get('wad_url')
    if not wad_url or not wad_url.startswith('/files'):
        LOGGER.info('No link available for page: %s.', dsda_url)
        LOGGER.info('This should only happen if this is a commercial product.')
        return

    wad_url = fix_dsda_link(wad_url)
    response = requests.get(wad_url)
    default_filename = urlparse(wad_url).path.strip('/').split('/')[-1]
    download_filename = get_download_filename(response, default_filename=default_filename)
    wad_name = get_wad_or_player_name_from_dsda_url(dsda_url)
    download_dir = os.path.join(CONFIG.wad_download_directory, wad_name)
    download_response(response, download_dir, download_filename, overwrite=overwrite)
    return os.path.join(download_dir, download_filename)


def download_demo_from_dsda(dsda_demo_url, download_dir, overwrite=True):
    """Download demo from DSDA.

    :param dsda_demo_url: DSDA demo URL
    :param overwrite: Flag indicating whether to overwrite the local path if it exists
    :return: Path to local demo download from DSDA
    """
    response = requests.get(dsda_demo_url)
    default_filename = urlparse(dsda_demo_url).path.strip('/').split('/')[-1]
    download_filename = get_download_filename(response, default_filename=default_filename)
    download_response(response, download_dir, download_filename, overwrite=overwrite)
    return os.path.join(download_dir, download_filename)


def conform_dsda_wad_url(dsda_wad_url):
    """Conform DSDA WAD URL.

    Limit path to first two parts (up to the WAD name) and remove any query/fragment/etc. Assume
    that the URL is already conformed to include a scheme, so the urllib parse library parses it
    correctly.

    :param dsda_wad_url: DSAD WAD URL
    :return: Conformed DSDA WAD URL
    """
    parsed_url = urlparse(dsda_wad_url)
    # Do not strip URL because it will be prepended with "/" and we need to retain that, so we go
    # to the 3rd element even though the wad name is second.
    parsed_url = parsed_url._replace(path='/'.join(parsed_url.path.split('/')[:3]))
    parsed_url = parsed_url._replace(params='')._replace(query='')._replace(fragment='')
    return urlunparse(parsed_url)


def get_wads():
    """Get dictionary of WAD short names mapped to WAD URLs.

    :return: WAD short names mapped to WAD URLs
    """
    wads = {}
    for wad_page_param in ['9'] + list(string.ascii_lowercase):
        soup = get_page(f'{DSDA_WAD_URL}?letter={wad_page_param}')
        player_table = soup.find('table')
        rows = player_table.find('tbody').find_all('tr')
        for row in rows:
            wad_file_col = row.find('td', class_='wadfile')
            dsda_cell = parse_dsda_cell(wad_file_col)
            wads[dsda_cell.text] = next(iter(dsda_cell.links.values()))

    return wads


def get_players():
    """Get dictionary of player names mapped to player URLs.

    :return: Player names mapped to player URLs
    """
    api_response = requests.get(DSDA_PLAYER_API_URL, headers={"User-Agent": "Mozilla/5.0"})
    return {player_dict['name']: '/'.join([DSDA_PLAYER_URL, player_dict['username']])
            for player_dict in api_response.json()['players']}


def get_player_stats(player_url):
    """Get player stats.

    :return: Player stats
    """
    verify_dsda_url(player_url, page_types=['player'])
    player_stats_page = f'{player_url}/stats'
    soup = get_page(player_stats_page)
    player_stats_elems = soup.find_all('h4')
    player_stats = {}
    for elem in player_stats_elems:
        elem_text = elem.getText()
        key, value = elem_text.split('=', 1)
        key = key.lower().strip().replace(' ', '_')
        value = value.strip()
        player_stats[key] = value

    return player_stats
