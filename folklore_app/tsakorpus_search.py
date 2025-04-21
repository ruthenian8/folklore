# Originally taken from https://bitbucket.org/tsakorpus/tsakorpus/src/master/
# Originally taken from https://github.com/timarkh/tsakorpus

import functools
import gzip
import math

import uuid
from functools import wraps

from flask import (
    after_this_request,
    session,
    jsonify,
    current_app
)
import copy
import json
import os
import random
import re


from flask import render_template, request


from folklore_app.main_app import app
from folklore_app.settings import SETTINGS_DIR
from folklore_app.search_engine.response_processors import SentenceViewer
from folklore_app.search_engine.client import SearchClient

MAX_PAGE_SIZE = 100  # maximum number of sentences per page

with open(os.path.join(SETTINGS_DIR, 'corpus.json'),
          'r', encoding='utf-8') as f:
    settings = json.loads(f.read())


corpus_name = settings['corpus_name']
if settings['max_docs_retrieve'] >= 10000:
    settings['max_docs_retrieve'] = 9999

from folklore_app.search_engine.corpus_settings import CorpusSettings
st = CorpusSettings()
st.load_settings(os.path.join(SETTINGS_DIR, 'corpus.json'),
                       os.path.join(SETTINGS_DIR, 'categories.json'))

sc = SearchClient(SETTINGS_DIR, st)
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


# app.config.update(dict(
#     LANGUAGES=settings['interface_languages'],
#     BABEL_DEFAULT_LOCALE='ru'
# ))


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

    if (len(wordConstraints) > 0
            and get_session_data('distance_strict')
            and 'sent_ids' not in query):
            # and distance_constraints_too_complex(wordConstraints)):
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
                 or len(wordConstraints) <= 0)):
                 # or not distance_constraints_too_complex(wordConstraints))):
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
            and not get_session_data('distance_strict')
            and 'hits' in hits and 'hits' in hits['hits']):
        for hit in hits['hits']['hits']:
            hit['toggled_on'] = sc.qp.wr.check_sentence(
                hit, wordConstraints, nWords=nWords)
    if docIDs is not None and len(docIDs) > 0:
        hits['subcorpus_enabled'] = True
    return hits


@app.route('/search_sent/<int:page>')
@app.route('/search_sent')
@gzipped
def search_sent(page=-1):
    if page < 0:
        set_session_data('page_data', {})
        page = 0
    hits = find_sentences_json(page=page)
    add_sent_to_session(hits)
    hitsProcessed = sentView.process_sent_json(
        hits,
        translit=get_session_data('translit'))
    hitsProcessed['page'] = get_session_data('page')
    hitsProcessed['page_size'] = get_session_data('page_size')
    hitsProcessed['languages'] = settings['languages']
    hitsProcessed['media'] = settings['media']
    hitsProcessed['subcorpus_enabled'] = False
    hitsProcessed['n_sentences'] = hitsProcessed['n_sentences']['value']
    if 'subcorpus_enabled' in hits:
        hitsProcessed['subcorpus_enabled'] = True
    sync_page_data(hitsProcessed['page'], hitsProcessed)
    maxPageNumber = (min(hitsProcessed['n_sentences'], 1000) - 1) \
                    // hitsProcessed['page_size'] + 1
    hitsProcessed['too_many_hits'] = (1000 < hitsProcessed['n_sentences'])
    return render_template(
        'tsa_blocks/result_sentences.html',
        data=hitsProcessed,
        max_page_number=maxPageNumber
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
