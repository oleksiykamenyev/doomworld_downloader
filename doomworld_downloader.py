"""
Doomworld downloader.

# TODO: Rename/reorganize this code
Specifically, I see the following structure making sense:
  - entry main code (probably rename this class to something like dsda_auto_updater)
    - this will contain just calls to the underlying stuff; i.e.:
      - get all of the relevant posts using the web parsing module and download demos
      - then use a separate interpolator module that takes the data from all the sources and mushes
        it together
  - separate module where we can move all of the BeautifulSoup/web parsing crap in here
    - the download request code can be in there too
"""

import itertools
import logging
import os
import re

from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse, parse_qs

import requests
import yaml

from bs4 import BeautifulSoup
from lxml import etree

from doomworld_downloader.upload_config import CONFIG


DOOM_SPEED_DEMOS_URL = 'https://www.doomworld.com/forum/37-doom-speed-demos/?page={num}'
THREAD_URL = '{base_url}/?page={num}'
POST_URL = 'https://www.doomworld.com/forum/post/{post_id}'
DATETIME_FORMAT = 'YYYY'
METADATA_FILE = 'demo_downloader_meta.txt'
CATEGORY_REGEXES = [
    re.compile(r'UV[ -_]?Max', re.IGNORECASE),
    re.compile(r'UV[ -_]?Speed', re.IGNORECASE),
    re.compile(r'NM[ -_]?Speed', re.IGNORECASE),
    re.compile(r'NM[ -_]?100s?', re.IGNORECASE),
    re.compile(r'UV[ -_]?-?fast', re.IGNORECASE),
    re.compile(r'(UV)?[ -_]?-?respawn', re.IGNORECASE),
    re.compile(r'(UV)?[ -_]?Pacifist', re.IGNORECASE),
    re.compile(r'(UV)?[ -_]?Tyson', re.IGNORECASE),
    # TODO: Either encode regex logic to make this not match nomo100 or have logic later on for that
    re.compile(r'(UV)?[ -_]?No ?mo(nsters)?', re.IGNORECASE),
    re.compile(r'(UV)?[ -_]?Nomo100s?', re.IGNORECASE),
    re.compile(r'Nightmare!?', re.IGNORECASE),
    re.compile(r'(UV)?[ -_]?Reality', re.IGNORECASE),
    re.compile(r'(UV)?[ -_]?Stroller', re.IGNORECASE)
]
ZIP_RE = re.compile(r'^.*\.zip$')

THREAD_MAP = {}
THREAD_MAP_KEYED_ON_ID = {}

LOGGER = logging.getLogger(__name__)


@dataclass
class Thread:
    name: str
    id: int
    url: str
    last_post_date: datetime
    last_page_num: int


@dataclass
class Post:
    author_name: str
    post_date: datetime
    attachments: dict
    links: dict
    post_text: str
    post_url: str
    parent: Thread


def get_links(link_elems, extract_link=False):
    links = {}
    for link_elem in link_elems:
        link_url = link_elem['href']
        # The attachment links on Doomworld do not have the protocol info, adding it manually.
        # Running this for all the links and not just attachments seems safer just in case the link
        # coding changes on the Doomworld side.
        if not link_url.startswith('http'):
            link_url = 'https:' + link_url
        links[link_elem.getText().strip()] = link_url
        if extract_link:
            link_elem.extract()
    return links


def get_page(url):
    request_res = requests.get(url)
    page_text = str(request_res.text)
    return BeautifulSoup(page_text, features='lxml')


def parse_thread_list(page_number):
    soup = get_page(DOOM_SPEED_DEMOS_URL.format(num=page_number))
    thread_elems = soup.find_all('li', class_='ipsDataItem')
    threads = []
    for thread in thread_elems:
        id = thread['data-rowid']
        if id in THREAD_MAP_KEYED_ON_ID:
            if THREAD_MAP_KEYED_ON_ID[id].get('additional_info', {}).get('ignore', False):
                continue
        title = thread.find(class_='ipsDataItem_title')
        title_link = title.find_all('a')[0]
        pagination = title.find(class_='ipsPagination')
        if pagination is not None:
            last_page_num = int(pagination.getText().strip().split()[-1])
        else:
            last_page_num = 1

        last_poster = thread.find(class_='ipsDataItem_lastPoster')
        last_post_date = last_poster.find('time')['datetime']
        last_post_date = datetime.strptime(last_post_date, '%Y-%m-%dT%H:%M:%SZ')
        threads.append(Thread(title_link.getText().strip(), int(id), title_link['href'],
                              last_post_date, last_page_num))

    return threads


