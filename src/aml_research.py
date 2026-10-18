"""Dependency-free evidence retrieval baseline. Not yet an embedding-based RAG system."""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
import math
from pathlib import Path
import re
import threading

ROOT = Path(__file__).resolve().parents[1]
STOP = set('a an the is are was were be been to of in on at for from and or with by as it its this that what which how does do can should would could we our your you i me about under into s'.split())


def tokens(text):
    words=[w for w in re.findall(r'[a-z0-9]+', text.lower()) if w not in STOP]
    # Light plural normalization keeps mule/mules and company/companies aligned
    # without stemming policy words such as analysis or status.
    def singular(w):
        if len(w)>4 and w.endswith('ies'):return w[:-3]+'y'
        if len(w)>4 and w.endswith('s') and not w.endswith(('ss','us','is')):return w[:-1]
        return w
    return [singular(w) for w in words]


def make_chunks(source, meta, max_words=230):
    """Keep heading context and whole extraction lines, including nearby exceptions.

    Oversized paragraphs remain whole; this favors preserving qualifications over
    enforcing a hard token limit. Source locators refer to this captured extract.
    """
    result, pending, heading = [], [], meta['title']

    def flush():
        if not pending:
            return
        start, end = pending[0]['line'], pending[-1]['line']
        text = '\n'.join(x['text'] for x in pending)
        result.append({
            'chunk_id': f"{source['source_id']}:L{start}-L{end}",
            'source_id': source['source_id'], 'title': meta['title'],
            'heading': heading, 'issuer': meta['issuer'],
            'authority_type': meta['authority_type'], 'url': source['url'],
            'published_date': meta.get('published_date'),
            'captured_date': source['captured_date'],
            'locator': (f'PDF page {pending[0]["page"]} · extracted text lines {start}-{end}' if pending[0].get('page') else f'Captured extract lines {start}-{end}'),
            'pdf_page': pending[0].get('page'),
            'topics': meta.get('topics', []),
            'currency_status': 'not independently checked for amendments or relief',
            'text': text,
        })
        pending.clear()

    for line in source['lines']:
        text = line['text'].strip()
        if not text:
            continue
        if text.startswith('#'):
            flush()
            heading = text.lstrip('#').strip()
            continue
        # Flush after reaching the target, preserving each extraction line.
        if pending and len(' '.join(x['text'] for x in pending).split()) >= max_words:
            flush()
        pending.append({'line': line['line'], 'text': text, 'page': line.get('page')})
    flush()
    return result


def build_index():
    manifest = json.loads((ROOT / 'config/source_manifest.json').read_text())
    metadata = {s['source_id']: s for s in manifest['sources']}
    chunks = []
    for path in sorted((ROOT / 'data/raw').glob('S*.json')):
        raw = path.read_bytes()
        source = json.loads(raw)
        meta = metadata[source['source_id']]
        if not meta.get('eligible_for_retrieval_prototype', False):
            continue
        chunks.extend(make_chunks(source, meta))
        meta.update(ingested=True, sha256=hashlib.sha256(raw).hexdigest(),
                    captured_date=source['captured_date'],
                    capture_method=source['capture_method'],
                    captured_extract_line_range=source['extract_line_range'])
    if not chunks:
        raise ValueError('No eligible source extracts found.')
    target = ROOT / 'data/processed/chunks.json'
    target.write_text(json.dumps(chunks, indent=2, ensure_ascii=False))
    manifest['status'] = 'excerpt corpus indexed for prototype retrieval; legal currency review pending'
    (ROOT / 'config/source_manifest.json').write_text(json.dumps(manifest, indent=2))
    return chunks


