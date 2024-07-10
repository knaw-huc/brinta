from typing import List, Dict

from annorepo.client import AnnoRepoClient, ContainerAdapter
from elasticsearch import Elasticsearch
from tqdm import tqdm

from SearchResultAdapter import SearchResultAdapter
from SearchResultItem import SearchResultItem
from SparseList import SparseList

# setup annorepo
annorepo = AnnoRepoClient('https://annorepo.republic-caf.diginfra.org')
container = annorepo.container_adapter("republic-2024.07.08")
print(annorepo.get_about())

# setup elastic
elastic = Elasticsearch('http://localhost:9200')
print(elastic.info())


def fetch_overlapping_volume_annos(container: ContainerAdapter, vol: SearchResultItem, types: List[str]) \
        -> Dict[str, List[SearchResultItem]]:
    query = build_overlapping_types_query(vol, types)

    volume_annos = dict()
    for t in types:
        volume_annos[t] = list()

    overlapping_anno_search = SearchResultAdapter(container, query)
    # print(overlapping_anno_search.search_info)

    anno_count = 0
    pbar = tqdm(overlapping_anno_search.items(), total=overlapping_anno_search.hits(), leave=False, unit="ann")
    for anno in pbar:
        pbar.set_description(f'ann: {anno.path('body.id').removeprefix('urn:republic:'):>60}')
        volume_annos[anno.path('body.type')].append(anno)
        anno_count += 1

    assert anno_count == overlapping_anno_search.hits()

    return volume_annos


def build_overlapping_types_query(vol: SearchResultItem, types: List[str]):
    target = vol.first_target_with_selector('Text')
    selector = target['selector']
    return {"body.type": {":isIn": types},
            ":overlapsWithTextAnchorRange": {
                "source": target['source'],
                "start": selector['start'],
                "end": selector['end']
            }}


def index_annos(volume_annos: Dict[str, List[SearchResultItem]], main_type: str):
    lst = SparseList()
    aux_annos_by_main_anno = dict()
    for main_anno in volume_annos[main_type]:
        aux_annos = set()  # use a single anno set for each 'Resolution'
        aux_annos_by_main_anno[main_anno] = aux_annos
        selector = main_anno.first_target_with_selector('LogicalText')['selector']
        for i in range(selector['start'], selector['end'] + 1):
            lst[i] = aux_annos

    for aux_type in [k for k in volume_annos.keys() if k != main_type]:
        for aux_anno in volume_annos[aux_type]:
            selector = aux_anno.first_target_with_selector('LogicalText')['selector']
            already_added = None
            for i in range(selector['start'], selector['end'] + 1):
                if lst[i] is not None and lst[i] != already_added:
                    lst[i].add(aux_anno)
                    already_added = lst[i]

    for main_anno in volume_annos[main_type]:
        print(f'{main_anno.path('body.id')}: ')
        for aux_anno in aux_annos_by_main_anno[main_anno]:
            print(f' - {aux_anno.path('body.id')}')


volume_search = SearchResultAdapter(container, {"body.type": "Volume"})
volume_count = 0
pbar = tqdm(volume_search.items(), total=volume_search.hits(), unit="vol")
for v in pbar:
    pbar.set_description(f'vol: {v.path('body.id').removeprefix('urn:republic:volume:')}')
    volume_annos = fetch_overlapping_volume_annos(container, v, ['Resolution', 'Attendant', 'Entity'])
    index_annos(volume_annos, 'Resolution')
    volume_count += 1
    break  # dev limit: stop after first

print(f'indexed {volume_count} volumes')
