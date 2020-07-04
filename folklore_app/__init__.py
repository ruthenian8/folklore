# -*- coding: utf-8 -*-
# from folklore_app.transliteration import *
from datetime import datetime
import copy
import functools
import gzip
import json
import math
import os
import random
import re
import time
import uuid
import xlsxwriter
import numpy as np
import pandas as pd
import plotly
import plotly.express as px


from collections import defaultdict
from functools import wraps, update_wrapper
from sqlalchemy import func, select, and_, or_, text as sql_text
from werkzeug.security import generate_password_hash, check_password_hash

from flask import (
    after_this_request,
    session,
    jsonify,
    current_app,
    send_from_directory,
    make_response
)
from flask import Flask, Response
from flask import render_template, request, redirect, url_for
from flask_login import login_user, logout_user, login_required
from flask_paginate import Pagination, get_page_parameter
from flask_uploads import UploadSet, configure_uploads, IMAGES

from folklore_app.models import (
    db,
    login_manager,
    Collectors,
    GeoText,
    Genres,
    Informators,
    Keywords,
    Questions,
    Texts,
    Region,
    District,
    Village,
    User,
    TImages,
    TAudio,
    TVideo,
    QListName,
    GTags,
    GImages,
    GIT,
)
from folklore_app.response_processors import SentenceViewer
from folklore_app.search_engine.client import SearchClient
from folklore_app.settings import APP_ROOT, SETTINGS_DIR, CONFIG, LINK_PREFIX, DATA_PATH
from folklore_app.const import ACCENTS, CATEGORIES
from folklore_app.tables import (
    TextForTable,
    GeoStats,
)
from pymystem3 import Mystem
from nltk.tokenize import sent_tokenize

m = Mystem()
# from pylev import levenschtein


DB = 'mysql+pymysql://{}:{}@{}:{}/{}'.format(
    CONFIG['USER'], CONFIG['PASSWORD'],
    CONFIG['HOST'], CONFIG['PORT'], CONFIG['DATABASE'])
MAX_RESULT = 200
# SETTINGS_DIR = './conf'
MAX_PAGE_SIZE = 100  # maximum number of sentences per page
PER_PAGE = 50
with open(os.path.join(SETTINGS_DIR, 'corpus.json'),
          'r', encoding='utf-8') as f:
    settings = json.loads(f.read())

with open(os.path.join(DATA_PATH, 'query_parameters.json')) as f:
    query_parameters = json.loads(f.read())

corpus_name = settings['corpus_name']
if settings['max_docs_retrieve'] >= 10000:
    settings['max_docs_retrieve'] = 9999
localizations = {}
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


def create_app():
    app = Flask(__name__, static_url_path='/static', static_folder='static')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['APPLICATION_ROOT'] = APP_ROOT
    app.config['SQLALCHEMY_DATABASE_URI'] = DB
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    app.secret_key = 'yyjzqy9ffY'
    db.app = app
    db.init_app(app)
    return app


app = create_app()
# app.route = prefix_route(app.route, '/foklore/')
# db.create_all()
# app.app_context().push()
login_manager.init_app(app)

photos = UploadSet('photos', IMAGES)
app.config['UPLOADED_PHOTOS_DEST'] = 'folklore_app/static/imgs'
app.config['UPLOAD_FOLDER'] = '/folklore_app/static'
configure_uploads(app, photos)

app.config.update(dict(
    LANGUAGES=settings['interface_languages'],
    BABEL_DEFAULT_LOCALE='ru'
))


@app.context_processor
def add_prefix():
    return dict(prefix=LINK_PREFIX)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


@app.route("/")
@app.route("/index")
def index():
    return render_template('index.html')


@app.route("/login", methods=['POST', 'GET'])
def login():
    if request.form:
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).one_or_none()
        if user:
            if check_password_hash(user.password, password):
                login_user(user)
                return render_template(
                    'login.html', message='{}, добро пожаловать!'.format(
                        user.name))
        return render_template('login.html', message='Попробуйте снова!')
    else:
        return render_template('login.html', message='')


@app.route("/logout")
@login_required
def logout():
    logout_user()
    return redirect(url_for('index'))


@app.route("/signup", methods=['POST', 'GET'])
@login_required
def signup():
    if request.form:
        username = request.form.get('username')
        password = generate_password_hash(request.form.get('password'))
        email = request.form.get('email')
        name = request.form.get('name')
        if User.query.filter_by(
                username=request.form.get('username')).one_or_none():
            return render_template(
                'signup.html', message='Имя {} уже занято!'.format(username))
        else:
            new_user = User(
                username=username,
                password=password,
                email=email,
                role='basic',
                name=name)
            db.session.add(new_user)
            db.session.commit()
            return render_template(
                'signup.html', message='{}, добро пожаловать!'.format(
                    new_user.name))
    else:
        return render_template('signup.html', message='???')


@app.route("/database", methods=['GET'])
def database():
    selection = database_fields()
    if not request.args.get('formtype'):
        selection['formtype'] = 'simple'
    else:
        selection['formtype'] = request.args.get('formtype')
    text = Texts.query.filter_by(id=100).one_or_none()
    # print(text.geo.__dict__)
    # print(text.geo.region.name)
    # print(text.region.__dict__)
    return render_template('database.html', selection=selection)


@app.route("/text/<idx>")
def text(idx):
    text = Texts.query.filter_by(id=idx).one_or_none()
    if text is not None:
        collectors = ', '.join(
            sorted([collector.code for collector in text.collectors]))
        keywords = ', '.join(
            sorted([keyword.word for keyword in text.keywords]))

        pretty_text = prettify_text(text.raw_text, html_br=True)
        # pretty_text = str(sentences(text.raw_text))

        return render_template('text.html', textdata=text,
                               pretty_text=pretty_text, collectors=collectors,
                               keywords=keywords)
    else:
        selection = database_fields()
        return render_template('database.html', selection=selection)


@app.route("/edit/<idx>")
@login_required
def edit(idx):
    text = Texts.query.filter_by(id=idx).one_or_none()
    other = {}
    other['collectors'] = [
        (collector.id, '{} | {}'.format(collector.id, collector.name),)
        for collector in text.collectors]
    seen_collectors = set(i[0] for i in other['collectors'])
    other['_collectors'] = [
        (collector.id, '{} | {}'.format(collector.id, collector.name),)
        for collector in Collectors.query.order_by('name').all()
        if collector.id not in seen_collectors]
    other['keywords'] = [
        (keyword.id, keyword.word,) for keyword in text.keywords]
    other['_keywords'] = [
        (keyword.id, keyword.word,)
        for keyword in Keywords.query.order_by('word').all()
        if keyword.word not in other['keywords']]
    other['informators'] = [
        (informator.id, '{} | {} | {}'.format(
            informator.id, informator.name, informator.current_village),)
        for informator in text.informators]
    seen_informators = set(i[0] for i in other['informators'])
    other['_informators'] = [
        (informator.id, '{} | {} | {}'.format(
            informator.id, informator.name, informator.current_village),)
        for informator in Informators.query.order_by(
            'current_village, name').all()
        if informator.id not in seen_informators
    ]
    other['video'] = [(video.id, video.video) for video in text.video]
    other['audio'] = [(audio.id, audio.audio) for audio in text.audio]
    other['images'] = [(image.id, image.imagename) for image in text.images]
    return render_template('edit_text.html',
                           textdata=text,
                           other=other)


