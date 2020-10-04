import functools
import gzip
import json
import math

import time
import uuid
import xlsxwriter
from functools import wraps, update_wrapper

from flask import (
    after_this_request,
    session,
    jsonify,
    current_app,
    send_from_directory,
    make_response,
    g
)
from datetime import datetime
import copy
import json
import os
import random
import re


from flask import render_template, request


from folklore_app.main_app import app
from folklore_app.settings import SETTINGS_DIR
from folklore_app.response_processors import SentenceViewer
from folklore_app.search_engine.client import SearchClient

MAX_PAGE_SIZE = 100  # maximum number of sentences per page

with open(os.path.join(SETTINGS_DIR, 'corpus.json'),
          'r', encoding='utf-8') as f:
    settings = json.loads(f.read())


corpus_name = settings['corpus_name']
if settings['max_docs_retrieve'] >= 10000:
    settings['max_docs_retrieve'] = 9999

sc = SearchClient(SETTINGS_DIR, mode='test')
sentView = SentenceViewer(SETTINGS_DIR, sc)
sc.qp.rp = sentView
sc.qp.wr.rp = sentView
random.seed()
corpus_size = sc.get_n_words()  # size of the corpus in words
word_freq_by_rank = []
lemma_freq_by_rank = []
for lang in settings['languages']:
    # number of word types for each frequency rank
    word_freq_by_rank.append(
        sentView.extract_cumulative_freq_by_rank(
            sc.get_word_freq_by_rank(lang)))
    # number of lemmata for each frequency rank
    lemma_freq_by_rank.append(
        sentView.extract_cumulative_freq_by_rank(
            sc.get_lemma_freq_by_rank(lang)))
linePlotMetafields = ['year']
# metadata fields whose statistics can be displayed on a line plot
sessionData = {}  # session key -> dictionary with the data for current session


app.config.update(dict(
    LANGUAGES=settings['interface_languages'],
    BABEL_DEFAULT_LOCALE='ru'
))


def jsonp(func):
    """
    Wrap JSONified output for JSONP requests.
    """

    @wraps(func)
    def decorated_function(*args, **kwargs):
        callback = request.args.get('callback', False)
        if callback:
            data = str(func(*args, **kwargs).data)
            content = str(callback) + '(' + data + ')'
            mimetype = 'application/javascript'
            return current_app.response_class(content, mimetype=mimetype)
        else:
            return func(*args, **kwargs)

    return decorated_function


def gzipped(f):
    """
    Gzipper taken from https://gist.github.com/RedCraig/94e43cdfe447964812c3
    """

    @functools.wraps(f)
    def view_func(*args, **kwargs):
        @after_this_request
        def zipper(response):
            accept_encoding = request.headers.get('Accept-Encoding', '')
            if 'gzip' not in accept_encoding.lower():
                return response
            response.direct_passthrough = False
            if (response.status_code < 200 or
                    response.status_code >= 300 or
                    'Content-Encoding' in response.headers):
                return response
            response.data = gzip.compress(response.data)
            response.headers['Content-Encoding'] = 'gzip'
            response.headers['Vary'] = 'Accept-Encoding'
            response.headers['Content-Length'] = len(response.data)
            return response

        return f(*args, **kwargs)

    return view_func


def nocache(view):
    @wraps(view)
    def no_cache(*args, **kwargs):
        response = make_response(view(*args, **kwargs))
        # response.headers['Last-Modified'] = http_date(datetime.now())
        response.headers['Cache-Control'] = (
            'no-store, no-cache, must-revalidate, post-check=0,'
            ' pre-check=0, max-age=0')
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '-1'
        return response

    return update_wrapper(no_cache, view)


def initialize_session():
    """
    Generate a unique session ID and initialize a dictionary with
    parameters for the current session. Write it to the global
    sessionData dictionary.
    """
    global sessionData
    session['session_id'] = str(uuid.uuid4())
    sessionData[session['session_id']] = {'page_size': 10,
                                          'page': 1,
                                          'login': False,
                                          'locale': 'ru',
                                          'sort': '',
                                          'distance_strict': False,
                                          'last_sent_num': -1,
                                          'last_query': {},
                                          'seed': random.randint(1, 1e6),
                                          'excluded_doc_ids': set(),
                                          'progress': 100}


def get_session_data(fieldName):
    """
    Get the value of the fieldName parameter for the current session.
    If the session has not yet been initialized, initialize it first.
    If the parameter is supported, but not in the session dictionary,
    initialize the parameter first.
    """
    global sessionData
    if 'session_id' not in session:
        initialize_session()
    if session['session_id'] not in sessionData:
        sessionData[session['session_id']] = {}
    if (fieldName == 'login'
            and fieldName not in sessionData[session['session_id']]):
        sessionData[session['session_id']]['login'] = False
    elif (fieldName == 'locale'
          and fieldName not in sessionData[session['session_id']]):
        sessionData[session['session_id']]['locale'] = 'ru'
    elif (fieldName == 'page_size'
          and fieldName not in sessionData[session['session_id']]):
        sessionData[session['session_id']]['page_size'] = 10
    elif (fieldName == 'last_sent_num'
          and fieldName not in sessionData[session['session_id']]):
        sessionData[session['session_id']]['last_sent_num'] = -1
    elif (fieldName == 'seed'
          and fieldName not in sessionData[session['session_id']]):
        sessionData[session['session_id']]['seed'] = random.randint(1, 1e6)
    elif (fieldName == 'excluded_doc_ids'
          and fieldName not in sessionData[session['session_id']]):
        sessionData[session['session_id']]['excluded_doc_ids'] = set()
    elif (fieldName == 'progress'
          and fieldName not in sessionData[session['session_id']]):
        sessionData[session['session_id']]['progress'] = 0
    elif fieldName not in sessionData[session['session_id']]:
        sessionData[session['session_id']][fieldName] = ''
    try:
        dictCurData = sessionData[session['session_id']]
        requestedValue = dictCurData[fieldName]
        return requestedValue
    except KeyError:
        return None


