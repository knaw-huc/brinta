import collections
import gzip
import logging
import traceback
from pathlib import Path
from typing import List, Dict, Any

import jsonpickle
import requests
from annorepo.client import AnnoRepoClient, ContainerAdapter
from elasticsearch import Elasticsearch
from tqdm import tqdm

from SearchResultAdapter import SearchResultAdapter
from SearchResultItem import SearchResultItem
from SparseList import SparseList

# settings
dataset_name = 'rep-2024.11.30'
container_name = 'republic-2024.11.30'

tqdm_bar_format = "{l_bar}{bar:20}{r_bar}{bar:-20b}"

# setup annorepo
annorepo = AnnoRepoClient('https://annorepo.goetgevonden.nl')
container = annorepo.container_adapter(container_name)
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
    print(query)
    print(overlapping_anno_search.search_info)

    anno_count = 0
    # pbar = tqdm(overlapping_anno_search.items(), total=overlapping_anno_search.hits(), colour='blue', leave=True,
    #             unit="ann", bar_format=tqdm_bar_format)
    for anno in overlapping_anno_search.items():
        # pbar.set_description(f'ann: {anno.path('body.id')[13:-37]:>60}')
        volume_annos[anno.path('body.type')].append(anno)
        anno_count += 1

    # AnnoRepo now uses a MongoDB Cursor and has no support for upfront 'size' counting anymore
    # assert anno_count == overlapping_anno_search.hits()

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
        'id': bmd('entityID'),
        'type': bmd('category'),
        'name': bmd('name'),
        'categories': bmd('entityLabels')
    }
    entities = list()
    for aux_anno in aux_annos:
        if aux_anno.path('body.type') == 'Entity':
            entity = dict()
            for key, path in aux_map.items():
                val = aux_anno.path(path)
                if val:
                    entity[key] = val
            if entity:
                entities.append(entity)
    doc['entities'] = dedup(entities)


def enrich_with_matching_annos(doc: dict[str, any], aux_annos: set[SearchResultItem]):
    delegate_fields = {'delegateID', 'name', 'president', 'province'}
    # print(f'enriching: len={len(aux_annos)}')
    delegates = list()
    for aux_anno in aux_annos:
        for delegate_anno in aux_anno.path(bmd('delegates')):
            delegate = dict()
            for key in delegate_fields:
                if key in delegate_anno:
                    delegate[key.replace('delegateID', 'id')] = delegate_anno[key]
            if len(delegate) > 0:
                delegates.append(delegate)
    doc['delegates'] = dedup(delegates)


def dedup(orig: list[dict[str, any]]) -> list[dict[str, any]]:
    # return [dict(s) for s in set(frozenset(d.items()) for d in lst)]
    return list({str(i): i for i in orig}.values())


def extract_text(anno: SearchResultItem, all_text: list[str]) -> str:
    selector = anno.first_target_with_selector('LogicalText')['selector']
    local_text_segments = all_text[selector['start']:selector['end'] + 1]
    if 'beginCharOffset' in selector:
        begin_char_offset = selector['beginCharOffset']
        local_text_segments[0] = local_text_segments[0][begin_char_offset:]
        print(f'beginCharOffset found: {selector} -> {local_text_segments[0]}')
    if 'endCharOffset' in selector:
        end_char_offset = selector['endCharOffset']
        local_text_segments[-1] = local_text_segments[-1][:end_char_offset + 1]
        print(f'endCharOffset found: {selector} -> {local_text_segments[-1]}')
    local_text = "".join(local_text_segments)
    # print(f'{selector} -> {local_text}')
    return local_text


def index_annos(volume_annos: dict[str, list[SearchResultItem]], main_type: str, volume_text_segments: list[str]):
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
            # print(f'  -> found entity: {aux_anno.path('body.id')}, range=[{selector['start']}..{selector['end']}]')
            just_checked = None
            for i in range(selector['start'], selector['end'] + 1):
                if lst[i] is not None and lst[i] != just_checked:
                    lst[i].add(aux_anno)
                    just_checked = lst[i]

    aux_annos_by_session_id = collections.defaultdict(set[SearchResultItem])
    # for aux_type in [k for k in volume_annos.keys() if k != main_type]:
    for aux_type in ['Session']:  # only for volume_annos.keys() that need to match
        for aux_anno in volume_annos[aux_type]:
            # session_id = aux_anno.path(bmd('sessionID'))
            session_id = aux_anno.path('body.id').replace(':session:session', ':session')
            aux_annos_by_session_id[session_id].add(aux_anno)

    pbar = tqdm(volume_annos[main_type], colour='yellow', leave=True, unit='res', bar_format=tqdm_bar_format)
    for main_anno in pbar:
        doc_id = main_anno.path('body.id')
        pbar.set_description(f'idx: {doc_id:>60}')
        # print(f'main_anno: {main_anno.path('body.id')}, sessionID={main_anno.path(bmd('sessionID'))}')
        doc = create_anno_doc(main_anno)
        enrich_with_overlapping_annos(doc, overlapping_annos_by_main_anno[main_anno])
        session_id = main_anno.path(bmd('sessionID'))
        enrich_with_matching_annos(doc, aux_annos_by_session_id[session_id])
        doc['text'] = extract_text(main_anno, volume_text_segments)

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
pbar = tqdm(volume_search.items(), total=volume_search.hits(), colour='magenta', unit='vol', bar_format=tqdm_bar_format)
for v in pbar:
    pbar.set_description(f'vol: {v.path('body.id').removeprefix('urn:republic:volume:'):>60}')
    volume_result.append(v)

cache = Path('.cache')
cache.mkdir(exist_ok=True)
frozen = jsonpickle.encode(volume_result)
with open(cache / 'volumes', 'w', encoding='utf-8') as f:
    f.write(frozen)

pbar = tqdm(volume_result, total=len(volume_result), colour='green', unit='vol')
for v in pbar:
    body_id = v.path('body.id').removeprefix('urn:republic:volume:')
    # if not body_id.endswith('3166'):
    #     print(f'SKIP: {body_id}')
    #     continue
    pbar.set_description(f'vol: {body_id:>60}')

    # prefetch all text segments for entire volume
    volume_text_target = v.first_target_without_selector('LogicalText')
    r = requests.get(volume_text_target['source'])
    if r.status_code == 200:
        volume_text_segments = r.json()
    else:
        print(f'Failed to get text for: {v.path('body.id')}')
        break

    path = (cache / f'{body_id}.gz')
    if path.exists():
        with gzip.open(path) as f:
            volume_annos = jsonpickle.decode(f.read())
    else:
        while True:
            try:
                print(f'Fetching overlapping annos for volume: {v.path('body.id')}')
                volume_annos = fetch_overlapping_volume_annos(container, v, ['Resolution', 'Entity', 'Session'])
                break
            except Exception as e:
                logging.error(traceback.format_exc())

        with gzip.open(path, 'wt') as f:
            f.write(jsonpickle.encode(volume_annos))
    index_annos(volume_annos, 'Resolution', volume_text_segments)