@app.route("/text_edited", methods=['POST', 'GET'])
@login_required
def text_edited():
    if request.form:
        text = Texts.query.get(request.form.get('id', type=int))
        if request.form.get('submit', type=str) == 'Удалить':
            db.session.delete(text)
        else:
            text.old_id = request.form.get('old_id', type=str)
            text.year = request.form.get('year', type=int)
            text.region = request.form.get('region', type=str)
            text.district = request.form.get('district', type=str)
            text.village = request.form.get('village', type=str)
            text.address = request.form.get('address', type=str)
            text.genre = request.form.get('genre', type=str)
            text.raw_text = request.form.get('raw_text', type=str)

            informators = Informators.query.filter(
                Informators.id.in_(
                    request.form.getlist('informators', type=int))).all()
            text.informators.clear()
            text.informators = informators
            collectors = Collectors.query.filter(
                Collectors.id.in_(
                    request.form.getlist('collectors', type=int))).all()
            text.collectors.clear()
            text.collectors = collectors
            keywords = Keywords.query.filter(
                Keywords.id.in_(
                    request.form.getlist('keywords', type=int))).all()
            text.keywords.clear()
            text.keywords = keywords

            new_video = request.form.get('video_add', type=str)
            new_videos = []
            old_video = request.form.getlist('video', type=int)
            if new_video:
                for x in convert_video_audio_new(new_video):
                    v = TVideo(id_text=text.id, video=x[0], start=x[1])
                    db.session.add(v)
                    db.session.flush()
                    db.session.refresh(v)
                    new_videos.append(v.id)
            text.video = TVideo.query.filter(
                TVideo.id.in_(old_video+new_videos)).all()

            new_audio = request.form.get('audio_add', type=str)
            new_audios = []
            old_audio = request.form.getlist('audio', type=int)
            if new_audio:
                for x in convert_video_audio_new(new_audio):
                    v = TAudio(id_text=text.id, audio=x[0], start=x[1])
                    db.session.add(v)
                    db.session.flush()
                    db.session.refresh(v)
                    new_videos.append(v.id)
            text.audio = TAudio.query.filter(
                TAudio.id.in_(old_audio+new_audios)).all()
            # print(request.files)

            old_images = request.form.getlist('images', type=int)
            if 'photo' in request.files:
                # print(request.files)
                images = add_images(text, request)
                # print(images)
            else:
                images = []
            text.images = TImages.query.filter(
                TImages.id.in_(old_images + images)).all()
        # with open('./folklore/{}.json'.format(text.id), 'w') as f:
        #    json.dump(tsakorpus_file(text), f, ensure_ascii=False)
        db.session.commit()
        if request.form.get('submit', type=str) != 'Удалить':
            return redirect(url_for('text', idx=text.id))
        else:
            return redirect(url_for('database'))
    else:
        return redirect(url_for('database'))


@app.route("/add/text")
@login_required
def add():
    other = {}
    other['_collectors'] = [
        (collector.id, '{} | {}'.format(collector.id, collector.name),)
        for collector in Collectors.query.order_by('name').all()]
    other['_keywords'] = [
        (keyword.id, keyword.word,)
        for keyword in Keywords.query.order_by('word').all()]
    other['_informators'] = [
        (informator.id, '{} | {} | {}'.format(
            informator.id, informator.name, informator.current_village),)
        for informator in Informators.query.order_by(
            'current_village, name').all()]
    return render_template('add_text.html', other=other)


@app.route("/text_added", methods=['POST', 'GET'])
@login_required
def text_added():
    print(request.form)
    print(request.files)
    if request.form:
        old_id = request.form.get('old_id', type=str)
        year = request.form.get('year', type=int)
        region = request.form.get('region', type=str)
        district = request.form.get('district', type=str)
        village = request.form.get('village', type=str)
        address = request.form.get('address', type=str)
        genre = request.form.get('genre', type=str)
        raw_text = request.form.get('raw_text', type=str)
        informators = Informators.query.filter(
            Informators.id.in_(
                request.form.getlist('informators', type=int))).all()
        collectors = Collectors.query.filter(
            Collectors.id.in_(
                request.form.getlist('collectors', type=int))).all()
        keywords = Keywords.query.filter(
            Keywords.id.in_(request.form.getlist('keywords', type=int))).all()
        text = Texts(
            old_id=old_id, year=year,
            region=region, district=district, village=village, address=address,
            genre=genre,
            raw_text=raw_text,
            informators=informators, collectors=collectors, keywords=keywords)
        db.session.add(text)
        db.session.flush()
        db.session.refresh(text)
        # if 'photo' in request.files:
        #     images = add_images(text, request)
        db.session.commit()
        # with open('./folklore/{}.json'.format(text.id), 'w') as f:
        #    json.dump(tsakorpus_file(text), f, ensure_ascii=False)
        return redirect(url_for('text', idx=text.id))
    else:
        return redirect(url_for('database'))


def add_images(text, request):
    result = []
    for file in request.files.getlist('photo'):
        filename = photos.save(file, folder=str(text.id))
        image = TImages(id_text=text.id, imagename=filename)
        db.session.add(image)
        db.session.flush()
        db.session.refresh(image)
        result.append(image.id)
    # print(result)
    return result


@app.route("/add/collector", methods=['POST', 'GET'])
@login_required
def add_collector():
    if request.form:

        old_id = request.form.get('old_id', type=str)
        name = request.form.get('name', type=str)
        code = request.form.get('code', type=str)
        collector = Collectors(old_id=old_id, name=name, code=code)

        db.session.add(collector)
        db.session.commit()

        return redirect(url_for('collectors_view'))
    else:
        return render_template('add_collector.html')


@app.route("/edit/collector/<id_collector>", methods=['POST', 'GET'])
@login_required
def edit_collector(id_collector):
    if request.form:
        person = Collectors.query.get(request.form.get('id', type=int))
        if request.form.get('submit', type=str) == 'Удалить':
            db.session.delete(person)
        else:
            person.old_id = request.form.get('old_id', type=str)
            person.name = request.form.get('name', type=str)
            person.code = request.form.get('code', type=str)
            db.session.flush()
            db.session.refresh(person)
        db.session.commit()
        return redirect(url_for('collectors_view'))
    else:
        person = Collectors.query.get(id_collector)
        return render_template('edit_collector.html', person=person)


@app.route('/collectors')
@login_required
def collectors_view():
    collectors = Collectors.query.order_by('code').all()
    return render_template('collectors.html', collectors=collectors)