def set_session_data(fieldName, value):
    """
    Set the value of the fieldName parameter for the current session.
    If the session has not yet been initialized, initialize it first.
    """
    global sessionData
    if 'session_id' not in session:
        initialize_session()
    if session['session_id'] not in sessionData:
        sessionData[session['session_id']] = {}
    sessionData[session['session_id']][fieldName] = value


def in_session(fieldName):
    """
    Check if the fieldName parameter exists in the dictionary with
    parameters for the current session.
    """
    global sessionData
    if 'session_id' not in session:
        return False
    return fieldName in sessionData[session['session_id']]


def get_locale():
    return 'ru'  # get_session_data('locale')


def change_display_options(query):
    """
    Remember the new display options provided in the query.
    """
    if 'page_size' in query:
        try:
            ps = int(query['page_size'])
            if ps > MAX_PAGE_SIZE:
                ps = MAX_PAGE_SIZE
            elif ps < 1:
                ps = 1
            set_session_data('page_size', ps)
        except (ValueError, TypeError, KeyError):
            set_session_data('page_size', 10)
    if 'sort' in query:
        set_session_data('sort', query['sort'])
    if 'distance_strict' in query:
        set_session_data('distance_strict', True)
    else:
        set_session_data('distance_strict', False)
    if 'translit' in query:
        set_session_data('translit', query['translit'])
    else:
        set_session_data('translit', None)
    if ('random_seed' in query
            and re.search('^[1-9][0-9]*', query['random_seed']) is not None
            and 0 < int(query['random_seed']) < 1000000):
        set_session_data('seed', int(query['random_seed']))


def add_sent_data_for_session(sent, sentData):
    """
    Add information about one particluar sentence to the
    sentData dictionary for storing in the session data
    dictionary.
    Modify sentData, do not return anything.
    """
    if len(sentData) <= 0:
        docID = -1
        if '_source' in sent:
            docID = sent['_source']['doc_id']
        sentData.update({'languages': {},
                         'doc_id': docID,
                         'times_expanded': 0,
                         'src_alignment_files': [],
                         'header_csv': ''})
    langID = 0
    nextID = prevID = -1
    highlightedText = ''
    if '_source' in sent:
        if 'next_id' in sent['_source']:
            nextID = sent['_source']['next_id']
        if 'prev_id' in sent['_source']:
            prevID = sent['_source']['prev_id']
        if len(sentData['header_csv']) <= 0:
            sentData['header_csv'] = sentView.process_sentence_header(
                sent['_source'], format='csv')
        if 'lang' in sent['_source']:
            langID = sent['_source']['lang']
            highlightedText = sentView.process_sentence_csv(
                sent, lang=settings['languages'][langID],
                translit=get_session_data('translit'))
        lang = settings['languages'][langID]
        if lang not in sentData['languages']:
            sentData['languages'][lang] = {'id': sent['_id'],
                                           'next_id': nextID,
                                           'prev_id': prevID,
                                           'highlighted_text': highlightedText}
        else:
            if ('next_id' not in sentData['languages'][lang]
                    or nextID == -1
                    or nextID > sentData['languages'][lang]['next_id']):
                sentData['languages'][lang]['next_id'] = nextID
            if ('prev_id' not in sentData['languages'][lang]
                    or prevID < sentData['languages'][lang]['prev_id']):
                sentData['languages'][lang]['prev_id'] = prevID
        if 'src_alignment' in sent['_source']:
            for alignment in sent['_source']['src_alignment']:
                if alignment['src'] not in sentData['src_alignment_files']:
                    sentData['src_alignment_files'].append(alignment['src'])


def add_sent_to_session(hits):
    """
    Store the ids of the currently viewed sentences in the
    session data dictionary, so that the user can later ask
    for expanded context.
    """
    if 'hits' not in hits or 'hits' not in hits['hits']:
        return
    curSentIDs = []
    set_session_data('last_sent_num', len(hits['hits']['hits']) - 1)
    for sent in hits['hits']['hits']:
        curSentID = {}
        add_sent_data_for_session(sent, curSentID)
        curSentIDs.append(curSentID)
    set_session_data('sentence_data', curSentIDs)


