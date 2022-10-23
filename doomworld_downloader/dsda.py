"""
Various utilities to parse DSDA pages
"""

import logging
import os
import requests

from dataclasses import dataclass

from urllib.parse import urlparse, urlunparse

from doomworld_downloader.upload_config import CONFIG
from doomworld_downloader.utils import get_download_filename, download_response, get_page


LOGGER = logging.getLogger(__name__)

DSDA_START = 'https://www.dsdarchive.com'
DSDA_PLAYER_URL = f'{DSDA_START}/players'


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
        table_info = div.find('p', {'class': 'p-short'})
        stats = table_info.getText().split('|')[0].split(',')
        parsed_headers['demo_count'] = int(stats[0].split(' ')[0].strip())
        parsed_headers['demo_time'] = stats[1].strip()

    return parsed_headers


def dsda_demo_page_to_json(dsda_url):
    """Convert DSDA demo page to JSON.

    :param dsda_url: DSDA URL
    :return: JSON of demos from given DSDA URL
    """
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


def get_wad_name_from_dsda_url(dsda_url):
    """Get WAD name from DSDA URL.

    :param dsda_url: DSDA URL
    :return: WAD name from DSDA URL
    """
    # https://www.dsdarchive.com/wads/scythe:
    #   path: /wads/scythe
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
    wad_name = get_wad_name_from_dsda_url(dsda_url)
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


def get_players():
    """Get dictionary of player names mapped to player URLs.

    :return: Player names mapped to player URLs
    """
    soup = get_page(DSDA_PLAYER_URL)
    player_table = soup.find('table')
    rows = player_table.find('tbody').find_all('tr')
    players = {}
    for row in rows:
        first_col = row.find('td')
        dsda_cell = parse_dsda_cell(first_col)
        players[dsda_cell.text] = next(iter(dsda_cell.links.values()))

    return players


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