@app.route("/add/keyword", methods=['POST', 'GET'])
@login_required
def add_keyword():
    if request.form:

        old_id = request.form.get('old_id', type=str)
        word = request.form.get('word', type=str)
        definition = request.form.get('definition', type=str)

        keyword = Keywords(old_id=old_id, word=word, definition=definition)

        db.session.add(keyword)
        db.session.commit()

        return redirect(url_for('keyword_view'))
    else:
        return render_template('add_keyword.html')


@app.route("/edit/keyword/<id_keyword>", methods=['POST', 'GET'])
@login_required
def edit_keyword(id_keyword):
    if request.form:
        keyword = Keywords.query.get(request.form.get('id', type=int))
        if request.form.get('submit', type=str) == 'Удалить':
            db.session.delete(keyword)
        else:
            keyword.old_id = request.form.get('old_id', type=str)
            keyword.word = request.form.get('word', type=str)
            keyword.definition = request.form.get('definition', type=str)
            db.session.flush()
            db.session.refresh(keyword)
        db.session.commit()
        return redirect(url_for('keyword_view'))
    else:
        keyword = Keywords.query.get(id_keyword)
        return render_template('edit_keyword.html', keyword=keyword)


@app.route("/keywords")
def keyword_view():
    keywords = Keywords.query.order_by('word').all()
    lettered = defaultdict(list)
    for keyword in keywords:
        first_let = keyword.word[0]
        lettered[first_let].append(keyword)
    return render_template('keywords.html', lettered=lettered)


@app.route("/add/informator", methods=['POST', 'GET'])
@login_required
def add_informator():
    if request.form:

        old_id = request.form.get('old_id', type=str)
        code = request.form.get('code', type=str)
        name = request.form.get('name', type=str)
        gender = request.form.get('gender', type=str)
        birth_year = request.form.get('birth_year', type=int)
        bio = request.form.get('bio', type=str)
        current_region = request.form.get('current_region', type=str)
        current_district = request.form.get('current_district', type=str)
        current_village = request.form.get('current_village', type=str)
        birth_region = request.form.get('birth_region', type=str)
        birth_district = request.form.get('birth_district', type=str)
        birth_village = request.form.get('birth_village', type=str)

        informator = Informators(
            old_id=old_id, code=code, name=name, gender=gender,
            birth_year=birth_year, bio=bio,
            current_region=current_region, current_district=current_district,
            current_village=current_village,
            birth_region=birth_region, birth_district=birth_district,
            birth_village=birth_village
            )

        db.session.add(informator)
        db.session.commit()

        return redirect(url_for('informators'))
    else:
        return render_template('add_informator.html')


@app.route('/informators')
@login_required
def informators_view():
    informators = Informators.query.order_by('name').all()
    return render_template('informators.html', informators=informators)


@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')


def get_search_query_terms(request):
    data = []
    for row in query_parameters:
        res = request.getlist(row['argument'])
        res = '; '.join(res)
        if res:
            data.append((row['rus'], res))
    return data


@app.route("/results", methods=['GET'])
def results():
    download_link = re.sub('&?page=\d+', '', request.query_string.decode('utf-8'))
    print(download_link)
    if request.args:
        if 'download_txt' in request.args:
            return download_file_txt(request)
        elif 'download_json' in request.args:
            return download_file_json(request)
        else:
            page = request.args.get(get_page_parameter(), type=int, default=1)
            offset = (page - 1) * PER_PAGE
            result = get_result(request)
            print(result.count())
            number = result.count()
            pagination = Pagination(
                page=page, per_page=PER_PAGE, total=number,
                search=False, record_name='result', css_framework='bootstrap3',
                display_msg='Результаты <b>{start} - {end}</b> из <b>{total}</b>'
            )
            print(pagination.display_msg)
            query_params = get_search_query_terms(request.args)
            result = [TextForTable(text) for text in result.all()[offset: offset + PER_PAGE]]
            return render_template('results.html', result=result, number=number,
                                   query_params=query_params, pagination=pagination, download_link=download_link)
    return render_template('results.html', result=[], download_link=download_link)


def download_file_txt(request):
    # response = Response("")
    # response = HttpResponse(text, content_type='text/txt; charset=utf-8')
    # response['Content-Disposition'] = 'attachment; filename="result.txt"'
    if request.args:
        text = ""
        result = get_result(request)
        for item in result[:MAX_RESULT]:
            textdata = Texts.query.filter_by(id=item.id).one_or_none()
            text += 'ID: {}\nОригинальный ID: {}\nГод: {}\nРегион: {}\n'.format(
                item.id, item.old_id, item.year, item.geo.region.name
            )
            text += 'Район: {}\nНаселенный пункт: {}\nЖанр: {}\n'.format(
                item.geo.district.name, item.geo.village.name, item.genre
            )
            text = text + 'Информанты:\t' + ';'.join('{}, {}, {}'.format(
                i.code, i.birth_year, i.gender) for i in item.informators
                                                     ) + '\n'
            text += 'Вопросы:\t' + ';'.join('{}, {}{}'.format(
                i.question_list, i.question_num, i.question_letter
            ) for i in item.questions) + '\n'
            text += 'Ключевые слова:\t' + ','.join([i.word for i in item.keywords]) + '\n\n'
            text += str(re.sub('\n{2,}', '\n', prettify_text(
                textdata.raw_text, html_br=False)))+'\n'
            text += '='*120 + '\n'
        response = Response(text, mimetype='text/txt')
    else:
        response = Response("", mimetype='text/txt')
    response.headers['Content-Disposition'] = (
        'attachment; filename="{}.txt"'.format(datetime.now()))
    return response


def download_file_json(request):
    if request.args:
        result = get_result(request)
        data = []
        for item in result[:MAX_RESULT]:
            textdata = Texts.query.filter_by(id=item.id).one_or_none()
            one = {}
            one['ID'] = item.id
            one['orig_ID'] = item.old_id
            one['year'] = item.year
            one['region'] = item.geo.region.name
            one['district'] = item.geo.district.name
            one['village'] = item.geo.village.name
            one['genre'] = item.genre
            one['informants'] = [
                {
                    'id': i.id,
                    'code': i.code,
                    'birth_year': i.birth_year,
                    'gender': i.gender,
                    'current_region': i.current_region,
                    'current_district': i.current_district,
                    'current_village': i.current_village,
                    'birth_region': i.birth_region,
                    'birth_district': i.birth_district,
                    'birth_village': i.birth_village
                } for i in item.informators
            ]
            one['questions'] = [
                {
                    'question_list': i.question_list,
                    'question_num': i.question_num,
                    'question_letter': i.question_letter,
                } for i in item.questions
            ]
            one['keywords'] = [i.word for i in item.keywords]
            one['text'] = str(re.sub('\n{2,}', '\n', prettify_text(
                textdata.raw_text)))+'\n'
            data.append(copy.deepcopy(one))
        text = json.dumps(data, ensure_ascii=False, indent=4)
        response = Response(text, mimetype='application/json')
    else:
        response = Response("", mimetype='application/json')
    response.headers['Content-Disposition'] = (
        'attachment; filename="{}.json"'.format(datetime.now()))
    return response