def parse_thread_page(base_url, page_number, thread):
    soup = get_page(THREAD_URL.format(base_url=base_url, num=page_number))
    post_elems = soup.find_all('article', class_='ipsComment')
    posts = []
    for post in post_elems:
        post_content_elem = post.find('div', class_='cPost_contentWrap')
        post_content_elem = post_content_elem.find('div', attrs={'data-role': 'commentContent'})
        # Remove all quotes from each post so we don't accidentally parse a different post's
        # category/other info and don't accidentally get attachments from a different post.
        quotes = post_content_elem.find_all('blockquote', class_='ipsQuote')
        for quote in quotes:
            quote.extract()

        attachments = get_links(post_content_elem.find_all('a', class_='ipsAttachLink'),
                                extract_link=True)
        # TODO: Consider repackaging rars and 7zs so we don't have to ask the posters to do it
        attachments = {attach: attach_url for attach, attach_url in attachments.items()
                       if ZIP_RE.match(attach)}
        # Skip posts with no attachments as they have no demos to search for
        if not attachments:
            continue

        post_id = post['id'].split('_')[1]
        post_url = POST_URL.format(post_id=post_id)

        # TODO: We may not want to extract_link here because that removes the links, so it might be
        # harder to infer which wad maps to which demos from a multi-wad multi-demo post
        links = get_links(post_content_elem.find_all('a'), extract_link=True)

        author_elem = post.find('aside', class_='ipsComment_author')
        author_name = author_elem.find('h3', class_='cAuthorPane_author').getText().strip()

        post_text_elem = post.find('div', class_='ipsColumn')
        post_meta_elem = post_text_elem.find('div', class_='ipsComment_meta')
        post_date = post_meta_elem.find('time')['datetime']
        post_date = datetime.strptime(post_date, '%Y-%m-%dT%H:%M:%SZ')

        post_text = post_content_elem.getText().strip()
        post_text = '\n'.join([line.strip() for line in post_text.splitlines() if line.strip()])

        posts.append(Post(author_name, post_date, attachments, links, post_text, post_url, thread))

    return posts