def get_page_data(hitsProcessed):
    """
    Extract all relevant information from the processed hits
    of one results page. Return a list of dictionaries, one dictionary
    per result sentence.
    """
    result = []
    curSentData = get_session_data('sentence_data')
    if (curSentData is None
            or len(curSentData) != len(hitsProcessed['contexts'])):
        return [{}] * len(hitsProcessed['contexts'])
    for iHit in range(len(hitsProcessed['contexts'])):
        hit = hitsProcessed['contexts'][iHit]
        sentPageDataDict = {'toggled_off': False,
                            'highlighted_text_csv': [],
                            'header_csv': ''}
        if not hit['toggled_on']:
            sentPageDataDict['toggled_off'] = True
        for lang in settings['languages']:
            if lang not in curSentData[iHit]['languages']:
                sentPageDataDict['highlighted_text_csv'].append('')
            else:
                sentPageDataDict['highlighted_text_csv'].append(
                    curSentData[iHit]['languages'][lang]['highlighted_text'])
            if 'header_csv' in curSentData[iHit]:
                sentPageDataDict['header_csv'] = (
                    curSentData[iHit]['header_csv'])
        result.append(sentPageDataDict)
    return result


def sync_page_data(page, hitsProcessed):
    """
    If the user is going to see this page for the first time,
    add relevant information to page_data. Otherwise, toggle on/off
    the sentences according to the previously saved page data.
    """
    pageData = get_session_data('page_data')
    if (pageData is not None and page in pageData
            and 'contexts' in hitsProcessed
            and len(hitsProcessed['contexts']) == len(pageData[page])):
        for iHit in range(len(hitsProcessed['contexts'])):
            if pageData[page][iHit]['toggled_off']:
                hitsProcessed['contexts'][iHit]['toggled_on'] = False
            else:
                hitsProcessed['contexts'][iHit]['toggled_on'] = True
    elif pageData is None:
        pageData = {}
    curPageData = get_page_data(hitsProcessed)
    pageData[page] = curPageData


def update_expanded_contexts(context, neighboringIDs):
    """
    Update the session data dictionary with the expanded
    context data.
    """
    curSentIDs = get_session_data('sentence_data')
    if (curSentIDs is None
            or 'n' not in context
            or context['n'] < 0
            or context['n'] >= len(curSentIDs)):
        return
    curSent = curSentIDs[context['n']]
    curSent['times_expanded'] += 1
    for lang in curSent['languages']:
        for side in ['next', 'prev']:
            if (side in context['languages'][lang]
                    and len(context['languages'][lang][side]) > 0):
                curSent['languages'][lang][side + '_id'] = (
                    neighboringIDs[lang][side])


@app.route('/search')
def search_page():
    """
    Return HTML of the search page (the main page of the corpus).
    """
    allLangSearch = settings['all_language_search_enabled']
    transliterations = None
    if 'input_methods' in settings:
        inputMethods = settings['input_methods']
    else:
        inputMethods = None
    mediaYoutube = False
    return render_template('search.html',
                           corpus_name=corpus_name,
                           languages=settings['languages'],
                           all_lang_search=allLangSearch,
                           transliterations=transliterations,
                           input_methods=inputMethods,
                           media=settings['media'],
                           youtube=mediaYoutube,
                           gloss_search_enabled=(
                               settings['gloss_search_enabled']),
                           debug=settings['debug'],
                           subcorpus_selection=settings['search_meta'],
                           max_request_time=settings['query_timeout'] + 1,
                           locales=settings['interface_languages'],
                           random_seed=get_session_data('seed'))


@app.route('/search_sent_query/<int:page>')
@app.route('/search_sent_query')
@jsonp
def search_sent_query(page=0):
    if not settings['debug']:
        return jsonify({})
    if request.args and page <= 0:
        query = copy_request_args()
        page = 1
        change_display_options(query)
        set_session_data('last_query', query)
    else:
        query = get_session_data('last_query')
    set_session_data('page', page)
    wordConstraints = sc.qp.wr.get_constraints(query)
    # wordConstraintsPrint = {str(k): v for k, v in wordConstraints.items()}

    if 'para_ids' not in query:
        query, paraIDs = para_ids(query)
        if paraIDs is not None:
            query['para_ids'] = list(paraIDs)

    if (len(wordConstraints) > 0
            and get_session_data('distance_strict')
            and 'sent_ids' not in query
            and distance_constraints_too_complex(wordConstraints)):
        esQuery = sc.qp.html2es(query,
                                searchOutput='sentences',
                                query_size=1,
                                distances=wordConstraints)
        hits = sc.get_sentences(esQuery)
        if ('hits' not in hits
                or 'total' not in hits['hits']
                or hits['hits']['total'] > settings['max_distance_filter']):
            esQuery = {}
        else:
            esQuery = sc.qp.html2es(query,
                                    searchOutput='sentences',
                                    distances=wordConstraints)
    else:
        esQuery = sc.qp.html2es(query,
                                searchOutput='sentences',
                                sortOrder=get_session_data('sort'),
                                randomSeed=get_session_data('seed'),
                                query_size=get_session_data('page_size'),
                                page=get_session_data('page'),
                                distances=wordConstraints)
    return jsonify(esQuery)


