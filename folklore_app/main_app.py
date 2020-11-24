# -*- coding: utf-8 -*-
"""
Flask app main part (except for tsakorpus search)
"""
from datetime import datetime
import copy
from collections import defaultdict
import json
import os
import re
from urllib.parse import quote

import pandas as pd
import plotly.express as px
from pymystem3 import Mystem
from nltk.tokenize import sent_tokenize

from sqlalchemy import and_, text as sql_text
from werkzeug.security import generate_password_hash, check_password_hash

from flask import Flask, Response
from flask import render_template, request, redirect, url_for
from flask_login import login_user, logout_user, login_required
from flask_paginate import Pagination, get_page_parameter
from flask_uploads import UploadSet, configure_uploads, IMAGES
from flask_admin import Admin

from folklore_app.admin_models import admin_views, AdminIndexView

from folklore_app.models import (
    db,
    login_manager,
    Collectors,
    Informators,
    Keywords,
    Questions,
    Texts,
    User,
    QListName,
    GTags,
    GImages,
)

from folklore_app.settings import APP_ROOT, CONFIG, LINK_PREFIX, DATA_PATH
from folklore_app.const import ACCENTS, CATEGORIES
from folklore_app.tables import TextForTable
from folklore_app.db_search import get_result, database_fields

try:
    m = Mystem(use_english_names=True)
except TypeError:
    m = Mystem()
    m._mystemargs.append('--eng-gr')

DB = 'mysql+pymysql://{}:{}@{}:{}/{}'.format(
    CONFIG['USER'], CONFIG['PASSWORD'],
    CONFIG['HOST'], CONFIG['PORT'], CONFIG['DATABASE'])

MAX_RESULT = 200
PER_PAGE = 50

with open(os.path.join(DATA_PATH, 'query_parameters.json'), encoding="utf-8") as f:
    query_parameters = json.loads(f.read())


def create_app():
    """Create and configure app"""
    app = Flask(__name__, static_url_path='/static', static_folder='static')
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['APPLICATION_ROOT'] = APP_ROOT
    app.config['SQLALCHEMY_DATABASE_URI'] = DB
    app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024
    app.config['TEMPLATES_AUTO_RELOAD'] = True
    app.config['FLASK_ADMIN_SWATCH'] = 'cerulean'
    app.secret_key = 'yyjzqy9ffY'
    db.app = app
    db.init_app(app)

    admin = Admin(
        app, name='Folklore Admin',
        template_mode='bootstrap3',
        index_view=AdminIndexView(),
        url="/admin"
    )
    admin = admin_views(admin)
    return app


app = create_app()
login_manager.init_app(app)

photos = UploadSet('photos', IMAGES)
app.config['UPLOADED_PHOTOS_DEST'] = 'folklore_app/static/imgs'
app.config['UPLOAD_FOLDER'] = '/folklore_app/static'
configure_uploads(app, photos)

# -------------------------


@app.context_processor
def add_prefix():
    """Add prefix (for site on host/folklore path)"""
    return dict(prefix=LINK_PREFIX)


@login_manager.user_loader
def load_user(user_id):
    """Load user by id"""
    return User.query.get(int(user_id))


@app.route("/")
@app.route("/index")
def index():
    """Index page"""
    return render_template('index.html')


@app.route("/check_path")
def check_path():
    """Check path"""
    return str(app.url_map)


@app.route("/login", methods=['POST', 'GET'])
def login():
    """Log in page"""
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
    return render_template('login.html', message='')


@app.route("/logout")
@login_required
def logout():
    """Log out"""
    logout_user()
    return redirect(url_for('index'))


@app.route("/signup", methods=['POST', 'GET'])
@login_required
def signup():
    """Signup page"""
    if request.form:
        username = request.form.get('username')
        password = generate_password_hash(request.form.get('password'))
        email = request.form.get('email')
        name = request.form.get('name')
        if User.query.filter_by(
                username=request.form.get('username')).one_or_none():
            return render_template(
                'signup.html', message='Имя {} уже занято!'.format(username))
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
    return render_template('signup.html', message='???')


@app.route("/database", methods=['GET'])
def database():
    """DB search page"""
    selection = database_fields()
    if not request.args.get('formtype'):
        selection['formtype'] = 'simple'
    else:
        selection['formtype'] = request.args.get('formtype')
    return render_template('database.html', selection=selection)


@app.route("/text/<idx>")
def text(idx):
    """Show text page"""
    text = Texts.query.filter_by(id=idx).one_or_none()
    if text is not None:
        collectors = ', '.join(
            sorted([collector.code for collector in text.collectors]))
        keywords = ', '.join(
            sorted([keyword.word for keyword in text.keywords]))

        pretty_text = prettify_text(text.raw_text, html_br=True)

        return render_template('text.html', textdata=text,
                               pretty_text=pretty_text, collectors=collectors,
                               keywords=keywords)
    selection = database_fields()
    return render_template('database.html', selection=selection)