@app.route('/user', methods=['POST', 'GET'])
@login_required
def user():
    if request.form:
        uid = request.form.get('id')
        password = generate_password_hash(request.form.get('password'))
        email = request.form.get('email')
        name = request.form.get('name')
        if User.query.filter_by(id=uid).one_or_none():
            cur_user = User.query.filter_by(id=uid).one_or_none()
            print(cur_user)
            cur_user.name = name
            cur_user.email = email
            cur_user.password = password
            db.session.flush()
            db.session.refresh(cur_user)
            db.session.commit()
        return render_template('user.html')
    else:
        return render_template('user.html')


@app.route('/help_user')
@login_required
def help_user():
    return render_template('help_user.html')


@app.route('/help')
def help():
    return render_template('help.html')


@app.route('/about')
def about():
    return render_template('about.html')


@app.route('/questionnaire', methods=['GET'])
def questionnaire():
    none = ('', ' ', '-', None)
    question_list = QListName.query.all()
    question_list.sort(
        key=lambda x: roman_interpreter(
            re.findall('^([A-ZХ]*?)[^A-Z]?$', x.question_list)[0]))
    questions = []
    name = ''
    full = False
    if request.args:
        name = request.args.get('qid', type=str)
        full = QListName.query.filter(
            QListName.question_list == name).one_or_none()
        if full:
            full = full.question_list_name
        questions = Questions.query.filter(
            and_(
                Questions.question_list == name,
                Questions.question_letter != 'доп')
        ).order_by(
            Questions.question_num, Questions.question_letter)
    if not full:
        full = ''
    return render_template('questionnaire.html',
                           question_list=question_list,
                           full=full,
                           questions=questions,
                           name=name)


def stats_geo():
    query = sql_text("""
    SELECT count(texts.id) as cnt, g_regions.region_name, g_districts.district_name, g_villages.village_name
    FROM texts
        JOIN g_geo_text ON texts.geo_id = g_geo_text.id
        JOIN g_regions ON g_geo_text.id_region = g_regions.id
        JOIN g_districts ON g_geo_text.id_district = g_districts.id
        JOIN g_villages ON g_geo_text.id_village = g_villages.id
    GROUP BY g_regions.region_name, g_districts.district_name, g_villages.village_name
    ORDER BY g_regions.region_name, g_districts.district_name, g_villages.village_name
    """)
    query_res = db.session.execute(query).fetchall()
    df = pd.DataFrame(query_res, columns=['cnt', 'reg', 'dis', 'vil'])
    graph = px.sunburst(df, path=['reg', 'dis', 'vil'], values='cnt')
    graph.update_layout(
        margin=dict(t=50, l=0, r=0, b=0),
        height=700,
        title="Кол-во текстов по населенным пунктам")
    print(graph)
    return graph.to_html(full_html=False)


@app.route('/stats')
def stats():
    yrs = stats_geo()
    graphs = [yrs]
    return render_template('stats.html',
                           graphs=graphs)

def convert_video_audio_new(text):
    items = text.split('\n')
    result = []
    for i in items:
        w = i.split(';')
        if len(w) == 2:
            result.append((w[0], int(w[1])))
        else:
            result.append((w[0], 0))
    # items = [(i.split(';')[0].strip(), int(i.split(';')[1])) for i in items]
    return result


def filter_geo_text(request):
    geo_res = GeoText.query.filter()
    list_of_parameters = [
        (Region, 'region'), (District, 'district'), (Village, 'village')
    ]
    for obj, name in list_of_parameters:
        if request.args.getlist(name, type=str):
            idxs = [
                i.id
                for i in obj.query.filter(
                    obj.name.in_(request.args.getlist(name, type=str))
                )
            ]
            geo_res = geo_res.filter(getattr(GeoText, 'id_'+str(name)).in_(idxs))
    geo_res = set(i.id for i in geo_res.all())
    return geo_res


def filter_person_geo(request, result):
    list_of_parameters = [
        'current_region', 'current_district', 'current_village',
        'birth_region', 'birth_district', 'birth_village'
    ]
    for name in list_of_parameters:
        if request.args.getlist(name, type=str):
            result = result.filter(
                Texts.informators.any(getattr(Informators, name).in_(
                    request.args.getlist(name, type=str))))
    return result


def get_result(request):
    result = Texts.query.filter()
    # year
    if request.args.get('year_from', type=int) is not None:
        result = result.filter(
            Texts.year >= request.args.get('year_from', type=int))
    if request.args.get('year_to', type=int) is not None:
        result = result.filter(
            Texts.year <= request.args.get('year_to', type=int))
    # id, old_id
    if request.args.get('new_id', type=int) is not None:
        result = result.filter(
            Texts.id == request.args.get('new_id', type=int))
    if request.args.get('old_id', type=str) not in ('', None):
        print(request.args.get('old_id', type=str))
        result = result.filter(
            Texts.old_id == request.args.get('old_id', type=str))
    # text geo
    geo_res = filter_geo_text(request)
    result = result.filter(Texts.geo_id.in_(geo_res))
    # informator meta
    # result = result.join(TI, Informators)
    if request.args.getlist('code', type=str) != []:
        result = result.filter(Texts.informators.any(Informators.code.in_(
            request.args.getlist('code', type=str))))
    if request.args.getlist('genre', type=str) != []:
        result = result.filter(Texts.genre.in_(
            request.args.getlist('genre', type=str)))

    # person geo
    result = filter_person_geo(request, result)

    if request.args.get('has_media'):
        ids = set([i.id_text for i in TImages.query.all()] + [i.id_text for i in TVideo.query.all()])
        result = result.filter(Texts.id.in_(ids))

    birth_year_to = request.args.get('birth_year_to', type=int, default=datetime.now().year)
    birth_year_from = request.args.get('birth_year_from', type=int, default=0)
    if birth_year_to and birth_year_from:
        result = result.filter(Texts.informators.any(
            and_(
                Informators.birth_year >= birth_year_from,
                Informators.birth_year <= birth_year_to)
            )
        )

    kw = request.args.get('keywords', type=str, default='').split(';')
    if kw != ['']:
        for word in kw:
            # result = result.filter(Texts.contains(kKeywords.word=word))
            result = result.filter(Texts.keywords.any(Keywords.word == word))

    # question list, code
    if request.args.getlist('question_list', type=str) != []:
        question = request.args.getlist('question_list', type=str)
        result = result.filter(
            Texts.questions.any(Questions.question_list.in_(question)))

    if request.args.getlist('question_num', type=int) != []:
        question = request.args.getlist('question_num', type=int)
        result = result.filter(
            Texts.questions.any(Questions.question_num.in_(question)))

    if request.args.getlist('question_letter', type=str) != []:
        question = request.args.getlist('question_letter', type=str)
        result = result.filter(
            Texts.questions.any(Questions.question_letter.in_(question)))

    return result


