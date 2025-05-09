import json
import re
import os
import math
from flask import render_template
from folklore_app.settings import LINK_PREFIX


class SentenceViewer:
    """
    Contains methods for turning the JSON response of ES into
    viewable html.
    """

    rxWordNo = re.compile('^w[0-9]+_([0-9]+)$')
    rxHitWordNo = re.compile('(?<=^w)[0-9]+')
    rxTextSpans = re.compile('</?span.*?>|[^<>]+', flags=re.DOTALL)
    invisibleAnaFields = {'gloss_index'}

    def __init__(self, settings_dir, search_client):
        self.settings_dir = settings_dir
        f = open(os.path.join(self.settings_dir, 'corpus.json'),
                 'r', encoding='utf-8')
        self.settings = json.loads(f.read())
        f.close()
        self.name = self.settings['corpus_name']
        self.sentence_props = ['text']
        self.sc = search_client
        self.w1_labels = set(['w1'] + [
            'w1_' + str(i)
            for i in range(self.settings['max_words_in_sentence'])
        ])

    def differing_ana_field(self, ana1, ana2):
        """
        Determine if two analyses with equal number of fields only differ
        in one field, with the possible exception of the gloss field.
        If they do, return the name of the field. If they do not differ
        at all, return empty string. If they have more than one
        differing fields, return None.
        """
        differingField = ''
        for key in ana1:
            if key not in ana2:
                return None
            if key in ('gloss', 'gloss_index'):
                continue
            if ana2[key] != ana1[key]:
                if len(differingField) > 0:
                    return None
                differingField = key
        return differingField

    def join_ana_gloss_variants(self, ana1, ana2):
        """
        Check if the gloss field values in the analyses differ only
        in one gloss. If so, return a string with joined glossing, e.g.
        (STEM-PL-GEN) + (STEM-SG-GEN) would give (STEM-PL/SG-GEN). If not,
        return None.
        """
        if 'gloss' not in ana1 or 'gloss' not in ana2:
            return None
        if ana1['gloss'] == ana2['gloss']:
            return ana1['gloss']
        glossParts1 = ana1['gloss'].split('-')
        glossParts2 = ana2['gloss'].split('-')
        if len(glossParts1) != len(glossParts2):
            return None
        nDifferences = 0
        joinedGloss = ''
        for iGloss in range(len(glossParts1)):
            if iGloss != 0:
                joinedGloss += '-'
            if glossParts1[iGloss] == glossParts2[iGloss]:
                joinedGloss += glossParts1[iGloss]
            else:
                if nDifferences >= 1:
                    return None
                nDifferences += 1
                newGlossPart = list(set(
                    glossParts1[iGloss].split('/') +
                    glossParts2[iGloss].split('/')))
                newGlossPart.sort()
                joinedGloss += '/'.join(newGlossPart)
        return joinedGloss

    def simplify_ana(self, analyses, matchingAnalyses):
        """
        Collate JSON analyses that only have differences in one field,
        e.g. [(N,sg,gen), (N,pl,gen)] -> (N,sg/pl,gen). Analyses that
        match the query (their indices are stored in matchingAnalyses)
        cannot be collated with those that do not.
        Return a list with simplified analyses and the matching analyses
        indices in the new list. The source list is changed in the process.
        """
        nAnalyses = len(analyses)
        simpleAnalyses = []
        simpleMatchingAnalyses = []
        usedAnalyses = []
        for i in range(nAnalyses):
            if i in usedAnalyses:
                continue
            for j in range(i + 1, nAnalyses):
                if j in usedAnalyses:
                    continue
                if i in matchingAnalyses and j not in matchingAnalyses:
                    continue
                if j in matchingAnalyses and i not in matchingAnalyses:
                    continue
                if len(analyses[i]) != len(analyses[j]):
                    continue
                differingField = self.differing_ana_field(
                    analyses[i], analyses[j])
                if (differingField is not None
                        and len(differingField) > 0
                        and differingField.startswith(('gr.', 'trans_'))
                        and type(analyses[i][differingField]) == str
                        and type(analyses[j][differingField]) == str):
                    if 'gloss' in analyses[i] or 'gloss' in analyses[j]:
                        joinedGloss = self.join_ana_gloss_variants(
                            analyses[i], analyses[j])
                        if joinedGloss is None:
                            continue
                        analyses[i]['gloss'] = joinedGloss
                    if differingField.startswith('gr.'):
                        separator = '/'
                    else:
                        separator = ' || '
                    values = list(set(
                        analyses[i][differingField].split(separator) +
                        analyses[j][differingField].split(separator)))
                    values.sort()
                    analyses[i][differingField] = separator.join(values)
                    usedAnalyses.append(j)
            simpleAnalyses.append(analyses[i])
            if i in matchingAnalyses:
                simpleMatchingAnalyses.append(len(simpleAnalyses) - 1)
        if len(simpleAnalyses) < len(analyses):
            # The procedure may require several recursive steps
            simpleAnalyses, simpleMatchingAnalyses = self.simplify_ana(
                simpleAnalyses, simpleMatchingAnalyses)
        return simpleAnalyses, simpleMatchingAnalyses

    def build_gr_ana_part(self, grValues, lang):
        """
        Build a string with gramtags ordered according to the settings
        for the language specified by lang.
        """
        sub_langs = self.settings['lang_props'][lang]['gr_fields_order']

        def key_comp(p):
            if p[0] not in sub_langs:
                return len(sub_langs)
            return sub_langs.index(p[0])

        grAnaPart = ''
        for fv in sorted(grValues, key=key_comp):
            if len(grAnaPart) > 0:
                grAnaPart += ', '
            grAnaPart += fv[1]
        return render_template(
            'tsa_blocks/grammar_popup.html', grAnaPart=grAnaPart).strip()

    def build_ana_div(self, ana, lang, translit=None):
        """
        Build the contents of a div with one particular analysis.
        """
        ana4template = {'lex': '', 'pos': '', 'gr': '', 'other_fields': []}
        if 'lex' in ana:
            ana4template['lex'] = self.transliterate_baseline(
                ana['lex'], lang=lang, translit=translit)
        if 'gr.pos' in ana:
            ana4template['pos'] = ana['gr.pos']
        grValues = []
        for field in sorted(ana):
            if (field not in ['lex', 'gr.pos']
                    and field not in self.invisibleAnaFields):
                value = ana[field]
                if type(value) == list:
                    value = ', '.join(value)
                if field.startswith('gr.'):
                    grValues.append((field[3:], value))
                else:
                    ana4template['other_fields'].append(
                        {'key': field, 'value': value})
        ana4template['gr'] = self.build_gr_ana_part(grValues, lang)
        return render_template(
            'tsa_blocks/analysis_div.html', ana=ana4template).strip()

    def build_ana_popup(
            self, word, lang, matchingAnalyses=None, translit=None):
        """
        Build a string for a popup with the word and its analyses.
        """
        if matchingAnalyses is None:
            matchingAnalyses = []
        data4template = {'wf': '', 'analyses': []}
        if 'wf' in word:
            data4template['wf'] = self.transliterate_baseline(
                word['wf'], lang=lang, translit=translit)
        if 'ana' in word:
            simplifiedAnas, simpleMatchingAnalyses = self.simplify_ana(
                word['ana'], matchingAnalyses)
            for iAna in range(len(simplifiedAnas)):
                ana4template = {
                    'match': iAna in simpleMatchingAnalyses,
                    'ana_div': self.build_ana_div(
                        simplifiedAnas[iAna], lang, translit=translit)}
                data4template['analyses'].append(ana4template)
        return render_template(
            'tsa_blocks/analyses_popup.html', data=data4template)

    def prepare_analyses(
            self, words, indexes, lang, matchWordOffsets=None, translit=None):
        """
        Generate viewable analyses for the words with given indexes.
        """
        result = ''
        for iStr in indexes:
            mWordNo = self.rxWordNo.search(iStr)
            if mWordNo is None:
                continue
            i = int(mWordNo.group(1))
            if i < 0 or i >= len(words):
                continue
            word = words[i]
            if word['wtype'] != 'word':
                continue
            matchingAnalyses = []
            if matchWordOffsets is not None and iStr in matchWordOffsets:
                matchingAnalyses = [
                    offAna[1] for offAna in matchWordOffsets[iStr]]
            result += self.build_ana_popup(
                word, lang,
                matchingAnalyses=matchingAnalyses, translit=translit)
        return result

    def build_span(
            self, sentSrc, curWords, lang, matchWordOffsets, translit=None):
        curClass = ''
        if any(wn.startswith('w') for wn in curWords):
            curClass += ' word '
        if any(wn.startswith('p') for wn in curWords):
            curClass += ' para '
        if any(wn.startswith('src') for wn in curWords):
            curClass += ' src '
        curClass = curClass.lstrip()

        if 'word' in curClass:
            dataAna = self.prepare_analyses(
                sentSrc['words'], curWords,
                lang, matchWordOffsets,
                translit=translit
            ).replace('"', "&quot;").replace('<', '&lt;').replace('>', '&gt;')
        else:
            dataAna = ''

        def highlightClass(nWord):
            if nWord in matchWordOffsets:
                return ' wmatch' + ''.join(
                    ' wmatch_' + str(n)
                    for n in set(
                        anaOff[0] for anaOff in matchWordOffsets[nWord]
                    ))
            return ''

        spanStart = '<span class="' + curClass + \
                    ' '.join(wn + highlightClass(wn)
                             for wn in curWords) + '" data-ana="' +\
                    dataAna + '">'
        return spanStart

    def add_highlighted_offsets(self, offStarts, offEnds, text):
        """
        Find highlighted fragments in source text of the sentence
        and store their offsets in the respective lists.
        """
        indexSubtr = 0
        # <em>s that appeared due to highlighting should be subtracted
        for i in range(len(text) - 4):
            if text[i] != '<':
                continue
            if text[i:i+4] == '<em>':
                try:
                    offStarts[i - indexSubtr].add('smatch')
                except KeyError:
                    offStarts[i - indexSubtr] = {'smatch'}
                indexSubtr += 4
            elif text[i:i+5] == '</em>':
                try:
                    offEnds[i - indexSubtr].add('smatch')
                except KeyError:
                    offEnds[i - indexSubtr] = {'smatch'}
                indexSubtr += 5

    def process_sentence_header(self, sentSource, format='html'):
        """
        Retrieve the metadata of the document the sentence
        belongs to. Return an HTML string with this data that
        can serve as a header for the context on the output page.
        """
        if format == 'csv':
            result = ''
        else:
            result = '<span class="context_header" data-meta="">'
        docID = sentSource['doc_id']
        meta = self.sc.get_doc_by_id(docID)
        print(meta)
        if (meta is None
                or 'hits' not in meta
                or 'hits' not in meta['hits']
                or len(meta['hits']['hits']) <= 0):
            return result + '</span>'
        meta = meta['hits']['hits'][0]
        if '_source' not in meta:
            return result + '</span>'
        meta = meta['_source']
        if 'title' in meta:
            if format == 'csv':
                result += '"' + meta['title'] + '" '
            else:
                # result += ('<span class="ch_title">' + meta['title'] +
                # '</span>')
                result += ('<a class="ch_title" target="_blank" href="' +
                           LINK_PREFIX + '/text/' + meta['id'] + '">'
                           + meta['title'] + '</a>')
        else:
            if format == 'csv':
                result += '"???" '
            else:
                result += '<span class="ch_title">-</span>'
        if 'author' in meta:
            if format == 'csv':
                result += '(' + meta['author'] + ') '
            else:
                result += '<span class="ch_author">' +\
                          meta['author'] + '</span>'
        if 'issue' in meta and len(meta['issue']) > 0:
            if format == 'csv':
                result += meta['issue'] + ' '
            else:
                result += '<span class="ch_date">' + meta['issue'] + '</span>'
        if 'year_from' in meta and 'year_to' in meta:
            dateDisplayed = str(meta['year_from'])
            if meta['year_to'] != meta['year_from']:
                if format == 'csv':
                    dateDisplayed += '-' + str(meta['year_to'])
                else:
                    dateDisplayed += '&ndash;' + str(meta['year_to'])
            if format == 'csv':
                result += '[' + dateDisplayed + ']'
            else:
                result += '<span class="ch_date">' + dateDisplayed + '</span>'
        dataMeta = ''
        for metaField in self.settings['viewable_meta']:
            if metaField == 'filename':
                continue
            try:
                metaValue = meta[metaField]
                if type(metaValue) != str:
                    metaValue = str(metaValue)
                dataMeta += metaField + ': ' + metaValue + '\\n'
            except KeyError:
                pass
        dataMeta = dataMeta.replace('"', '&quot;')
        if len(dataMeta) > 0 and format != 'csv':
            result = result.replace(
                'data-meta=""', 'data-meta="' + dataMeta + '"')
        if format != 'csv':
            result += '</span>'
        return result

    def get_word_offsets(self, sSource, numSent, matchOffsets=None):
        """
        Find at which offsets which word start and end. If macthOffsets
        is not None, find only offsets of the matching words.
        Return two dicts, one with start offsets and the other with end offsets
        The keys are offsets and the values are the string IDs of the words.
        """
        offStarts, offEnds = {}, {}
        for iWord in range(len(sSource['words'])):
            try:
                if sSource['words'][iWord]['wtype'] != 'word':
                    continue
                offStart = sSource['words'][iWord]['off_start']
                offEnd = sSource['words'][iWord]['off_end']
            except KeyError:
                continue
            wn = 'w' + str(numSent) + '_' + str(iWord)
            if matchOffsets is not None and wn not in matchOffsets:
                continue
            try:
                offStarts[offStart].add(wn)
            except KeyError:
                offStarts[offStart] = {wn}
            try:
                offEnds[offEnd].add(wn)
            except KeyError:
                offEnds[offEnd] = {wn}
        return offStarts, offEnds

    def get_para_offsets(self, sSource):
        """
        Find at which offsets which parallel fragments start and end.
        Return two dicts, one with start offsets and the other with end
        offsets.
        The keys are offsets and the values are the string IDs of the
        fragments.
        """
        offStarts, offEnds = {}, {}
        if 'para_alignment' not in sSource or 'doc_id' not in sSource:
            return offStarts, offEnds
        docID = sSource['doc_id']
        for iPA in range(len(sSource['para_alignment'])):
            pa = sSource['para_alignment'][iPA]
            try:
                offStart, offEnd = pa['off_start'], pa['off_end']
            except KeyError:
                continue
            pID = 'p' + pa['para_id'] + str(docID)
            try:
                offStarts[offStart].add(pID)
            except KeyError:
                offStarts[offStart] = {pID}
            try:
                offEnds[offEnd].add(pID)
            except KeyError:
                offEnds[offEnd] = {pID}
        return offStarts, offEnds

    def get_src_offsets(self, sSource):
        """
        Find at which offsets which sound/video-alignment fragments start and
        end.
        Return three dicts, one with start offsets, the other with end offsets,
        and the third with the descriptions of the fragments.
        The keys in the first two are offsets and the values are the string IDs
        of the fragments.
        """
        offStarts, offEnds, fragmentInfo = {}, {}, {}
        if 'src_alignment' not in sSource or 'doc_id' not in sSource:
            return offStarts, offEnds, fragmentInfo
        docID = sSource['doc_id']
        for iSA in range(len(sSource['src_alignment'])):
            sa = sSource['src_alignment'][iSA]
            try:
                offStart, offEnd = sa['off_start_sent'], sa['off_end_sent']
            except KeyError:
                continue
            srcID = 'src' + sa['src_id'] + str(docID)
            fragmentInfo[srcID] = {'start': sa['off_start_src'],
                                   'end': sa['off_end_src'],
                                   'src': sa['src'],
                                   'mtype': sa['mtype']}
            try:
                offStarts[offStart].add(srcID)
            except KeyError:
                offStarts[offStart] = {srcID}
            try:
                offEnds[offEnd].add(srcID)
            except KeyError:
                offEnds[offEnd] = {srcID}
        return offStarts, offEnds, fragmentInfo

    def relativize_src_alignment(self, expandedContext, srcFiles):
        """
        If the sentences in the expanded context are aligned with the
        neighboring media file fragments rather than with the same fragment,
        re-align them with the same one and recalculate offsets.
        """
        srcFiles = set(srcFiles)
        if (len(srcFiles) > 1
                or len(srcFiles) <= 0
                or 'src_alignment' not in expandedContext):
            return
        srcFile = list(srcFiles)[0]
        rxSrcFragmentName = re.compile('^(.*?)-(\\d+)-(\\d+)\\.[^.]*$')
        mSrc = rxSrcFragmentName.search(srcFile)
        if mSrc is None:
            return
        for k in expandedContext['src_alignment']:
            alignment = expandedContext['src_alignment'][k]
            if srcFile == alignment['src']:
                continue
            mExp = rxSrcFragmentName.search(alignment['src'])
            if mExp is None or mExp.group(1) != mSrc.group(1):
                continue
            offsetSrc = (
                    int(mSrc.group(3)) * self.settings['media_length']
                    + int(mSrc.group(2)) * self.settings['media_length'] / 3)
            offsetExp = (
                    int(mExp.group(3)) * self.settings['media_length']
                    + int(mExp.group(2)) * self.settings['media_length'] / 3)
            difference = offsetExp - offsetSrc
            alignment['src'] = srcFile
            alignment['start'] = str(float(alignment['start']) + difference)
            alignment['end'] = str(float(alignment['end']) + difference)

    def process_sentence_csv(self, sJSON, lang='', translit=None):
        """
        Process one sentence taken from response['hits']['hits'].
        Return a CSV string for this sentence.
        """
        sDict = self.process_sentence(
            sJSON, numSent=0, getHeader=False, format='csv',
            lang=lang, translit=translit)
        if ('languages' not in sDict
                or lang not in sDict['languages']
                or 'text' not in sDict['languages'][lang]
                or len(sDict['languages'][lang]['text']) <= 0):
            return ''
        return sDict['languages'][lang]['text']

    def transliterate_baseline(self, text, lang, translit=None):
        if translit is None or lang not in self.settings['languages']:
            return text
        spans = self.rxTextSpans.findall(text)
        translitFuncName = 'trans_' + translit + '_baseline'
        localNames = globals()
        if translitFuncName not in localNames:
            return text
        translit_func = localNames[translitFuncName]
        textTranslit = ''
        for span in spans:
            if span.startswith('<'):
                textTranslit += span
            else:
                textTranslit += translit_func(span, lang)
        return textTranslit

    def process_sentence(
            self, s, numSent=1, getHeader=False, lang='',
            translit=None, format='html'):
        """
        Process one sentence taken from response['hits']['hits'].
        If getHeader is True, retrieve the metadata from the database.
        Return dictionary
        {'header': document header HTML,
        {'languages': {'<language_name>': {'text': sentence HTML}}}}.
        """
        if '_source' not in s:
            return {'languages': {lang: {'text': '', 'highlighted_text': ''}}}
        matchWordOffsets = self.retrieve_highlighted_words(s, numSent)
        sSource = s['_source']
        if 'text' not in sSource or len(sSource['text']) <= 0:
            return {'languages': {lang: {'text': '', 'highlighted_text': ''}}}

        header = {}
        if getHeader:
            header = self.process_sentence_header(sSource, format)
        if 'highlight' in s and 'text' in s['highlight']:
            highlightedText = s['highlight']['text']
            if type(highlightedText) == list:
                if len(highlightedText) > 0:
                    highlightedText = highlightedText[0]
                else:
                    highlightedText = sSource['text']
        else:
            highlightedText = sSource['text']
        if 'words' not in sSource:
            return {'languages': {
                lang: {
                    'text': highlightedText,
                    'highlighted_text': highlightedText}}}
        chars = list(sSource['text'])
        if format == 'csv':
            offParaStarts, offParaEnds = {}, {}
            offSrcStarts, offSrcEnds, fragmentInfo = {}, {}, {}
            offStarts, offEnds = self.get_word_offsets(
                sSource, numSent,
                matchOffsets=matchWordOffsets)
        else:
            offParaStarts, offParaEnds = self.get_para_offsets(sSource)
            offSrcStarts, offSrcEnds, fragmentInfo = self.get_src_offsets(
                sSource
            )
            offStarts, offEnds = self.get_word_offsets(sSource, numSent)
            self.add_highlighted_offsets(offStarts, offEnds, highlightedText)

        curWords = set()
        for i in range(len(chars)):
            if chars[i] == '\n':
                if format == 'csv':
                    chars[i] = '\\n '
                elif (i == 0 or i == len(chars) - 1
                        or all(chars[j] == '\n'
                               for j in range(i+1, len(chars)))):
                    chars[i] = '<span class="newline"></span>'
                else:
                    chars[i] = '<br>'
            if (i not in offStarts and i not in offEnds
                    and i not in offParaStarts and i not in offParaEnds
                    and i not in offSrcStarts and i not in offSrcEnds):
                continue
            addition = ''
            if len(curWords) > 0:
                if format == 'csv':
                    addition = '}}'
                else:
                    addition = '</span>'
                if i in offEnds:
                    curWords -= offEnds[i]
                if i in offParaEnds:
                    curWords -= offParaEnds[i]
                if i in offSrcEnds:
                    curWords -= offSrcEnds[i]
            newWord = False
            if i in offStarts:
                curWords |= offStarts[i]
                newWord = True
            if i in offParaStarts:
                curWords |= offParaStarts[i]
                newWord = True
            if i in offSrcStarts:
                curWords |= offSrcStarts[i]
                newWord = True
            if len(curWords) > 0 and (len(addition) > 0 or newWord):
                if format == 'csv':
                    addition = '{{'
                else:
                    addition += self.build_span(
                        sSource, curWords, lang,
                        matchWordOffsets, translit=translit)
            chars[i] = addition + chars[i]
        if len(curWords) > 0:
            if format == 'csv':
                chars[-1] += '}}'
            else:
                chars[-1] += '</span>'
        relationsSatisfied = True
        if 'toggled_on' in s and not s['toggled_on']:
            relationsSatisfied = False
        text = self.transliterate_baseline(
            ''.join(chars), lang=lang, translit=translit)
        return {
            'header': header,
            'languages': {lang: {
                'text': text, 'highlighted_text': highlightedText}},
            'toggled_on': relationsSatisfied,
            'src_alignment': fragmentInfo}

    def count_word_subcorpus_stats(self, w, docIDs):
        """
        Return statistics about the given word in the subcorpus
        specified by the list of document IDs.
        This function is currently unused and will probably be deleted.
        """
        query = {'bool':
                 {'must':
                  [{'term': {'w_id': w['_id']}},
                   {'terms': {'d_id': docIDs}}]
                  }
                 }
        aggFreq = {'agg_freq': {'stats': {'field': 'freq'}}}
        esQuery = {'query': query, 'aggs': aggFreq, 'size': 1}
        response = self.sc.get_word_freqs(esQuery)
        nSents, rank = '', ''   # for now
        if 'hits' not in response or 'total' not in response['hits']:
            return '?', '?', '?', '?'
        nDocs = str(response['hits']['total'])
        if ('aggregations' in response
                and 'agg_freq' in response['aggregations']):
            freq = str(int(response['aggregations']['agg_freq']['sum']))
        else:
            freq = '0'
        return freq, rank, nSents, nDocs

    def filter_multi_word_highlight_iter(
            self, hit, nWords=1, negWords=None, keepOnlyFirst=False):
        """
        Remove those of the highlights that are empty or which do
        not constitute a full set of search terms. If keepOnlyFirst
        is True, remove highlights for all non-first query words.
        negWords is a list of words whose query was negative: they will be
        absent from the highlighting.
        Iterate over filtered inner hits.
        """
        if 'inner_hits' not in hit:
            return
        if negWords is None:
            negWords = []
        if keepOnlyFirst:
            for key, ih in hit['inner_hits'].items():
                if (key in self.w1_labels
                    and all(
                            hit['inner_hits']['w' + str(
                                iWord + 1
                            ) + '_' + key[3:]]['hits']['total'] > 0
                            for iWord in range(1, nWords)
                            if iWord + 1 not in negWords)):
                    yield key, ih
        else:
            for key, ih in hit['inner_hits'].items():
                if (all(
                        hit['inner_hits'][self.rxHitWordNo.sub(
                            str(iWord + 1), key, 1)]['hits']['total']['value'] > 0
                        for iWord in range(nWords)
                        if iWord + 1 not in negWords)
                        or '_' not in key):
                    yield key, ih

    def filter_multi_word_highlight(
            self, hit, nWords=1, negWords=None, keepOnlyFirst=False):
        """
        Non-iterative version of filter_multi_word_highlight_iter whic
        replaces hits['inner_hits'] dictionary.
        """
        if 'inner_hits' not in hit or nWords <= 1:
            return
        hit['inner_hits'] = {
            key: ih
            for key, ih in self.filter_multi_word_highlight_iter(
                hit, nWords=nWords,
                negWords=negWords,
                keepOnlyFirst=keepOnlyFirst)}

    def add_word_from_sentence(self, hitsProcessed, hit, nWords=1):
        """
        Extract word data from the highlighted w1 in the sentence and
        add it to the dictionary hitsProcessed.
        """
        if '_source' not in hit or 'inner_hits' not in hit:
            return
        langID, lang = self.get_lang_from_hit(hit)
        bRelevantWordExists = False

        for innerHitKey, innerHit in self.filter_multi_word_highlight_iter(
                hit, nWords=nWords, keepOnlyFirst=True):
            # if innerHitKey not in self.w1_labels:
            #     continue
            bRelevantWordExists = True
            for word in innerHit['hits']['hits']:
                hitsProcessed['total_freq'] += 1
                word['_source']['lang'] = lang
                wID = word['_source']['w_id']
                wf = word['_source']['wf'].lower()
                try:
                    hitsProcessed['word_ids'][wID]['n_occurrences'] += 1
                    hitsProcessed['word_ids'][wID]['n_sents'] += 1
                    hitsProcessed['word_ids'][wID]['doc_ids'].add(
                        hit['_source']['doc_id'])
                except KeyError:
                    hitsProcessed['n_occurrences'] += 1
                    hitsProcessed['word_ids'][wID] = {
                        'n_occurrences': 1,
                        'n_sents': 1,
                        'doc_ids': {hit['_source']['doc_id']},
                        'wf': wf}
        if bRelevantWordExists:
            hitsProcessed['n_sentences'] += 1
            hitsProcessed['doc_ids'].add(hit['_source']['doc_id'])

    @staticmethod
    def get_lemma(word):
        """
        Join all lemmata in the JSON representation of a word with
        an analysis and return them as a string.
        """
        if 'ana' not in word:
            return ''
        curLemmata = set()
        for ana in word['ana']:
            if 'lex' in ana:
                curLemmata.add(ana['lex'])
        return '/'.join(l for l in sorted(curLemmata))

    def process_words_collected_from_sentences(
            self, hitsProcessed, sortOrder='freq', pageSize=10):
        """
        Process all words collected from the sentences with a multi-word query.
        """
        for wID, freqData in hitsProcessed['word_ids'].items():
            word = {'w_id': wID, '_source': {'wf': freqData['wf']}}
            word['_source']['freq'] = freqData['n_occurrences']
            word['_source']['rank'] = ''
            word['_source']['n_sents'] = freqData['n_sents']
            word['_source']['n_docs'] = len(freqData['doc_ids'])
            hitsProcessed['words'].append(word)
        del hitsProcessed['word_ids']
        self.calculate_ranks(hitsProcessed)
        if sortOrder == 'freq':
            hitsProcessed['words'].sort(
                key=lambda w: (-w['_source']['freq'], w['_source']['wf']))
        elif sortOrder == 'wf':
            hitsProcessed['words'].sort(
                key=lambda w: w['_source']['wf'])
        processedWords = []
        for i in range(min(len(hitsProcessed['words']), pageSize)):
            word = hitsProcessed['words'][i]
            wordSource = self.sc.get_word_by_id(
                word['w_id'])['hits']['hits'][0]['_source']
            wordSource.update(word['_source'])
            word['_source'] = wordSource
            processedWords.append(
                self.process_word(
                    word,
                    lang=self.settings['languages'][word['_source']['lang']]))
        hitsProcessed['words'] = processedWords

    def calculate_ranks(self, hitsProcessed):
        """
        Calculate frequency ranks of the words collected from sentences based
        on their frequency in the hitsProcessed list.
        For each word, store results in word['_source']['rank']. Return nothing
        """
        freqsSorted = [w['_source']['freq'] for w in hitsProcessed['words']]
        freqsSorted.sort(reverse=True)
        quantiles = {}
        for q in [0.03, 0.04, 0.05, 0.1, 0.15, 0.2, 0.25, 0.5]:
            qIndex = math.ceil(q * len(freqsSorted))
            if qIndex >= len(freqsSorted):
                qIndex = len(freqsSorted) - 1
            quantiles[q] = freqsSorted[qIndex]
        for w in hitsProcessed['words']:
            if w['_source']['freq'] > 1:
                if w['_source']['freq'] > quantiles[0.03]:
                    w['_source']['rank'] = '#' + str(
                        freqsSorted.index(w['_source']['freq']) + 1)
                elif w['_source']['freq'] >= quantiles[0.5]:
                    w['_source']['rank'] = '&gt; ' + str(
                        min(
                            math.ceil(q * 100)
                            for q in quantiles
                            if w['_source']['freq'] >= quantiles[q]
                        )) + '%'

    def process_doc(self, d, exclude=None):
        """
        Process one document taken from response['hits']['hits'].
        """
        if '_source' not in d:
            return ''
        dSource = d['_source']
        dID = d['_id']
        doc = {
            'fields': [],
            'excluded': (exclude is not None and int(dID) in exclude),
            'id': dID}
        dateDisplayed = '-'
        if 'year_from' in dSource:
            dateDisplayed = str(dSource['year_from'])
            if ('year_to' in dSource
                    and dSource['year_to'] != dSource['year_from']):
                dateDisplayed += '&ndash;' + str(dSource['year_to'])
        doc['date_displayed'] = dateDisplayed
        for field in self.sc.qp.docMetaFields:
            if field.endswith('_kw'):
                continue
            if field in dSource:
                doc['fields'].append(dSource[field])
            else:
                doc['fields'].append('')
        return doc

    def retrieve_highlighted_words(self, sentence, numSent, queryWordID=''):
        """
        Explore the inner_hits part of the response to find the
        offsets of the words that matched the word-level query
        and offsets of the respective analyses, if any.
        Search for word offsets recursively, so that the procedure
        does not depend excatly on the response structure.
        Return a dictionary where keys are offsets of highlighted words
        and values are sets of the pairs (ID of the words, ID of its ana)
        that were found by the search query .
        """
        if 'inner_hits' in sentence:
            return self.retrieve_highlighted_words(sentence['inner_hits'],
                                                   numSent,
                                                   queryWordID)

        offsets = {}    # query term ID -> highlights for this query term
        if type(sentence) == list:
            for el in sentence:
                if type(el) not in [dict, list]:
                    continue
                newOffsets = self.retrieve_highlighted_words(
                    el, numSent, queryWordID)
                for newK, newV in newOffsets.items():
                    if newK not in offsets:
                        offsets[newK] = newV
                    else:
                        offsets[newK] |= newV
            return offsets
        elif type(sentence) == dict:
            if 'field' in sentence and sentence['field'] == 'words':
                if 'offset' in sentence:
                    wordOffset = (
                            'w' + str(numSent) + '_' + str(sentence['offset']))
                    if wordOffset not in offsets:
                        offsets[wordOffset] = set()
                    if queryWordID == '':
                        queryWordID = 'w0'
                    anaOffset = -1
                    if ('_nested' in sentence
                            and 'field' in sentence['_nested']
                            and sentence['_nested']['field'] == 'ana'):
                        anaOffset = sentence['_nested']['offset']
                    offsets[wordOffset].add((queryWordID, anaOffset))
                return offsets
            for k, v in sentence.items():
                curQueryWordID = queryWordID
                mQueryWordID = re.search('^(w[0-9]+)(_[0-9]+)?$', k)
                if mQueryWordID is not None:
                    if (len(queryWordID) > 0
                            and queryWordID != mQueryWordID.group(1)):
                        continue
                    elif len(queryWordID) <= 0:
                        curQueryWordID = mQueryWordID.group(1)
                if type(v) in [dict, list]:
                    newOffsets = self.retrieve_highlighted_words(
                        v, numSent, curQueryWordID)
                    for newK, newV in newOffsets.items():
                        if newK not in offsets:
                            offsets[newK] = newV
                        else:
                            offsets[newK] |= newV
        return offsets

    def get_lang_from_hit(self, hit):
        """
        Return the ID and the name of the language of the current hit
        taken from ES response.
        """
        if 'lang' in hit['_source']:
            langID = hit['_source']['lang']
        else:
            langID = 0
        lang = self.settings['languages'][langID]
        return langID, lang

    def process_sent_json(self, response, translit=None):
        result = {'n_occurrences': 0, 'n_sentences': 0,
                  'n_docs': 0, 'page': 1,
                  'message': 'Nothing found.'}
        if 'hits' not in response or 'total' not in response['hits']:
            return result
        result['message'] = ''
        result['n_sentences'] = response['hits']['total']
        result['contexts'] = []
        srcAlignmentInfo = {}
        if 'aggregations' in response:
            if 'agg_ndocs' in response['aggregations']:
                result['n_docs'] = int(
                    response['aggregations']['agg_ndocs']['value'])
            if (result['n_docs'] > 0
                    and 'agg_nwords' in response['aggregations']):
                result['n_occurrences'] = int(
                    math.floor(response['aggregations']['agg_nwords']['sum']))
        for iHit in range(len(response['hits']['hits'])):
            langID, lang = self.get_lang_from_hit(
                response['hits']['hits'][iHit])
            curContext = self.process_sentence(
                response['hits']['hits'][iHit],
                numSent=iHit,
                getHeader=True,
                lang=lang,
                translit=translit)
            if 'src_alignment' in curContext:
                srcAlignmentInfo.update(curContext['src_alignment'])
            result['contexts'].append(curContext)
        if len(srcAlignmentInfo) > 0:
            result['src_alignment'] = json.dumps(srcAlignmentInfo)
        return result

    def process_word_json(
            self, response, docIDs, searchType='word', translit=None):
        result = {
            'n_occurrences': 0, 'n_sentences': 0,
            'n_docs': 0, 'message': 'Nothing found.'}
        if ('hits' not in response
                or 'total' not in response['hits']
                or response['hits']['total'] <= 0):
            return result
        result['message'] = ''
        result['n_occurrences'] = response['hits']['total']
        result['n_docs'] = response['aggregations']['agg_ndocs']['value']
        result['total_freq'] = response['aggregations']['agg_freq']['value']
        result['words'] = []
        for iHit in range(len(response['hits']['hits'])):
            langID, lang = self.get_lang_from_hit(
                response['hits']['hits'][iHit])
            result['words'].append(
                self.process_word(
                    response['hits']['hits'][iHit],
                    searchType=searchType,
                    lang=lang, translit=translit))
        return result

    def process_word_subcorpus_json(self, response, docIDs, translit=None):
        result = {
            'n_occurrences': 0, 'n_sentences': 0,
            'n_docs': 0, 'message': 'Nothing found.'}
        if ('aggregations' not in response
                or 'agg_freq' not in response['aggregations']
                or 'value' not in response['aggregations']['agg_freq']
                or 'hits' not in response
                or 'total' not in response['hits']
                or response['hits']['total'] <= 0):
            return result
        result['message'] = ''
        # result['n_occurrences'] = response['hits']['total']
        result['n_occurrences'] = (
            response['aggregations']['agg_noccurrences']['value'])
        result['n_docs'] = response['aggregations']['agg_ndocs']['value']
        result['total_freq'] = response['aggregations']['agg_freq']['value']
        result['words'] = []
        sub_res = response['aggregations']['group_by_word']
        for iHit in range(len(sub_res['buckets'])):
            wordID = sub_res['buckets'][iHit]['key']
            docCount = sub_res['buckets'][iHit]['doc_count']
            wordFreq = sub_res['buckets'][iHit]['subagg_freq']['value']
            hit = self.sc.get_word_by_id(wordID)
            langID, lang = self.get_lang_from_hit(hit['hits']['hits'][0])
            result['words'].append(
                self.process_word_subcorpus(
                    hit['hits']['hits'][0],
                    nDocuments=docCount,
                    freq=wordFreq,
                    lang=lang, translit=translit))
        return result

    def process_docs_json(self, response, exclude=None, corpusSize=1):
        result = {'n_words': 0, 'n_sentences': 0, 'n_docs': 0,
                  'size_percent': 0.0,
                  'message': 'Nothing found.',
                  'metafields': [
                      field
                      for field in self.sc.qp.docMetaFields
                      if not field.endswith('_kw')]}
        if ('hits' not in response
                or 'total' not in response['hits']
                or response['hits']['total'] <= 0):
            return result
        if corpusSize <= 0:
            corpusSize = 1
        result['message'] = ''
        result['n_docs'] = response['hits']['total']
        result['n_words'] = int(
            round(response['aggregations']['agg_nwords']['value'], 0))
        result['docs'] = []
        for iHit in range(len(response['hits']['hits'])):
            if exclude is not None and int(
                    response['hits']['hits'][iHit]['_id']) in exclude:
                result['n_docs'] -= 1
                result['n_words'] -= (
                    response['hits']['hits'][iHit]['_source']['n_words'])
            result['docs'].append(
                self.process_doc(response['hits']['hits'][iHit], exclude))
        result['size_percent'] = round(result['n_words'] * 100 / corpusSize, 3)
        return result

    def extract_cumulative_freq_by_rank(self, hits):
        """
        Process search results that contain buckets with frequency rank. Each
        bucket contains the total frequency of a word of a given frequency
        rank.
        Buckets should be ordered by frequency rank.
        Return a dictionary of the kind {frequency rank: total frequency of
        the words whose rank is less or equal to this rank}.
        """
        if ('aggregations' not in hits
                or 'agg_rank' not in hits['aggregations']
                or 'buckets' not in hits['aggregations']['agg_rank']):
            return {}
        cumulFreq = 0
        freqByRank = {}
        for bucket in hits['aggregations']['agg_rank']['buckets']:
            cumulFreq += bucket['doc_count']
            freqByRank[bucket['key']] = cumulFreq
        return freqByRank