def main():
    # TODO: Probably refactor this to a separate module/class handling configuration
    # TODO:
    #   The config files (thread map, upload.ini, etc.) should eventually be moved to be managed by
    #   pkg_resources instead of relative paths
    testing_mode = CONFIG.testing_mode
    with open('doomworld_downloader/thread_map.yaml', encoding='utf-8') as thread_map_stream:
        THREAD_MAP.update(yaml.safe_load(thread_map_stream))

    # TODO: I made the map keyed on URL, but depending on how we use it over time, might want to
    # reformat the YAML to be keyed on ID
    for url, thread_dict in THREAD_MAP.items():
        THREAD_MAP_KEYED_ON_ID[thread_dict['id']] = {key: value
                                                     for key, value in thread_dict.items()}
        THREAD_MAP_KEYED_ON_ID['url'] = url

    search_start_date = datetime.strptime(CONFIG.search_start_date, '%Y-%m-%dT%H:%M:%SZ')
    search_end_date = datetime.strptime(CONFIG.search_end_date, '%Y-%m-%dT%H:%M:%SZ')
    threads = []
    for page_num in itertools.count(1):
        # In case of testing, use dummy data
        if testing_mode:
            break
        cur_threads = parse_thread_list(page_num)
        new_threads = [thread for thread in cur_threads
                       if thread.last_post_date > search_start_date]
        # If no new threads are found, break out of the loop.
        if not new_threads:
            break

        threads.extend(new_threads)

    LOGGER.debug(threads)
    posts = []
    for thread in threads:
        # In case of testing, use dummy data
        if testing_mode:
            break
        for page_num in range(thread.last_page_num, 0, -1):
            cur_posts = parse_thread_page(thread.url, page_num, thread)
            # If the last post on a page is before the start date, we can break out immediately
            # since we are going backwards in time from the last page.
            if cur_posts and cur_posts[-1].post_date < search_start_date:
                break

            new_posts = [post for post in cur_posts
                         if search_start_date < post.post_date < search_end_date]
            posts.extend(new_posts)

    LOGGER.debug(posts)
    # In case testing, use dummy data
    # TODO: Generate this in a better way
    # Long-term we need unit tests, so maybe this mode can be removed entirely in the future, or if
    # it's needed, we can put the test data into a test input file somewhere instead of directly in
    # the code
    if testing_mode:
        posts = [
            Post(author_name='the_kovic', post_date=datetime(2020, 4, 10, 15, 22, 55), attachments={'kovic_e2m1-40.zip': 'https://www.doomworld.com/applications/core/interface/file/attachment.php?id=82293'}, links={'https://www.youtube.com/watch?v=aXyPH0J4BD8': 'https://www.youtube.com/watch?v=aXyPH0J4BD8'}, post_text='Ultimate Doom E2M1 in 40\nPort used: Crispy Doom\nDemo:\nVideo:\nI was inspired to attempt to run something in Doom by a couple of content creators on YT (you probably know which ones), decided to try E2M1. I got 41 in about ten minutes and then spent three more hours grinding 40. It might be bias but for now I think that running Doom is much harder for me than bunnyhopping in Source games (which is what I usually play and run).\nI hope I read all the rules correctly and that the demo works fine.', parent=Thread(name='Personal Best Demo Thread ← POST YOUR NON-WRs HERE', id=112532, url='https://www.doomworld.com/forum/topic/112532-personal-best-demo-thread-%E2%86%90-post-your-non-wrs-here/', last_post_date=datetime(2020, 4, 11, 3, 4, 56), last_page_num=3)), Post(author_name='RobUrHP420', post_date=datetime(2020, 4, 11, 3, 4, 56), attachments={'9.94e1m1(uv  pacifist).zip': 'https://www.doomworld.com/applications/core/interface/file/attachment.php?id=82370'}, links={'https://www.youtube.com/watch?v=2LF_jlA1aLc': 'https://www.youtube.com/watch?v=2LF_jlA1aLc'}, post_text='Finally hit 9s on Hangar (UV Pacifist) So happy rn! Took me well over a thousand attempts.\nVideo:', parent=Thread(name='Personal Best Demo Thread ← POST YOUR NON-WRs HERE', id=112532, url='https://www.doomworld.com/forum/topic/112532-personal-best-demo-thread-%E2%86%90-post-your-non-wrs-here/', last_post_date=datetime(2020, 4, 11, 3, 4, 56), last_page_num=3))]

    demo_jsons = []
    for post in posts:
        author_name = post.author_name
        author_dir = 'demos_for_upload/{}'.format(author_name)
        for attach_name, attach_url in post.attachments.items():
            parsed_url = urlparse(attach_url)
            attach_id = parse_qs(parsed_url.query, keep_blank_values=True)['id']
            attach_dir = os.path.join(author_dir, attach_id[0])
            os.makedirs(attach_dir, exist_ok=True)
            response = requests.get(attach_url)
            attach_path = os.path.join(attach_dir, attach_name)
            with open(attach_path, 'wb') as output_file:
                output_file.write(response.content)

            with open(os.path.join(attach_dir, METADATA_FILE), 'w') as meta_file:
                meta_file.write(post.post_url)

        demo_jsons.append({
            # Get this from the thread map or if the textfile has the TAS string in it.
            'is_tas': None,
            # Get this from the lmp header?
            'is_solo_net': None,
            # Get this from the lmp header
            'player_count': None,
            # Get this from the thread map or post URLs or last resort either the demo footer or
            # textfile
            'wad_name': None,
            # This is in the attachments dictionary
            'zip_name': None,
            # Get this from the footer/demo analysis preferably, if not then demo
            'engine': None,
            # Get this from the levelstat preferably, or the post/textfile
            'time': None,
            # Get this from the levelstat
            'level': None,
            # Get this from the levelstat
            'kills': None,
            # Get this from the levelstat
            'items': None,
            # Get this from the levelstat
            'secrets': None,
            # Auto-infer this preferably or get from post/textfile
            'category': None,
            # Get this from the zip file date
            'recorded_at': None,
            # Assume this is the author name unless num_players is more than 1, in which case we
            # probably will have to fill it in manually
            'player_list': None,
            # Update in case of Other category or certain other cases (need to compile a list, not
            # sure we can cover this automatically)
            'comment': None
        })


if __name__ == '__main__':
    main()