class BM25:
    def __init__(self, chunks):
        self.chunks = chunks
        self.docs = [Counter(tokens(c['title'] + ' ' + c['heading'] + ' ' + c['text'])) for c in chunks]
        self.lengths = [sum(d.values()) for d in self.docs]
        self.average = sum(self.lengths) / max(1, len(self.docs))
        self.df = Counter(w for doc in self.docs for w in doc)

    def search(self, question, k=5, source_id=None):
        if not 1 <= k <= 20:
            raise ValueError('k must be between 1 and 20')
        original_terms = set(tokens(question))
        expansions = {'kyc':'know your customer identity verification', 'cdd':'customer due diligence',
                      'edd':'enhanced due diligence higher risk', 'cip':'customer identification program'}
        query_terms = tokens(question + ' ' + ' '.join(v for a,v in expansions.items() if a in original_terms))
        query = set(query_terms)
        if not query:
            return []
        ranked = []
        allowed = None
        topics_file=ROOT/'config/typology_topics.json'
        if not source_id and topics_file.exists():
            topic_specs=json.loads(topics_file.read_text())
            query_text=' '+' '.join(query_terms)+' '
            matched=[t for t in topic_specs if any(' '+' '.join(tokens(a))+' ' in query_text for a in t.get('aliases',[]))]
            if matched:
                preferred={sid for t in matched for sid in t['source_ids']}
                # Keep relevant control guidance for mixed control/typology questions.
                if query & {'kyc','cdd','edd','cip'} or 'due diligence' in question.lower():
                    preferred.update({'S06','S10','S12','S24'})
                if preferred & {c['source_id'] for c in self.chunks}:allowed=preferred
        control_question = bool(original_terms & {'kyc','cdd','edd','cip'}) or any(
            phrase in question.lower() for phrase in ('know your customer','customer due diligence','identity verification'))
        # Dedicated customer-control references prevent incidental KYC mentions
        # in broad threat reports from crowding out the operative guidance.
        if control_question and allowed is None and not source_id:
            allowed = {'S06','S10','S12','S24'}
            if re.search(r'histor|2014|testimony',question,re.I):allowed.add('S13')
        for chunk, doc, length in zip(self.chunks, self.docs, self.lengths):
            if source_id and chunk['source_id'] != source_id:
                continue
            if allowed is not None and chunk['source_id'] not in allowed:
                continue
            score = 0.0
            for word in query:
                frequency = doc[word]
                if not frequency:
                    continue
                idf = math.log(1 + (len(self.docs) - self.df[word] + .5) / (self.df[word] + .5))
                score += idf * frequency * 2.5 / (frequency + 1.5 * (.25 + .75 * length / self.average))
            # Favor topic-specific heading phrases over incidental generic
            # matches in short introductory sections. This remains lexical.
            heading_terms = tokens(chunk['heading'])
            heading_pairs = set(zip(heading_terms, heading_terms[1:]))
            generic = {'bank', 'banks', 'aml', 'bsa', 'compliance'}
            if score > 0:
                for pair in set(zip(query_terms, query_terms[1:])):
                    if pair in heading_pairs and not set(pair) <= generic:
                        score += 3.0
                ranked.append({**chunk, 'retrieval_score': round(score, 5)})
        ranked = sorted(ranked, key=lambda x: (-x['retrieval_score'], x['chunk_id']))
        # Multi-concept questions need evidence for each concept, rather than
        # five near-duplicate passages for the dominant one. Reserve one body
        # match per explicitly requested term, then fill by BM25 rank.
        concepts = {'kyc': 'know your customer', 'cdd': 'customer due diligence',
                    'edd': 'enhanced due diligence', 'cip': 'customer identification program'}
        requested = [(abbr, phrase) for abbr, phrase in concepts.items()
                     if abbr in query or phrase in question.lower()]
        selected = []
        if control_question and not source_id:
            anchors = []
            if original_terms & {'kyc','cdd'} or 'customer due diligence' in question.lower():
                anchors += [('S24','Customer Due Diligence Rule — consolidated FAQs (updated May 2026) · PDF page 2')]
            if 'kyc' in original_terms or 'know your customer' in question.lower():
                anchors += [('S10','Verification Through Documents')]
            if original_terms & {'kyc','cdd'} or 'customer due diligence' in question.lower():
                anchors += [('S12','Customer Due Diligence — Overview'), ('S12','Customer Due Diligence')]
            if 'edd' in original_terms or 'enhanced due diligence' in question.lower():
                anchors += [('S12','Higher Risk Profile Customers')]
            if original_terms & {'kyc','cip'} or 'know your customer' in question.lower():
                anchors += [('S10','Verification Through Documents'), ('S10','Verification Through Non-Documentary Methods')]
            anchors += [('S12','Ongoing Monitoring of the Customer Relationship')]
            for sid, heading in anchors:
                match=next((c for c in ranked if c['source_id']==sid and
                            (c['heading']==heading or heading=='terminology' and 'terminology' in c['heading'])),None)
                if match and match not in selected:selected.append(match)
        if len(requested) > 1:
            for abbr, phrase in requested:
                match = next((c for c in ranked if re.search(r'\b'+abbr+r'\b', c['text'], re.I)
                              or phrase in ' '.join(c['text'].lower().split())), None)
                if match and match not in selected:
                    selected.append(match)
        return (selected + [c for c in ranked if c not in selected])[:k]


_INDEX_CACHE = {}
_INDEX_LOCK = threading.Lock()

def load_index():
    path = ROOT / 'data/processed/chunks.json'
    if not path.exists():
        raise ValueError('Build the index first: python3 src/aml_research.py build')
    stat=path.stat();key=(str(path.resolve()),stat.st_mtime_ns,stat.st_size)
    with _INDEX_LOCK:
        if key not in _INDEX_CACHE:
            _INDEX_CACHE.clear()
            _INDEX_CACHE[key]=BM25(json.loads(path.read_text()))
        return _INDEX_CACHE[key]


def evidence_packet(question, results):
    return {
        'question': question, 'mode': 'retrieved_evidence_only',
        'scope': 'Selected US bank reference excerpts',
        'notice': 'Keyword matches are not confidence scores or a compliance conclusion. Legal currency review is pending.',
        'results': results,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    commands.add_parser('build')
    search = commands.add_parser('search')
    search.add_argument('question')
    search.add_argument('--k', type=int, default=5)
    search.add_argument('--source-id')
    search.add_argument('--json', action='store_true')
    args = parser.parse_args()
    if args.command == 'build':
        chunks = build_index()
        print(f"Indexed {len(chunks)} chunks from {len(set(c['source_id'] for c in chunks))} source excerpts. No model calls.")
        return
    index = load_index()
    results = index.search(args.question, args.k, args.source_id)
    packet = evidence_packet(args.question, results)
    if args.json:
        print(json.dumps(packet, indent=2, ensure_ascii=False))
        return
    print(packet['notice'])
    if not results:
        print('No keyword evidence found. This does not establish that no applicable rule exists.')
    for result in results:
        print(f"\n[{result['chunk_id']}] {result['heading']} | {result['authority_type']}")
        print(result['url'])
        print(result['locator'] + ' | captured ' + result['captured_date'])
        print(result['text'])


if __name__ == '__main__':
    main()