def find_parallel_for_one_sent(sSource):
    """
    Retrieve all sentences in other languages which are aligned
    with the given sentence. Return the search results in JSON.
    """
    sids = set()
    for pa in sSource['para_alignment']:
        sids |= set(pa['sent_ids'])
    sids = list(sid for sid in sorted(sids))
    query = {'query': {'ids': {'values': sids}}}
    paraSentHits = sc.get_sentences(query)
    if 'hits' in paraSentHits and 'hits' in paraSentHits['hits']:
        return paraSentHits['hits']['hits']
    return []


def get_parallel_for_one_sent_html(sSource, numHit):
    """
    Iterate over HTML strings with sentences in other languages
    aligned with the given sentence.
    """
    curSentIDs = get_session_data('sentence_data')
    for s in find_parallel_for_one_sent(sSource):
        numSent = get_session_data('last_sent_num') + 1
        set_session_data('last_sent_num', numSent)
        add_sent_data_for_session(s, curSentIDs[numHit])
        langID = s['_source']['lang']
        lang = settings['languages'][langID]
        sentHTML = sentView.process_sentence(
            s, numSent=numSent, getHeader=False, lang=lang,
            translit=get_session_data('translit'))['languages'][lang]['text']
        yield sentHTML, lang


def add_parallel(hits, htmlResponse):
    """
    Add HTML of fragments in other languages aligned with the current
    search results to the response.
    """
    for iHit in range(len(hits)):
        if ('para_alignment' not in hits[iHit]['_source']
                or len(hits[iHit]['_source']['para_alignment']) <= 0):
            continue
        for sentHTML, lang in get_parallel_for_one_sent_html(
                hits[iHit]['_source'], iHit):
            try:
                htmlResponse['contexts'][iHit]['languages'][lang]['text'] += (
                        ' ' + sentHTML)
            except KeyError:
                htmlResponse['contexts'][iHit]['languages'][lang] = {
                    'text': sentHTML}


def get_buckets_for_metafield(
        fieldName, langID=-1, docIDs=None, maxBuckets=300):
    """
    Group all documents into buckets, each corresponding to one
    of the unique values for the fieldName metafield. Consider
    only top maxBuckets field values (in terms of document count).
    If langID is provided, count only data for a particular language.
    Return a dictionary with the values and corresponding document
    count.
    """
    if (fieldName not in settings['search_meta']['stat_options']
            or langID >= len(settings['languages']) > 1):
        return {}
    innerQuery = {'match_all': {}}
    if docIDs is not None:
        innerQuery = {'ids': {'type': 'doc', 'values': list(docIDs)}}
    if not fieldName.startswith('year'):
        queryFieldName = fieldName + '_kw'
    else:
        queryFieldName = fieldName
    if len(settings['languages']) == 1 or langID < 0:
        nWordsFieldName = 'n_words'
        nSentsFieldName = 'n_sents'
    else:
        nWordsFieldName = 'n_words_' + settings['languages'][langID]
        nSentsFieldName = 'n_sents_' + settings['languages'][langID]
    esQuery = {'query': innerQuery,
               'size': 0,
               'aggs': {
                   'metafield': {
                       'terms': {'field': queryFieldName, 'size': maxBuckets},
                       'aggs': {
                           'subagg_n_words': {
                               'sum': {'field': nWordsFieldName}},
                           'subagg_n_sents': {
                               'sum': {'field': nSentsFieldName}}}}
               }
               }
    hits = sc.get_docs(esQuery)
    if 'aggregations' not in hits or 'metafield' not in hits['aggregations']:
        return {}
    buckets = []
    for bucket in hits['aggregations']['metafield']['buckets']:
        bucketListItem = {'name': bucket['key'],
                          'n_docs': bucket['doc_count'],
                          'n_words': bucket['subagg_n_words']['value']}
        buckets.append(bucketListItem)
    if not fieldName.startswith('year'):
        buckets.sort(key=lambda b: (-b['n_words'], -b['n_docs'], b['name']))
    else:
        buckets.sort(key=lambda b: b['name'])
    if len(buckets) > 25 and not fieldName.startswith('year'):
        bucketsFirst = buckets[:25]
        lastBucket = {'name': '>>', 'n_docs': 0, 'n_words': 0}
        for i in range(25, len(buckets)):
            lastBucket['n_docs'] += buckets[i]['n_docs']
            lastBucket['n_words'] += buckets[i]['n_words']
        bucketsFirst.append(lastBucket)
        buckets = bucketsFirst
    return buckets


@app.route('/doc_stats/<metaField>')
def get_doc_stats(metaField):
    """
    Return JSON with basic statistics concerning the distribution
    of corpus documents by values of one metafield. This function
    can be used to visualise (sub)corpus composition.
    """
    if metaField not in settings['search_meta']['stat_options']:
        return jsonify({})
    query = copy_request_args()
    change_display_options(query)
    docIDs = subcorpus_ids(query)
    buckets = get_buckets_for_metafield(metaField, langID=-1, docIDs=docIDs)
    return jsonify(buckets)