def database_fields():
    selection = {}
    none = ('', ' ', '-', None)
    # selection['question_list'] = list(
    #     set(
    #         i.question_list
    #         for i in Questions.query.all()
    #         if i.question_list not in none
    #     )
    # )
    # selection['question_list'].sort(
    #     key=lambda x: roman_interpreter(
    #         re.findall('^([A-ZХ]*?)[^A-Z]?$', x)[0]
    #     ))
    selection['question_list'] = QListName.query.all()
    selection['question_num'] = [
        i
        for i in sorted(
            set(
                i.question_num
                for i in Questions.query.all()
                if i.question_num not in none
            ))]
    selection['question_letter'] = [
        i
        for i in sorted(set(
            i.question_letter
            for i in Questions.query.all()
        ))
        if len(i) == 1
    ]
    selection['region'] = [
        i
        for i in sorted(set(
            i.geo.region.name
            for i in Texts.query.all()
            if i.geo.region.name not in none
        ))]
    selection['district'] = [
        i
        for i in sorted(set(
            i.geo.district.name for i in Texts.query.all()
            if i.geo.district.name not in none
        ))]
    selection['village'] = [
        i
        for i in sorted(set(
            i.geo.village.name
            for i in Texts.query.all()
            if i.geo.village.name not in none
        ))]

    # dict with geo_text
    selection['geo_text'] = {}
    for i in GeoText.query.all():
        if i.region.name in selection['geo_text']:
            if i.district.name in selection['geo_text'][i.region.name]:
                selection['geo_text'][i.region.name][i.district.name].append(
                    i.village.name
                )
            else:
                selection['geo_text'][i.region.name][i.district.name] = [
                    i.village.name
                ]
        else:
            selection['geo_text'][i.region.name] = {}
            selection['geo_text'][i.region.name][i.district.name] = [i.village.name]

    for region in selection['geo_text']:
        for district in selection['geo_text'][region]:
            selection['geo_text'][region][district] = [
                village
                for village in sorted(set(
                    selection['geo_text'][region][district]
                ))
            ]
    # print(selection['geo_text'])
    # -----------------------------------------

    selection['keywords'] = [
        i
        for i in sorted(set(
            i.word for i in Keywords.query.all()
            if i.word not in none
        ))]

    selection['code'] = [
        i for i in sorted(set(
            i.code
            for i in Informators.query.all()
            if i.code is not none
        ))]
    selection['current_region'] = [
        i for i in sorted(set(
            i.current_region
            for i in Informators.query.all()
            if i.current_region not in none
        ))]
    selection['current_district'] = [
        i for i in sorted(set(
            i.current_district
            for i in Informators.query.all()
            if i.current_district not in none
        ))]
    selection['current_village'] = [
        i for i in sorted(set(
            i.current_village
            for i in Informators.query.all()
            if i.current_village not in none
        ))]

    selection['current_geo_text'] = {}
    for i in Informators.query.all():
        if i.current_region and i.current_region in selection['current_geo_text']:
            if i.current_district in selection['current_geo_text'][i.current_region]:
                selection['current_geo_text'][i.current_region][i.current_district].append(
                    i.current_village
                )
            else:
                selection['current_geo_text'][i.current_region][i.current_district] = [
                    i.current_village
                ]
        elif i.current_region:
            selection['current_geo_text'][i.current_region] = {}
            if i.current_village and i.current_district:
                selection['current_geo_text'][i.current_region][i.current_district] = [i.current_village]

    for region in selection['current_geo_text']:
        for district in selection['current_geo_text'][region]:
            selection['current_geo_text'][region][district] = [
                village
                for village in sorted(set(
                    selection['current_geo_text'][region][district]
                ))
            ]
    print(selection['current_geo_text'])
    selection['birth_region'] = [
        i for i in sorted(set(
            i.birth_region
            for i in Informators.query.all()
            if i.birth_region not in none
        ))]
    selection['birth_district'] = [
        i for i in sorted(set(
            i.birth_district
            for i in Informators.query.all()
            if i.birth_district not in none
        ))]
    selection['birth_village'] = [
        i for i in sorted(set(
            i.birth_village
            for i in Informators.query.all()
            if i.birth_village not in none
        ))]

    selection['birth_geo_text'] = {}
    for i in Informators.query.all():
        if i.birth_region and i.birth_region in selection['birth_geo_text']:
            if i.birth_district in selection['birth_geo_text'][i.birth_region] and i.birth_village:
                selection['birth_geo_text'][i.birth_region][i.birth_district].append(
                    i.birth_village
                )
            elif i.birth_village:
                selection['birth_geo_text'][i.birth_region][i.birth_district] = [
                    i.birth_village
                ]
        elif i.birth_region and i.birth_region:
            selection['birth_geo_text'][i.birth_region] = {}
            if i.birth_village and i.birth_district:
                selection['birth_geo_text'][i.birth_region][i.birth_district] = [i.birth_village]

    for region in selection['birth_geo_text']:
        for district in selection['birth_geo_text'][region]:
            selection['birth_geo_text'][region][district] = [
                village
                for village in sorted(set(
                    selection['birth_geo_text'][region][district]
                ))
            ]
    selection['genres'] = [i.genre_name for i in Genres.query.all()]
    return selection


get_accents = {item[1]+'\\': item[0] for item in ACCENTS.items()}


def prettify_text(text, html_br=False):
    try:
        for i in get_accents:
            if i in text:
                text = text.replace(i, get_accents[i])
    except:
        text = text or ''
    text = re.sub('{{.*?}}', '', text)
    text = re.sub(' +', ' ', text)
    text = re.sub(' \n', '\n', text)
    text = text.replace('у%', 'ў')
    text = text.replace('У%', 'Ў')
    text = re.sub("([а-яА-Я])_", "\g<1>\g<1>", text)
    if html_br:
        text = re.sub("\n{2,}", "<br><br>", text)
        text = re.sub("\n", "<br>", text)
        # text = text.replace('[', '<br><div class="parentheses-text">[')
        # text = text.replace(']', ']</div><br>')
        # text = re.sub('\[(.*?)\]', '<div class="parentheses-text">[\g<1>]</div>', text)
        text = re.sub('\[(.*?)\]', '<span class="parentheses-text">[\g<1>]</span>', text)
    return text


def normalize_text(text):
    t_new = []
    text = text.replace('\\', '').replace('у%', 'ў')
    for i in re.split(" +", text):
        if re.match('^{{.*?}}$', i):
            t_new[-1] = i.strip('{}')
        else:
            t_new.append(i)
    text = ' '.join(t_new)
    text = text.replace('ў', 'в')
    text = text.replace('_', '')
    text = re.sub(' \n', '\n', text)
    return text


def split_sentences(text):
    text = text.replace('[', '\n\n[').strip()
    text = re.sub('\n{3,}', '\n\n', text)
    result = []
    for i in text.split('\n\n'):
        result += sent_tokenize(i)
    return result


def sentence_comment(text):
    c = text.find(']')
    if c == -1:
        return None, m.analyze(text[c + 1:].strip())
    else:
        return text[:c + 1], m.analyze(text[c + 1:].strip())


