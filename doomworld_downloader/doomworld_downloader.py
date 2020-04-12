import itertools
import re

from dataclasses import dataclass
from datetime import datetime

import requests
import yaml

from bs4 import BeautifulSoup
from lxml import etree

DOOM_SPEED_DEMOS_URL = 'https://www.doomworld.com/forum/37-doom-speed-demos/?page={num}'
THREAD_URL = '{base_url}/?page={num}'
DATETIME_FORMAT = 'YYYY'
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

THREAD_MAP = {}


@dataclass
class Thread:
    name: str
    id: int
    url: str
    last_post_date: datetime


@dataclass
class Post:
    author_name: str
    post_date: datetime
    attachments: dict
    links: dict
    post_text: str
    parent: Thread


def get_link_elems(link_elems, extract_link=False):
    links = {}
    for link_elem in link_elems:
        links[link_elem.getText().strip()] = link_elem['href']
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
        title = thread.find(class_='ipsDataItem_title')
        title_link = title.find_all('a')[0]
        last_poster = thread.find(class_='ipsDataItem_lastPoster')
        last_post_date = last_poster.find('time')['datetime']
        last_post_date = datetime.strptime(last_post_date, '%Y-%m-%dT%H:%M:%SZ')
        threads.append(Thread(title_link.getText().strip(), id, title_link['href'], last_post_date))

    return threads


def parse_thread_page(base_url, page_number, thread):
    soup = get_page(THREAD_URL.format(base_url=base_url, num=page_number))
    post_elems = soup.find_all('article', class_='ipsComment')
    posts = []
    for post in post_elems:
        post_content_elem = post.find('div', class_='cPost_contentWrap')
        post_content_elem = post_content_elem.find('div', attrs={'data-role': 'commentContent'})
        attachments = get_link_elems(post_content_elem.find_all('a', class_='ipsAttachLink'),
                                     extract_link=True)
        # Skip posts with no attachments as they have no demos to search for
        if not attachments:
            continue

        # TODO: We may not want to extract_link here because that removes the links, so it might be
        # harder to infer which wad maps to which demos from a multi-wad multi-demo post
        links = get_link_elems(post_content_elem.find_all('a'), extract_link=True)

        author_elem = post.find('aside', class_='ipsComment_author')
        author_name = author_elem.find('h3', class_='cAuthorPane_author').getText().strip()

        post_text_elem = post.find('div', class_='ipsColumn')
        post_meta_elem = post_text_elem.find('div', class_='ipsComment_meta')
        post_date = post_meta_elem.find('time')['datetime']
        post_date = datetime.strptime(post_date, '%Y-%m-%dT%H:%M:%SZ')

        post_text = post_content_elem.getText().strip()
        post_text = '\n'.join([line.strip() for line in post_text.splitlines() if line.strip()])

        posts.append(Post(author_name, post_date, attachments, links, post_text, thread))

    return posts


def main():
    with open('thread_map.yaml') as thread_map_stream:
        THREAD_MAP.update(yaml.safe_load(thread_map_stream))

    with open('search_start_date.txt') as search_stream:
        search_start_date = search_stream.read().strip()
    search_start_date = datetime.strptime(search_start_date, '%Y-%m-%dT%H:%M:%SZ')

    with open('search_end_date.txt') as search_stream:
        search_end_date = search_stream.read().strip()
    search_end_date = datetime.strptime(search_end_date, '%Y-%m-%dT%H:%M:%SZ')

    threads = []
    for page_num in itertools.count(1):
        cur_threads = parse_thread_list(page_num)
        new_threads = [thread for thread in cur_threads
                       if thread.last_post_date > search_start_date]
        threads.extend(new_threads)
        if len(cur_threads) != len(new_threads):
            break

    posts = []
    for thread in threads:
        last_page_response = requests.get(THREAD_URL.format(base_url=thread.url, num=999))
        if last_page_response.history:
            if '?page=' in last_page_response.url:
                last_page_num = int(last_page_response.url.split('?page=')[1])
            else:
                last_page_num = 1

        for page_num in range(last_page_num, 0, -1):
            cur_posts = parse_thread_page(thread.url, page_num, thread)
            new_posts = [post for post in cur_posts
                         if search_start_date < post.post_date < search_end_date]
            posts.extend(new_posts)
            if len(cur_threads) != len(new_threads):
                break

    demo_jsons = []
    for post in posts:


        demo_jsons.append({
            'is_tas': None,
            'is_solo_net': None,
            'player_count': None,
            'wad_name': None,
            'zip_name': None,
            'engine': None,
            'time': None,
            'level': None,
            'kills': None,
            'items': None,
            'secrets': None,
            'category': None,
            'recorded_at': None,
            'player_list': None,
            'comment': None
        })


if __name__ == '__main__':
    main()