def subcorpus_ids(htmlQuery):
    """
    Return IDs of the documents specified by the subcorpus selection
    fields in htmlQuery.
    """
    subcorpusQuery = sc.qp.subcorpus_query(
        htmlQuery, sortOrder='',
        exclude=get_session_data('excluded_doc_ids'))
    if subcorpusQuery is None or (
            'query' in subcorpusQuery
            and subcorpusQuery['query'] == {'match_all': {}}):
        return None
    iterator = sc.get_all_docs(subcorpusQuery)
    docIDs = []
    for doc in iterator:
        docIDs.append(doc['_id'])
    return docIDs


def para_ids(htmlQuery):
    """
    If the query contains parts for several languages, find para_ids associated
    with the sentences in non-first languages that conform to the corresponding
    parts of the query.
    Return the query for the first language and para_ids
    conforming to the other parts of the query.
    """
    langQueryParts = sc.qp.split_query_into_languages(htmlQuery)
    if langQueryParts is None or len(langQueryParts) <= 1:
        return htmlQuery, None
    paraIDs = None
    for i in range(1, len(langQueryParts)):
        lpHtmlQuery = langQueryParts[i]
        paraIDQuery = sc.qp.para_id_query(lpHtmlQuery)
        if paraIDQuery is None:
            return None
        curParaIDs = set()
        iterator = sc.get_all_sentences(paraIDQuery)
        for dictParaID in iterator:
            if '_source' not in dictParaID \
                    or 'para_ids' not in dictParaID['_source']:
                continue
            for paraID in dictParaID['_source']['para_ids']:
                curParaIDs.add(paraID)
        if paraIDs is None:
            paraIDs = curParaIDs
        else:
            paraIDs &= curParaIDs
        if len(paraIDs) <= 0:
            return langQueryParts[0], list(paraIDs)
    return langQueryParts[0], list(paraIDs)


def copy_request_args():
    """
    Copy the reauest arguments from request.args to a
    normal modifiable dictionary. Return the dictionary.
    If input method is specified, change the values using
    the relevant transliteration function.
    """
    query = {}
    if request.args is None or len(request.args) <= 0:
        return query
    input_translit_func = lambda f, t, l: t  # noqa
    if 'input_method' in request.args \
            and len(request.args['input_method']) > 0:
        translitFuncName = 'input_method_' + request.args['input_method']
        localNames = globals()
        if translitFuncName in localNames:
            input_translit_func = localNames[translitFuncName]
    for field, value in request.args.items():
        if type(value) != list or len(value) > 1:
            query[field] = copy.deepcopy(value)
            if type(value) == str:
                mFieldNum = sc.qp.rxFieldNum.search(field)
                if mFieldNum is None:
                    continue
                if 'lang' + mFieldNum.group(2) not in request.args:
                    continue
                lang = request.args['lang' + mFieldNum.group(2)]
                query[field] = input_translit_func(
                    mFieldNum.group(1), query[field], lang)
        else:
            query[field] = copy.deepcopy(value[0])
    if 'sent_ids' in query:
        del query['sent_ids']  # safety
    return query


def count_occurrences(query, distances=None):
    esQuery = sc.qp.html2es(query,
                            searchOutput='sentences',
                            sortOrder='no',
                            query_size=1,
                            distances=distances)
    hits = sc.get_sentences(esQuery)
    if ('aggregations' in hits
            and 'agg_nwords' in hits['aggregations']
            and hits['aggregations']['agg_nwords']['sum'] is not None):
        return int(math.floor(hits['aggregations']['agg_nwords']['sum']))
    return 0


def distance_constraints_too_complex(wordConstraints):
    """
    Decide if the constraints on the distances between pairs
    of search terms are too complex, i. e. if there is no single word
    that all pairs include. If the constraints are too complex
    and the "distance requirements are strict" flag is set,
    the query will find some invalid results, so further (slow)
    post-filtering is needed.
    """
    if wordConstraints is None or len(wordConstraints) <= 0:
        return False
    commonTerms = None
    for wordPair in wordConstraints:
        if commonTerms is None:
            commonTerms = set(wordPair)
        else:
            commonTerms &= set(wordPair)
        if len(commonTerms) <= 0:
            return True
    return False