@app.route('/collectors')
@login_required
def collectors_view():
    """Collector list page"""
    collectors = Collectors.query.order_by('code').all()
    return render_template('collectors.html', collectors=collectors)


@app.route("/keywords")
def keyword_view():
    """Keyword list page"""
    keywords = Keywords.query.order_by('word').all()
    lettered = defaultdict(list)
    for keyword in keywords:
        first_let = keyword.word[0]
        lettered[first_let].append(keyword)

    ordered_letters = sorted(lettered.keys())

    return render_template('keywords.html', lettered=lettered, ordered_letters=ordered_letters)


@app.route('/informators')
@login_required
def informators_view():
    """List of informators"""
    informators = Informators.query.order_by('name').all()
    return render_template('informators.html', informators=informators)


@app.route('/dashboard')
@login_required
def dashboard():
    """Dashboard page"""
    return render_template('dashboard.html')


def get_search_query_terms(request):
    """Extract query terms to show them in human-readable form"""
    data = []
    for row in query_parameters:
        res = request.getlist(row['argument'])
        res = '; '.join(res)
        if res:
            data.append((row['rus'], res))
    return data


@app.route("/results", methods=['GET'])
def results():
    """Search results page"""
    download_link = re.sub(r'&?page=\d+', '', request.query_string.decode('utf-8'))
    if request.args:
        if 'download_txt' in request.args:
            return download_file_txt(request)
        if 'download_json' in request.args:
            return download_file_json(request)
        page = request.args.get(get_page_parameter(), type=int, default=1)
        offset = (page - 1) * PER_PAGE
        result = get_result(request)
        number = result.count()
        pagination = Pagination(
            page=page, per_page=PER_PAGE, total=number,
            search=False, record_name='result', css_framework='bootstrap3',
            display_msg='Результаты <b>{start} - {end}</b> из <b>{total}</b>'
        )
        query_params = get_search_query_terms(request.args)
        result = [TextForTable(text) for text in result.all()[offset: offset + PER_PAGE]]
        return render_template(
            'results.html', result=result, number=number, query_params=query_params,
            pagination=pagination, download_link=download_link)
    return render_template('results.html', result=[], download_link=download_link)


def download_file_txt(request):
    """
    Download search results as a TXT file
    """
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
                textdata.raw_text, html_br=False))) + '\n'
            text += '=' * 120 + '\n'
        response = Response(text, mimetype='text/txt')
    else:
        response = Response("", mimetype='text/txt')
    response.headers['Content-Disposition'] = (
        'attachment; filename="{}.txt"'.format(datetime.now()))
    return response


def download_file_json(request):
    """
    Download search results as a JSON file
    """
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
                textdata.raw_text))) + '\n'
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
    """
    User profile page
    """
    if request.form:
        uid = request.form.get('id')
        password = generate_password_hash(request.form.get('password'))
        email = request.form.get('email')
        name = request.form.get('name')
        if User.query.filter_by(id=uid).one_or_none():
            cur_user = User.query.filter_by(id=uid).one_or_none()
            cur_user.name = name
            cur_user.email = email
            cur_user.password = password
            db.session.flush()
            db.session.refresh(cur_user)
            db.session.commit()
        return render_template('user.html')
    return render_template('user.html')


@app.route('/help_user')
@login_required
def help_user():
    """Help authenticated user"""
    return render_template('help_user.html')


@app.route('/help')
def help_page():
    """Help page"""
    return render_template('help.html')


@app.route('/about')
def about():
    """About page"""
    return render_template('about.html')


@app.route('/questionnaire', methods=['GET'])
def questionnaire():
    """
    Page with questionnaires.
    Show questions if any questionnaire is chosen.
    Show only list of questionnaires otherwise.
    """
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
    """
    Query DB for geo statistics
    """
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
    data = pd.DataFrame(query_res, columns=['cnt', 'reg', 'dis', 'vil'])
    graph = px.sunburst(data, path=['reg', 'dis', 'vil'], values='cnt')
    graph.update_layout(
        margin=dict(t=50, l=0, r=0, b=0),
        height=700,
        title="Кол-во текстов по населенным пунктам")
    return graph.to_html(full_html=False)


@app.route('/stats')
def stats():
    """Page with statistics"""
    yrs = stats_geo()
    graphs = [yrs]
    return render_template('stats.html',
                           graphs=graphs)


def convert_video_audio_new(text):
    """
    Convert video / audio entry before writing to DB
    """
    items = text.split('\n')
    result = []
    for i in items:
        one_item = i.split(';')
        if len(one_item) == 2:
            result.append((one_item[0], int(one_item[1])))
        else:
            result.append((one_item[0], 0))
    return result


