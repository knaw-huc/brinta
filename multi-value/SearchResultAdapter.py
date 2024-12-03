import json
from collections.abc import Generator
from typing import Dict, Any

from annorepo.client import ContainerAdapter

from SearchResultItem import SearchResultItem


class SearchResultAdapter:

    def __init__(self, container: ContainerAdapter, query: Dict[str, Any]):
        self.container = container
        self.query = query
        self.search_info = container.create_search(query)
        self.cached_hits = -1

    def __hash__(self):
        ser = json.dumps((self.query, self.container.client.base_url), sort_keys=True)
        print(ser)
        return hash(ser)

    def hits(self) -> int:
        if self.cached_hits == -1:
            # check upstream cached hits first, without asking for result page
            self.cached_hits = self.container.read_search_info(self.search_info.id)['hits']

        if self.cached_hits == -1:
            # force 'hits' to be computed by asking for first page of results
            self.container.read_search_result_page(self.search_info.id)
            self.cached_hits = self.container.read_search_info(self.search_info.id)['hits']

        return self.cached_hits

    def items(self, start_page: int = 0) -> Generator[SearchResultItem]:
        first_pass_count = -1
        cur_page = start_page
        while True:
            res = self.container.read_search_result_page(self.search_info.id, cur_page)
            if 'items' not in res:
                break

            # could be last page, or may have hit bug in MongoDB cursor in AR
            if 'next' not in res:
                print(f'no "next", last page? page={cur_page}')
                first_pass_count = len(res['items'])
                res = self.container.read_search_result_page(self.search_info.id, cur_page)
                second_pass_count = len(res['items'])
                print(f'retry: pass 1: {first_pass_count}, pass 2: {second_pass_count}')
                if first_pass_count == second_pass_count:
                    # retry yields same number, so this is final page
                    print('confirmed last page')
                else:
                    print("recovered from missing 'next_page'")
                    continue

            for item in res['items']:
                yield SearchResultItem(item)

            if 'next' not in res:
                break

            next_page_url = res['next']

            if '?page=' not in next_page_url:
                break

            cur_page = next_page_url.split('?page=')[1]