def find_sentences_json(page=0):
    """
    Find sentences and change current options using the query in request.args.
    """
    if request.args and page <= 0:
        query = copy_request_args()
        page = 1
        change_display_options(query)
        if get_session_data('sort') not in ('random', 'freq'):
            set_session_data('sort', 'random')
        set_session_data('last_query', query)
        wordConstraints = sc.qp.wr.get_constraints(query)
        set_session_data('word_constraints', wordConstraints)
    else:
        query = get_session_data('last_query')
        wordConstraints = get_session_data('word_constraints')
    set_session_data('page', page)

    nWords = 1
    negWords = []
    if 'n_words' in query:
        nWords = int(query['n_words'])
        if nWords > 0:
            for iQueryWord in range(1, nWords + 1):
                if ('negq' + str(iQueryWord) in query) \
                        and query['negq' + str(iQueryWord)] == 'on':
                    negWords.append(iQueryWord)

    docIDs = None
    if 'doc_ids' not in query and 'sent_ids' not in query:
        docIDs = subcorpus_ids(query)
        if docIDs is not None:
            query['doc_ids'] = docIDs

    if 'para_ids' not in query:
        query, paraIDs = para_ids(query)
        if paraIDs is not None:
            query['para_ids'] = paraIDs

    if (len(wordConstraints) > 0
            and get_session_data('distance_strict')
            and 'sent_ids' not in query
            and distance_constraints_too_complex(wordConstraints)):
        esQuery = sc.qp.html2es(query,
                                searchOutput='sentences',
                                query_size=1,
                                distances=wordConstraints)
        hits = sc.get_sentences(esQuery)
        if ('hits' not in hits
                or 'total' not in hits['hits']
                or hits['hits']['total'] > settings['max_distance_filter']):
            query = {}
        else:
            esQuery = sc.qp.html2es(query,
                                    searchOutput='sentences',
                                    distances=wordConstraints)
            if '_source' not in esQuery:
                esQuery['_source'] = {}
            # esQuery['_source']['excludes'] = ['words.ana', 'words.wf']
            esQuery['_source'] = ['words.next_word', 'words.wtype']
            # TODO: separate threshold for this?
            iterator = sc.get_all_sentences(esQuery)
            query['sent_ids'] = sc.qp.filter_sentences(
                iterator, wordConstraints, nWords=nWords)
            set_session_data('last_query', query)

    queryWordConstraints = None
    if (len(wordConstraints) > 0
            and get_session_data('distance_strict')):
        queryWordConstraints = wordConstraints

    nOccurrences = 0
    if (get_session_data('sort') in ('random', 'freq')
            and (nWords == 1
                 or len(wordConstraints) <= 0
                 or not distance_constraints_too_complex(wordConstraints))):
        nOccurrences = count_occurrences(query, distances=queryWordConstraints)

    esQuery = sc.qp.html2es(query,
                            searchOutput='sentences',
                            sortOrder=get_session_data('sort'),
                            randomSeed=get_session_data('seed'),
                            query_size=get_session_data('page_size'),
                            page=get_session_data('page'),
                            distances=queryWordConstraints)

    # return esQuery
    hits = sc.get_sentences(esQuery)
    if nWords > 1 and 'hits' in hits and 'hits' in hits['hits']:
        for hit in hits['hits']['hits']:
            sentView.filter_multi_word_highlight(
                hit, nWords=nWords, negWords=negWords)
    if 'aggregations' in hits and 'agg_nwords' in hits['aggregations']:
        if nOccurrences > 0:
            hits['aggregations']['agg_nwords']['sum'] = nOccurrences
            # hits['aggregations']['agg_nwords']['count'] = 0
        elif ('n_words' in query and query['n_words'] == 1
              and 'sum' in hits['aggregations']['agg_nwords']):
            # only count number of occurrences for one-word queries
            hits['aggregations']['agg_nwords']['sum'] = 0
    if (len(wordConstraints) > 0
            and (not get_session_data('distance_strict')
                 or distance_constraints_too_complex(wordConstraints))
            and 'hits' in hits and 'hits' in hits['hits']):
        for hit in hits['hits']['hits']:
            hit['toggled_on'] = sc.qp.wr.check_sentence(
                hit, wordConstraints, nWords=nWords)
    if docIDs is not None and len(docIDs) > 0:
        hits['subcorpus_enabled'] = True
    return hits


def remove_sensitive_data(hits):
    """
    Remove data that should not be shown to the user, i.e. the ids
    of the sentences (the user can use this information to download
    the whole corpus if the sentences are numbered consecutively,
    which is actually not the case, but still).
    Change the hits dictionary, do not return anything.
    """
    if type(hits) != dict or 'hits' not in hits or 'hits' not in hits['hits']:
        return
    for hit in hits['hits']['hits']:
        if '_id' in hit:
            del hit['_id']
        if '_source' in hit:
            if 'prev_id' in hit['_source']:
                del hit['_source']['prev_id']
            if 'next_id' in hit['_source']:
                del hit['_source']['next_id']


@app.route('/search_sent_json/<int:page>')
@app.route('/search_sent_json')
@jsonp
def search_sent_json(page=-1):
    if page < 0:
        set_session_data('page_data', {})
        page = 0
    hits = find_sentences_json(page=page)
    remove_sensitive_data(hits)
    return jsonify(hits)


@app.route('/search_sent/<int:page>')
@app.route('/search_sent')
@gzipped
def search_sent(page=-1):
    if page < 0:
        set_session_data('page_data', {})
        page = 0
    # try:
    hits = find_sentences_json(page=page)
    # except:
    #     return render_template(
    #     'result_sentences.html', message='Request timeout.')
    add_sent_to_session(hits)
    hitsProcessed = sentView.process_sent_json(
        hits,
        translit=get_session_data('translit'))
    if len(settings['languages']) > 1 \
            and 'hits' in hits \
            and 'hits' in hits['hits']:
        add_parallel(hits['hits']['hits'], hitsProcessed)
    hitsProcessed['page'] = get_session_data('page')
    hitsProcessed['page_size'] = get_session_data('page_size')
    hitsProcessed['languages'] = settings['languages']
    hitsProcessed['media'] = settings['media']
    hitsProcessed['subcorpus_enabled'] = False
    if 'subcorpus_enabled' in hits:
        hitsProcessed['subcorpus_enabled'] = True
    sync_page_data(hitsProcessed['page'], hitsProcessed)

    return render_template(
        'tsa_blocks/result_sentences.html', data=hitsProcessed
    )