get_accents = {item[1] + '\\': item[0] for item in ACCENTS.items()}


def prettify_text(text, html_br=False):
    """
    Prettify text for human-readable form
    """
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
    text = re.sub(r"([а-яА-Я])_", r"\g<1>\g<1>", text)
    if html_br:
        text = re.sub(r"\n{2,}", "<br><br>", text)
        text = re.sub(r"\n", "<br>", text)
        text = re.sub(r'\[(.*?)\]', r'<span class="parentheses-text">[\g<1>]</span>', text)
    return text


def normalize_text(text):
    """
    Normalize text for corpus parsing
    """
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
    """
    Process too many line breaks and split sentences.
    """
    text = text.replace('[', '\n\n[').strip()
    text = re.sub('\n{3,}', '\n\n', text)
    result = []
    for i in text.split('\n\n'):
        result += sent_tokenize(i)
    return result


def sentence_comment(text):
    """
    find sentence comment (researcher speech)
    """
    comment = text.find(']')
    if comment == -1:
        return None, m.analyze(text[comment + 1:].strip())
    return text[:comment + 1], m.analyze(text[comment + 1:].strip())


def mystem_interpreter(word, display, language='russian'):
    """
    Mystem result converter
    """
    result = []
    if 'analysis' in word:
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
                continue
            # TODO check this continue thing
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


def sentences(text, meta=None):
    """
    Process sentences for the future tsakorpus indexing
    """
    if meta is None:
        meta = {}
    text_pretty = split_sentences(prettify_text(text))
    text_norm = split_sentences(normalize_text(text))
    result = []
    for key_, sent in enumerate(text_norm):
        try:
            sentence = sentence_comment(sent)
            sentence_double = sentence_comment(text_pretty[key_])
            cur = []
            for key, j in enumerate(sentence[1]):
                m_i = mystem_interpreter(j, sentence_double[1][key]['text'])
                if m_i['wf'] != ' ':
                    cur.append(
                        mystem_interpreter(j, sentence_double[1][key]['text']))
            result.append(
                _join_text(sentence[0], sentence_double[0], {'words': cur}))
            if sentence[0] is not None:
                if sentence[0].strip('][:') in meta:
                    result[-1]['meta'] = meta[sentence[0].strip('][:')]
            elif sentence[0] is None and len(meta) == 1:
                result[-1]['meta'] = meta[list(meta.keys())[0]]
        except IndexError:
            pass

    return result


def str_none(text):
    """None text to empty string"""
    if text is None:
        return ""
    return text


def tsakorpus_file(text):
    """
    Prepare file for tsakorpus future indexing
    """
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
        "region": text.geo.region.name,
        "village": text.geo.village.name,
        "district": text.geo.district.name,
        "title": "N {}, {}, {}, {}, {}".format(
            text.id, text.year, text.geo.region.name, text.geo.village.name, text.geo.district.name)
    }
    result = {'sentences': sentences(text.raw_text, meta),
              'meta': textmeta}
    return result


def roman_interpreter(roman):
    """
    Interpreter of roman numbers for numeric equivalents
    """
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
    """
    Update all json files with parsed texts in ./folklore folder.
    """
    texts = Texts.query.all()
    error_log = defaultdict(list)
    for one_text in texts:
        try:
            with open('./folklore/{}.json'.format(one_text.id), 'w') as jsonfile:
                json.dump(tsakorpus_file(one_text), jsonfile, ensure_ascii=False)
        except Exception as error:
            error_log[error].append(one_text.id)
    del texts
    print(error_log)
    return render_template('update_all.html', bad=error_log)


def get_gallery_main_structure():
    """
    Get geo and keyword tags from gallery_old DB part
    """
    query = "SELECT rus, id FROM glr_tags WHERE geo_lvl IS NULL ORDER BY rus"
    keywords = [
        (k.replace(" ", "&nbsp;").capitalize(), i)
        for k, i in db.session.execute(query).fetchall()]
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


def get_gallery_photos(tag_text):
    """
    Query DB and get gallery_old photos by tag.
    Replace spaces with different symbol and quote names.
    """
    images = GImages.query.filter()
    images = images.filter(GImages.tags.any(getattr(GTags, 'id') == tag_text))
    images = images.all()
    for i in images:
        for tag in i.tags:
            tag.rus = tag.rus.replace(" ", "&nbsp;")
        i.image_name = quote(i.image_name)
    return images


@app.route("/gallery")
def gallery():
    """
    Gallery render:
    1. If tag: get photos and render
    2. If empty: return main layout
    """
    if request.args:
        tag = GTags.query.get(request.args.get("tag"))
        images = get_gallery_photos(request.args.get("tag"))
        return render_template('gallery_layout.html', images=images, tag=tag)
    structure = get_gallery_main_structure()
    return render_template('gallery.html', structure=structure)
