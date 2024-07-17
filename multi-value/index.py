import collections
import gzip
from pathlib import Path
from typing import List, Dict, Any

import jsonpickle
from annorepo.client import AnnoRepoClient, ContainerAdapter
from elasticsearch import Elasticsearch
from tqdm import tqdm

from SearchResultAdapter import SearchResultAdapter
from SearchResultItem import SearchResultItem
from SparseList import SparseList

# settings
# dataset_name = 'republic-2024.06.18'
dataset_name = 'republic-2024.07.08'

# setup annorepo
annorepo = AnnoRepoClient('https://annorepo.republic-caf.diginfra.org')
container = annorepo.container_adapter(dataset_name)
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
    pbar = tqdm(overlapping_anno_search.items(), total=overlapping_anno_search.hits(), colour='blue', leave=True,
                unit="ann")
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


def bmd(field: str) -> str:
    return f'body.metadata.{field}'


def create_anno_doc(anno: SearchResultItem) -> Dict[str, Any]:
    doc = dict()

    metadata_items = [
        'propositionType', 'resolutionType',
        'sessionDate', 'sessionDay', 'sessionMonth', 'sessionYear', 'sessionWeekday',
        'textType'
    ]

    for it in metadata_items:
        doc[it] = anno.path(bmd(it))

    doc['bodyType'] = anno.path('body.type')

    return doc


def enrich_with_overlapping_annos(doc: dict[str, any], aux_annos: set[SearchResultItem]):
    aux_map = {
        'entityCategory': bmd('category'),
        'entityId': bmd('entityID'),
        'entityLabels': bmd('entityLabels'),
        'entityName': bmd('name')
    }
    for aux_anno in aux_annos:
        if aux_anno.path('body.type') == 'Entity':
            for it in aux_map.keys():
                doc[it] = aux_anno.path(aux_map[it])


def enrich_with_matching_annos(doc: dict[str, any], aux_annos: set[SearchResultItem]):
    aux_map = {
        'delegateId': bmd('delegateID'),
        'delegateName': bmd('delegateName')
    }
    for it in aux_map.keys():
        doc[it] = list[str]()
    for aux_anno in aux_annos:
        for it in aux_map.keys():
            val = aux_anno.path(aux_map[it])
            if val:
                doc[it].append(val)


def index_annos(volume_annos: dict[str, list[SearchResultItem]], main_type: str):
    lst = SparseList()
    overlapping_annos_by_main_anno = dict()
    for main_anno in volume_annos[main_type]:
        overlapping_annos = set[SearchResultItem]()  # use a single anno set for each 'Resolution'
        overlapping_annos_by_main_anno[main_anno] = overlapping_annos
        selector = main_anno.first_target_with_selector('LogicalText')['selector']
        for i in range(selector['start'], selector['end'] + 1):
            lst[i] = overlapping_annos

    # for aux_type in [k for k in volume_annos.keys() if k != main_type]:
    for aux_type in ['Entity']:  # only for volume_annos.keys() that need overlap
        for aux_anno in volume_annos[aux_type]:
            selector = aux_anno.first_target_with_selector('LogicalText')['selector']
            just_checked = None
            for i in range(selector['start'], selector['end'] + 1):
                if lst[i] is not None and lst[i] != just_checked:
                    lst[i].add(aux_anno)
                    just_checked = lst[i]

    aux_annos_by_session_id = collections.defaultdict(set[SearchResultItem])
    # for aux_type in [k for k in volume_annos.keys() if k != main_type]:
    for aux_type in ['Attendant']:  # only for volume_annos.keys() that need to match
        for aux_anno in volume_annos[aux_type]:
            session_id = aux_anno.path(bmd('sessionID'))
            aux_annos_by_session_id[session_id].add(aux_anno)

    pbar = tqdm(volume_annos[main_type], colour='yellow', leave=True, unit='res')
    for main_anno in pbar:
        doc_id = main_anno.path('body.id')
        pbar.set_description(f'idx: {doc_id:>60}')
        doc = create_anno_doc(main_anno)
        enrich_with_overlapping_annos(doc, overlapping_annos_by_main_anno[main_anno])
        session_id = main_anno.path(bmd('sessionID'))
        enrich_with_matching_annos(doc, aux_annos_by_session_id[session_id])

        # now send doc to elastic
        resp = elastic.index(index=dataset_name, id=doc_id, document=doc)
        if resp['result'] not in ['created', 'updated']:
            print(f'Indexing {doc_id} failed: resp')


def create_index(mapping):
    elastic.indices.create(index=dataset_name, body=mapping)


def delete_index():
    elastic.indices.delete(index=dataset_name)


if not elastic.indices.exists(index=dataset_name):
    path = Path('mapping.json')
    print(f'Creating ES index: {dataset_name} using: \'{path}\'')
    create_index(path.read_text())

volume_search = SearchResultAdapter(container, {"body.type": "Volume"})
volume_result = list[SearchResultItem]()
pbar = tqdm(volume_search.items(), total=volume_search.hits(), colour='magenta', unit='vol')
for v in pbar:
    pbar.set_description(f'vol: {v.path('body.id').removeprefix('urn:republic:volume:'):>60}')
    volume_result.append(v)
    # break  # dev limit: stop after first

print(f'fetched {len(volume_result)} volumes, hash={hash(volume_search)}')

cache = Path('.cache')
cache.mkdir(exist_ok=True)
frozen = jsonpickle.encode(volume_result)
with open(cache / 'volumes', 'w', encoding='utf-8') as f:
    f.write(frozen)

pbar = tqdm(volume_result, total=len(volume_result), colour='green', unit='vol')
for v in pbar:
    body_id = v.path('body.id').removeprefix('urn:republic:volume:')
    pbar.set_description(f'vol: {body_id:>60}')
    path = (cache / f'{body_id}.gz')
    print(path)
    if path.exists():
        with gzip.open(path) as f:
            volume_annos = jsonpickle.decode(f.read())
    else:
        volume_annos = fetch_overlapping_volume_annos(container, v, ['Resolution', 'Attendant', 'Entity'])
        with gzip.open(path, 'wt') as f:
            f.write(jsonpickle.encode(volume_annos))
    index_annos(volume_annos, 'Resolution')