@app.route('/get_sent_context/<int:n>')
@jsonp
def get_sent_context(n):
    """
    Retrieve the neighboring sentences for the currently
    viewed sentence number n. Take into account how many
    times this particular context has been expanded and
    whether expanding it further is allowed.
    """
    if n < 0:
        return jsonify({})
    sentData = get_session_data('sentence_data')
    # return jsonify({"l": len(sentData), "i": sentData[n]})
    if sentData is None \
            or n >= len(sentData) \
            or 'languages' not in sentData[n]:
        return jsonify({})
    curSentData = sentData[n]
    if curSentData['times_expanded'] >= settings['max_context_expand']:
        return jsonify({})
    context = {
        'n': n,
        'languages': {
            lang: {}
            for lang in curSentData['languages']
        },
        'src_alignment': {}
    }
    neighboringIDs = {
        lang: {'next': -1, 'prev': -1}
        for lang in curSentData['languages']
    }
    for lang in curSentData['languages']:
        langID = settings['languages'].index(lang)
        for side in ['next', 'prev']:
            curCxLang = context['languages'][lang]
            if side + '_id' in curSentData['languages'][lang]:
                curCxLang[side] = sc.get_sentence_by_id(
                    curSentData['languages'][lang][side + '_id'])
            if (side in curCxLang
                    and len(curCxLang[side]) > 0
                    and 'hits' in curCxLang[side]
                    and 'hits' in curCxLang[side]['hits']
                    and len(curCxLang[side]['hits']['hits']) > 0):
                lastSentNum = get_session_data('last_sent_num') + 1
                curSent = curCxLang[side]['hits']['hits'][0]
                if '_source' in curSent and (
                        'lang' not in curSent['_source']
                        or curSent['_source']['lang'] != langID):
                    curCxLang[side] = ''
                    continue
                if ('_source' in curSent) \
                        and (side + '_id' in curSent['_source']):
                    neighboringIDs[lang][side] = (
                        curSent['_source'][side + '_id'])
                expandedContext = sentView.process_sentence(
                    curSent,
                    numSent=lastSentNum,
                    getHeader=False,
                    lang=lang,
                    translit=get_session_data('translit'))
                curCxLang[side] = expandedContext['languages'][lang]['text']
                if settings['media']:
                    sentView.relativize_src_alignment(
                        expandedContext, curSentData['src_alignment_files'])
                    context['src_alignment'].update(
                        expandedContext['src_alignment'])
                set_session_data('last_sent_num', lastSentNum)
            else:
                curCxLang[side] = ''
    update_expanded_contexts(context, neighboringIDs)
    return jsonify(context)


@app.route('/search_lemma_query')
@jsonp
def search_lemma_query():
    return search_word_query(searchType='lemma')


@app.route('/search_word_query')
@jsonp
def search_word_query(searchType='word'):
    if not settings['debug']:
        return jsonify({})
    query = copy_request_args()
    change_display_options(query)
    if 'doc_ids' not in query:
        docIDs = subcorpus_ids(query)
        if docIDs is not None:
            query['doc_ids'] = docIDs
    else:
        docIDs = query['doc_ids']
    sortOrder = get_session_data('sort')
    queryWordConstraints = None
    if 'n_words' in query and int(query['n_words']) > 1:
        sortOrder = 'random'
        # in this case, the words are sorted after the search
        wordConstraints = sc.qp.wr.get_constraints(query)
        set_session_data('word_constraints', wordConstraints)
        if (len(wordConstraints) > 0
                and get_session_data('distance_strict')):
            queryWordConstraints = wordConstraints

    query = sc.qp.html2es(query,
                          searchOutput='words',
                          sortOrder=sortOrder,
                          randomSeed=get_session_data('seed'),
                          query_size=get_session_data('page_size'),
                          distances=queryWordConstraints)
    if searchType == 'lemma':
        sc.qp.lemmatize_word_query(query)
    return jsonify(query)


@app.route('/search_lemma_json')
@jsonp
def search_lemma_json():
    return search_word_json(searchType='lemma')


@app.route('/search_word_json')
@jsonp
def search_word_json(searchType='word'):
    query = copy_request_args()
    change_display_options(query)
    if 'doc_ids' not in query:
        docIDs = subcorpus_ids(query)
        if docIDs is not None:
            query['doc_ids'] = docIDs
    else:
        docIDs = query['doc_ids']

    searchIndex = 'words'
    sortOrder = get_session_data('sort')
    queryWordConstraints = None
    if 'n_words' in query and int(query['n_words']) > 1:
        searchIndex = 'sentences'
        sortOrder = 'random'
        # in this case, the words are sorted after the search
        wordConstraints = sc.qp.wr.get_constraints(query)
        set_session_data('word_constraints', wordConstraints)
        if (len(wordConstraints) > 0
                and get_session_data('distance_strict')):
            queryWordConstraints = wordConstraints
    elif 'sentence_index1' in query and len(query['sentence_index1']) > 0:
        searchIndex = 'sentences'
        sortOrder = 'random'

    query = sc.qp.html2es(query,
                          searchOutput='words',
                          sortOrder=sortOrder,
                          randomSeed=get_session_data('seed'),
                          query_size=get_session_data('page_size'),
                          distances=queryWordConstraints)

    hits = []
    if searchIndex == 'words':
        if docIDs is None:
            if searchType == 'lemma':
                sc.qp.lemmatize_word_query(query)
                hits = sc.get_lemmata(query)
            else:
                hits = sc.get_words(query)
        else:
            hits = sc.get_word_freqs(query)
    elif searchIndex == 'sentences':
        iSent = 0
        for hit in sc.get_all_sentences(query):
            if iSent >= 5:
                break
            iSent += 1
            hits.append(hit)

    return jsonify(hits)