def mystem_interpreter(word, display, language='russian'):
    result = []
    if 'analysis' in word:
        # if True:
        for i in word['analysis']:
            lex = i['lex']
            variants = i['gr'].split('=')
            variants[0] = variants[0].split(',')
            variants[1] = [
                x.split(',')
                for x in variants[1].strip('()').split('|')
            ]
            if variants[1] == [['']]:
                variants[1] = []
                cur = {'lex': lex}
                for var in variants[0]:
                    cur['gr.{}'.format(CATEGORIES[language][var])] = var
                result.append(cur)
            else:
                for j in variants[1]:
                    cur = {'lex': lex}
                    for var in variants[0] + j:
                        if var != '':
                            cur['gr.{}'.format(
                                CATEGORIES[language][var]
                            )] = var

                    result.append(cur)
        return {
            'wtype': 'word',
            'wf': word['text'],
            'wf_display': display,
            'ana': result
        }
    else:
        return {
            'wtype': 'punkt',
            'wf': word['text'],
            'wf_display': display
        }


def _join_text(beginning, display_beginning, sentence):
    if beginning is not None and beginning != '':
        text = display_beginning + ' '
    else:
        text = ''
    for key, word in enumerate(sentence['words']):
        sentence['words'][key]['off_start'] = len(text)
        if word['wtype'] == 'word':
            text += word['wf_display'] + ' '
            sentence['words'][key]['off_end'] = len(text) - 1
        else:
            if word['wf_display'].startswith(('(', '[', '{', '<', '“')):
                text += word['wf_display']
                sentence['words'][key]['off_end'] = len(text)
            elif word['wf_display'].startswith(
                    (')', ']', '}', '>', '.', ':', ',', '?', '!', '”', '…')):
                if text.endswith(' '):
                    sentence['words'][key]['off_start'] -= 1
                    text = text[:-1]
                text += word['wf_display'] + ' '
                sentence['words'][key]['off_end'] = len(text) - 1
            else:
                text += word['wf_display'] + ' '
                sentence['words'][key]['off_end'] = len(text) - 1
        sentence['words'][key]['sentence_index'] = key
        sentence['words'][key]['next_word'] = key + 1
    sentence['text'] = text
    if beginning is not None:
        sentence['words'] = [{
            'wf': beginning,
            'wf_display': display_beginning,
            'wtype': 'comment',
            'off_start': 0,
            'off_end': len(beginning)
        }] + sentence['words']
    return sentence


def sentences(text, meta={}):
    text_pretty = split_sentences(prettify_text(text))
    text_norm = split_sentences(normalize_text(text))
    result = []
    for key_, sent in enumerate(text_norm):
        sentence = sentence_comment(text_norm[key_])
        sentence_double = sentence_comment(text_pretty[key_])
        cur = []
        for key, j in enumerate(sentence[1]):
            mi = mystem_interpreter(j, sentence_double[1][key]['text'])
            if mi['wf'] != ' ':
                cur.append(
                    mystem_interpreter(j, sentence_double[1][key]['text']))
        result.append(
            _join_text(sentence[0], sentence_double[0], {'words': cur}))
        if sentence[0] is not None:
            if sentence[0].strip('][:') in meta:
                result[-1]['meta'] = meta[sentence[0].strip('][:')]
        elif sentence[0] is None and len(meta) == 1:
            result[-1]['meta'] = meta[list(meta.keys())[0]]
    return result


def str_none(text):
    if text is None:
        return ""
    else:
        return text


def tsakorpus_file(text):
    meta = {}
    for i in text.informators:
        meta[i.code] = {'gender': str_none(i.gender),
                        'birth_village': str_none(i.birth_village),
                        'birth_district': str_none(i.birth_district),
                        'birth_region': str_none(i.birth_region),
                        'current_village': str_none(i.current_village),
                        'current_district': str_none(i.current_district),
                        'current_region': str_none(i.current_region)
                        }
        if i.birth_year is not None:
            meta[i.code]['age'] = str(text.year - i.birth_year)
            meta[i.code]['birth_year'] = str(i.birth_year)
    textmeta = {
        "year": str(text.year),
        "id": str(text.id),
        "region": text.region,
        "village": text.village,
        "district": text.district,
        "title": "N {}, {}, {}, {}, {}".format(
            text.id, text.year, text.region, text.village, text.district)
    }
    result = {'sentences': sentences(text.raw_text, meta),
              'meta': textmeta}
    return result


def roman_interpreter(roman):
    roman = roman.replace('Х', 'X')
    keys = [
        'IV', 'IX', 'XL', 'XC', 'CD', 'CM', 'I', 'V', 'X', 'L', 'C', 'D', 'M'
    ]
    to_arabic = {
        'IV': '4', 'IX': '9', 'XL': '40', 'XC': '90', 'CD': '400', 'CM': '900',
        'I': '1', 'V': '5', 'X': '10', 'L': '50', 'C': '100', 'D': '500',
        'M': '1000'}
    for key in keys:
        if key in roman:
            roman = roman.replace(key, ' {}'.format(to_arabic.get(key)))
    arabic = sum(int(num) for num in roman.split())
    return arabic


@app.route('/update_all')
@login_required
def update_all():
    texts = Texts.query.all()
    bad = []
    for text in texts:
        try:
            with open('./folklore/{}.json'.format(text.id), 'w') as f:
                json.dump(tsakorpus_file(text), f, ensure_ascii=False)
        except (Exception):
            bad.append(text.id)
    del texts
    return render_template('update_all.html', bad=bad)


def get_gallery_main_structure():
    query = "SELECT rus, id FROM glr_tags WHERE geo_lvl IS NULL ORDER BY rus"
    keywords = [(k.replace(" ", "&nbsp;"), i) for k, i in db.session.execute(query).fetchall()]
    query = "SELECT rus, id FROM glr_tags WHERE geo_lvl = 1"
    regions = db.session.execute(query).fetchall()
    query = "SELECT rus, id, region_id FROM glr_tags WHERE geo_lvl = 3 ORDER BY region_id, rus"
    villages = db.session.execute(query).fetchall()
    villages_dict = defaultdict(list)
    for rus, idx, reg in villages:
        villages_dict[reg].append((rus.replace(" ", "&nbsp;"), idx))
    result = {"keywords": keywords, "geo": {(reg, idx): None for reg, idx in regions}}
    for reg, idx in result["geo"]:
        result["geo"][(reg, idx)] = villages_dict[idx]
    return result


def get_gallery_photos(tag):
    ###
    images = GImages.query.filter()
    images = images.filter(GImages.tags.any(getattr(GTags, 'id') == tag))
    images = images.all()
    for i in images:
        for t in i.tags:
            t.rus = t.rus.replace(" ", "&nbsp;")
    return images


@app.route("/gallery")
def gallery():
    if request.args:
        tag = GTags.query.get(request.args.get("tag"))
        images = get_gallery_photos(request.args.get("tag"))
        return render_template('gallery_layout.html', images=images, tag=tag)
    else:
        structure = get_gallery_main_structure()
        return render_template('gallery.html', structure=structure)