@app.route('/search_lemma')
def search_lemma():
    return search_word(searchType='lemma')


@app.route('/search_word')
def search_word(searchType='word'):
    set_session_data('progress', 0)
    query = copy_request_args()
    change_display_options(query)
    if 'doc_ids' not in query:
        docIDs = subcorpus_ids(query)
        if docIDs is not None:
            query['doc_ids'] = docIDs
    else:
        docIDs = query['doc_ids']

    searchIndex = 'words'
    sortOrder = get_session_data('sort')
    wordConstraints = None
    queryWordConstraints = None
    constraintsTooComplex = False
    nWords = 1
    if 'n_words' in query and int(query['n_words']) > 1:
        nWords = int(query['n_words'])
        searchIndex = 'sentences'
        sortOrder = 'random'
        # in this case, the words are sorted after the search
        wordConstraints = sc.qp.wr.get_constraints(query)
        set_session_data('word_constraints', wordConstraints)
        if (len(wordConstraints) > 0
                and get_session_data('distance_strict')):
            queryWordConstraints = wordConstraints
            if distance_constraints_too_complex(wordConstraints):
                constraintsTooComplex = True
    elif 'sentence_index1' in query and len(query['sentence_index1']) > 0:
        searchIndex = 'sentences'
        sortOrder = 'random'

    query = sc.qp.html2es(query,
                          searchOutput='words',
                          sortOrder=sortOrder,
                          randomSeed=get_session_data('seed'),
                          query_size=get_session_data('page_size'),
                          distances=queryWordConstraints,
                          includeNextWordField=constraintsTooComplex)

    maxRunTime = time.time() + settings['query_timeout']
    hitsProcessed = {}
    if searchIndex == 'words':
        if docIDs is None:
            if searchType == 'lemma':
                sc.qp.lemmatize_word_query(query)
                hits = sc.get_lemmata(query)
            else:
                hits = sc.get_words(query)
            hitsProcessed = sentView.process_word_json(
                hits, docIDs,
                searchType=searchType,
                translit=get_session_data('translit'))
        else:
            hits = sc.get_word_freqs(query)
            hitsProcessed = sentView.process_word_subcorpus_json(
                hits, docIDs,
                translit=get_session_data('translit'))

    elif searchIndex == 'sentences':
        hitsProcessed = {'n_occurrences': 0, 'n_sentences': 0, 'n_docs': 0,
                         'total_freq': 0,
                         'words': [], 'doc_ids': set(), 'word_ids': {}}
        for hit in sc.get_all_sentences(query):
            if constraintsTooComplex:
                if not sc.qp.wr.check_sentence(
                        hit, wordConstraints, nWords=nWords
                ):
                    continue
            sentView.add_word_from_sentence(hitsProcessed, hit, nWords=nWords)
            if (hitsProcessed['total_freq'] >= 2000) \
                    and (time.time() > maxRunTime):
                hitsProcessed['timeout'] = True
                break
        hitsProcessed['n_docs'] = len(hitsProcessed['doc_ids'])
        if hitsProcessed['n_docs'] > 0:
            sentView.process_words_collected_from_sentences(
                hitsProcessed,
                sortOrder=get_session_data('sort'),
                pageSize=get_session_data('page_size'))

    hitsProcessed['media'] = settings['media']
    set_session_data('progress', 100)
    return render_template('tsa_blocks/result_words.html', data=hitsProcessed)


@app.route('/search_doc_query')
@jsonp
def search_doc_query():
    if not settings['debug']:
        return jsonify({})
    query = copy_request_args()
    change_display_options(query)
    query = sc.qp.subcorpus_query(query,
                                  sortOrder=get_session_data('sort'),
                                  query_size=settings['max_docs_retrieve'])
    return jsonify(query)


@app.route('/get_word_fields')
def get_word_fields():
    """
    Return HTML with form inputs representing all additional
    word-level annotation fields.
    """
    result = ''
    wordFields = None
    sentMeta = None
    if 'word_fields' in settings and len(settings['word_fields']) > 0:
        wordFields = settings['word_fields']
    if 'sentence_meta' in settings and len(settings['sentence_meta']) > 0:
        sentMeta = settings['sentence_meta']
    result += render_template(
        'tsa_blocks/common_additional_search_fields.html',
        word_fields=wordFields,
        sentence_meta=sentMeta,
        ambiguous_analyses=settings['ambiguous_analyses'])
    return result