# ------------------- Tsakorpus ---------------------------

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
    return get_session_data('locale')


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
                           locale=get_locale(),
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


@app.route('/word_freq_stats/<searchType>')
def get_word_freq_stats(searchType='word'):
    """
    Return JSON with the distribution of a particular kind of words
    or lemmata by frequency rank. This function is used for visualisation.
    Currently, it can only return statistics for a context-insensitive
    query for the whole corpus (the subcorpus constraints are
    discarded from the query). Return a list which contains results
    for each of the query words (the corresponding lines are plotted
    in different colors). Maximum number of simultaneously queried words
    is 10. All words should be in the same language; the language of the
    first word is used.
    """
    htmlQuery = copy_request_args()
    change_display_options(htmlQuery)
    langID = 0
    nWords = 1
    if 'n_words' in htmlQuery and int(htmlQuery['n_words']) > 1:
        nWords = int(htmlQuery['n_words'])
        if nWords > 10:
            nWords = 10
    if searchType not in ('word', 'lemma'):
        searchType = 'word'
    if 'lang1' in htmlQuery and htmlQuery['lang1'] in settings['languages']:
        langID = settings['languages'].index(htmlQuery['lang1'])
    else:
        return jsonify([])
    results = []
    for iWord in range(1, nWords + 1):
        htmlQuery['lang' + str(iWord)] = htmlQuery['lang1']
        partHtmlQuery = sc.qp.swap_query_words(
            1, iWord, copy.deepcopy(htmlQuery))
        esQuery = sc.qp.word_freqs_query(partHtmlQuery, searchType=searchType)
        # return jsonify(esQuery)
        if searchType == 'word':
            hits = sc.get_words(esQuery)
        else:
            hits = sc.get_lemmata(esQuery)
        # return jsonify(hits)
        curFreqByRank = sentView.extract_cumulative_freq_by_rank(hits)
        buckets = []
        prevFreq = 0
        if searchType == 'lemma':
            freq_by_rank = lemma_freq_by_rank
        else:
            freq_by_rank = word_freq_by_rank
        for freqRank in sorted(freq_by_rank[langID]):
            bucket = {'name': freqRank, 'n_words': 0}
            if freqRank in curFreqByRank:
                bucket['n_words'] = (
                        curFreqByRank[freqRank] /
                        freq_by_rank[langID][freqRank])
                prevFreq = curFreqByRank[freqRank]
            else:
                bucket['n_words'] = prevFreq / freq_by_rank[langID][freqRank]
            buckets.append(bucket)
        results.append(buckets)
    return jsonify(results)


@app.route('/word_stats/<searchType>/<metaField>')
def get_word_stats(searchType, metaField):
    """
    Return JSON with basic statistics concerning the distribution
    of a particular word form by values of one metafield. This function
    can be used to visualise word distributions across genres etc.
    If searchType == 'context', take into account the whole query.
    If searchType == 'compare', treat the query as several sepearate
    one-word queries. If, in this case, the data is to be displayed
    on a bar plot, process only the first word of the query.
    Otherwise, return a list which contains results for each
    of the query words (the corresponding lines are plotted
    in different colors). Maximum number of simultaneously queried words
    is 10. All words should be in the same language; the language of the
    first word is used.
    """
    if metaField not in settings['search_meta']['stat_options']:
        return jsonify([])
    if searchType not in ('compare', 'context'):
        return jsonify([])

    htmlQuery = copy_request_args()
    change_display_options(htmlQuery)
    docIDs = subcorpus_ids(htmlQuery)
    langID = -1
    if 'lang1' in htmlQuery and htmlQuery['lang1'] in settings['languages']:
        langID = settings['languages'].index(htmlQuery['lang1'])
    nWords = 1
    if 'n_words' in htmlQuery and int(htmlQuery['n_words']) > 1:
        nWords = int(htmlQuery['n_words'])
        if searchType == 'compare':
            if nWords > 10:
                nWords = 10
            if metaField not in linePlotMetafields:
                nWords = 1
    buckets = get_buckets_for_metafield(
        metaField, langID=langID, docIDs=docIDs)

    searchIndex = 'words'
    queryWordConstraints = None
    if metaField not in linePlotMetafields:
        queryFieldName = metaField + '_kw'
    else:
        queryFieldName = metaField
    if searchType == 'context' and nWords > 1:
        searchIndex = 'sentences'
        wordConstraints = sc.qp.wr.get_constraints(htmlQuery)
        set_session_data('word_constraints', wordConstraints)
        if (len(wordConstraints) > 0
                and get_session_data('distance_strict')):
            queryWordConstraints = wordConstraints
    elif (searchType == 'context'
          and 'sentence_index1' in htmlQuery
          and len(htmlQuery['sentence_index1']) > 0):
        searchIndex = 'sentences'

    results = []
    if searchType == 'context':
        nWordsProcess = 1
    else:
        nWordsProcess = nWords
    for iWord in range(1, nWordsProcess + 1):
        curWordBuckets = []
        for bucket in buckets:
            if (bucket['name'] == '>>'
                    or (type(bucket['name']) == str
                        and len(bucket['name']) <= 0)):
                continue
            newBucket = copy.deepcopy(bucket)
            if searchType == 'context':
                curHtmlQuery = copy.deepcopy(htmlQuery)
            else:
                curHtmlQuery = sc.qp.swap_query_words(
                    1, iWord, copy.deepcopy(htmlQuery))
                curHtmlQuery = sc.qp.remove_non_first_words(curHtmlQuery)
                curHtmlQuery['lang1'] = htmlQuery['lang1']
                curHtmlQuery['n_words'] = 1
            # if metaField not in curHtmlQuery or
            # len(curHtmlQuery[metaField]) <= 0:
            curHtmlQuery[queryFieldName] = bucket['name']
            # elif type(curHtmlQuery[metaField]) == str:
            #     curHtmlQuery[metaField] += ',' + bucket['name']
            curHtmlQuery['doc_ids'] = subcorpus_ids(curHtmlQuery)
            query = sc.qp.html2es(curHtmlQuery,
                                  searchOutput=searchIndex,
                                  sortOrder='',
                                  query_size=1,
                                  distances=queryWordConstraints)
            if searchIndex == 'words' and newBucket['n_words'] > 0:
                hits = sc.get_word_freqs(query)
                if ('aggregations' not in hits
                        or 'agg_freq' not in hits['aggregations']
                        or 'agg_ndocs' not in hits['aggregations']
                        or hits['aggregations']['agg_ndocs']['value'] is None
                        or (hits['aggregations']['agg_ndocs']['value'] <= 0
                            and not metaField.startswith('year'))):
                    continue
                newBucket['n_words'] = (
                        hits['aggregations']['agg_freq']['value'] /
                        newBucket['n_words'] * 1000000)
                newBucket['n_docs'] = (
                        hits['aggregations']['agg_ndocs']['value'] /
                        newBucket['n_docs'] * 100)
            elif searchIndex == 'sentences' and newBucket['n_words'] > 0:
                hits = sc.get_sentences(query)
                if ('aggregations' not in hits
                        or 'agg_nwords' not in hits['aggregations']
                        or 'agg_ndocs' not in hits['aggregations']
                        or hits['aggregations']['agg_ndocs']['value'] is None
                        or hits['aggregations']['agg_nwords']['sum'] is None
                        or (hits['aggregations']['agg_ndocs']['value'] <= 0
                            and not metaField.startswith('year'))):
                    continue
                newBucket['n_words'] = (
                        hits['aggregations']['agg_nwords']['sum'] /
                        newBucket['n_words'] * 1000000)
                if nWords > 1:
                    newBucket['n_sents'] = hits['hits']['total']
                newBucket['n_docs'] = (
                        hits['aggregations']['agg_ndocs']['value'] /
                        newBucket['n_docs'] * 100)
            curWordBuckets.append(newBucket)
        results.append(curWordBuckets)
    return jsonify(results)


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
            if '_source' not in dictParaID\
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
    if 'input_method' in request.args\
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
                if ('negq' + str(iQueryWord) in query)\
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
    if len(settings['languages']) > 1\
            and 'hits' in hits\
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
    if sentData is None\
        or n >= len(sentData)\
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
                if ('_source' in curSent)\
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
            if (hitsProcessed['total_freq'] >= 2000)\
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


@app.route('/search_doc_json')
@jsonp
def search_doc_json():
    query = copy_request_args()
    change_display_options(query)
    query = sc.qp.subcorpus_query(query,
                                  sortOrder=get_session_data('sort'),
                                  query_size=settings['max_docs_retrieve'])
    hits = sc.get_docs(query)
    return jsonify(hits)


@app.route('/search_doc')
@jsonp
def search_doc():
    query = copy_request_args()
    change_display_options(query)
    query = sc.qp.subcorpus_query(query,
                                  sortOrder=get_session_data('sort'),
                                  query_size=settings['max_docs_retrieve'])
    hits = sc.get_docs(query)
    hitsProcessed = sentView.process_docs_json(
        hits,
        exclude=get_session_data('excluded_doc_ids'),
        corpusSize=corpus_size)
    hitsProcessed['media'] = settings['media']
    return render_template('tsa_blocks/result_docs.html', data=hitsProcessed)


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


@app.route('/media/<path:path>')
def send_media(path):
    """
    Return the requested media file.
    """
    return send_from_directory(os.path.join('../media', corpus_name), path)


def prepare_results_for_download(pageData):
    """
    Return a list of search results in a format easily transformable
    to CSV/XLSX.
    """
    result = []
    for page in pageData:
        for sent in pageData[page]:
            if not sent['toggled_off']:
                result.append(
                    [sent['header_csv']] + sent['highlighted_text_csv'])
    return result


@app.route('/download_cur_results_csv')
@nocache
def download_cur_results_csv():
    """
    Write all sentences the user has already seen, except the
    toggled off ones, to a CSV file. Return the contents of the file.
    """
    pageData = get_session_data('page_data')
    if pageData is None or len(pageData) <= 0:
        return ''
    result = prepare_results_for_download(pageData)
    return '\n'.join(['\t'.join(s) for s in result if len(s) > 0])


@app.route('/download_cur_results_xlsx')
@nocache
def download_cur_results_xlsx():
    """
    Write all sentences the user has already seen, except the
    toggled off ones, to an XSLX file. Return the file.
    """
    pageData = get_session_data('page_data')
    if pageData is None or len(pageData) <= 0:
        return ''
    results = prepare_results_for_download(pageData)
    XLSXFilename = 'results-' + str(uuid.uuid4()) + '.xlsx'
    workbook = xlsxwriter.Workbook('tmp/' + XLSXFilename)
    worksheet = workbook.add_worksheet('Search results')
    for i in range(len(results)):
        for j in range(len(results[i])):
            worksheet.write(i, j, results[i][j])
    workbook.close()
    return send_from_directory('../tmp', XLSXFilename)


@app.route('/toggle_sentence/<int:sentNum>')
def toggle_sentence(sentNum):
    """
    Togle currently viewed sentence with the given number on or off.
    The sentences that have been switched off are not written to the
    CSV/XLSX when the user wants to download the search results.
    """
    pageData = get_session_data('page_data')
    page = get_session_data('page')
    if page is None or page == '':
        page = 0
    if pageData is None or page is None or page not in pageData:
        return json.dumps(pageData)
    if sentNum < 0 or sentNum >= len(pageData[page]):
        return ''
    pageData[page][sentNum]['toggled_off'] = (
        not pageData[page][sentNum]['toggled_off'])
    return ''


@app.route('/toggle_doc/<int:docID>')
def toggle_document(docID):
    """
    Togle given docID on or off. The documents that have been switched off
    are not included in the search.
    """
    excludedDocIDs = get_session_data('excluded_doc_ids')
    nWords = sc.get_n_words_in_document(docId=docID)
    sizePercent = round(nWords * 100 / corpus_size, 3)
    if docID in excludedDocIDs:
        excludedDocIDs.remove(docID)
        nDocs = 1
    else:
        excludedDocIDs.add(docID)
        nWords = -1 * nWords
        sizePercent = -1 * sizePercent
        nDocs = -1
    return jsonify(
        {
            'n_words': nWords,
            'n_docs': nDocs,
            'size_percent': sizePercent
        }
    )


@app.route('/clear_subcorpus')
def clear_subcorpus():
    """
    Flush the list of excluded document IDs.
    """
    set_session_data('excluded_doc_ids', set())
    return ''


@app.route('/get_gramm_selector/<lang>')
def get_gramm_selector(lang=''):
    """
    Return HTML of the grammatical tags selection dialogue
    for the given language.
    """
    if (lang not in settings['lang_props'])\
            or ('gramm_selection' not in settings['lang_props'][lang]):
        return ''
    grammSelection = settings['lang_props'][lang]['gramm_selection']
    return render_template(
        'tsa_blocks/select_gramm.html',
        gramm=grammSelection
    )


@app.route('/get_gloss_selector/<lang>')
def get_gloss_selector(lang=''):
    """
    Return HTML of the gloss selection dialogue for the given language.
    """
    if (lang not in settings['lang_props'])\
            or ('gloss_selection' not in settings['lang_props'][lang]):
        return ''
    glossSelection = settings['lang_props'][lang]['gloss_selection']
    return render_template(
        'tsa_blocks/select_gloss.html',
        glosses=glossSelection
    )


@app.route('/set_locale/<lang>')
def set_locale(lang=''):
    if lang not in settings['interface_languages']:
        return
    set_session_data('locale', lang)
    return ''


@app.route('/help_dialogue')
def help_dialogue():
    lang = get_locale()
    return render_template(
        'tsa_blocks/help_dialogue_' + lang + '.html',
        media=settings['media'],
        gloss_search_enabled=settings['gloss_search_enabled']
    )
