# -*- coding: utf-8 -*-

from datetime import datetime
import copy
import json
import os
import re

import pandas as pd
import plotly.express as px

from collections import defaultdict
from sqlalchemy import and_, text as sql_text, not_
from werkzeug.security import generate_password_hash, check_password_hash
from urllib.parse import quote

from flask import Flask, Response
from flask import render_template, request, redirect, url_for
from flask_login import login_user, logout_user, login_required, current_user
from flask_paginate import Pagination, get_page_parameter
from flask_uploads import UploadSet, configure_uploads, IMAGES
from flask_admin import Admin
from flask_admin.base import MenuLink
from flask_admin import expose
import flask_admin as f_admin

from folklore_app.admin_models import (
    FolkloreBaseView,
    EditOnly,
    NoDeleteView,
    ViewOnly,
    CreateOnly
)
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

from folklore_app.settings import APP_ROOT, CONFIG, LINK_PREFIX, DATA_PATH
from folklore_app.const import ACCENTS, CATEGORIES
from folklore_app.tables import TextForTable
from pymystem3 import Mystem
from nltk.tokenize import sent_tokenize


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


class AdminIndexView(f_admin.AdminIndexView):
    @expose('/')
    def index(self):
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        return super(AdminIndexView, self).index()


def admin_views(admin):
    admin.add_view(FolkloreBaseView(Texts, db.session, name='Тексты'))

    admin.add_view(CreateOnly(User, db.session, category="Люди", name='Пользователи'))
    admin.add_view(FolkloreBaseView(Collectors, db.session, category="Люди", name='Собиратели'))
    admin.add_view(FolkloreBaseView(Informators, db.session, category="Люди", name='Информанты'))

    admin.add_view(EditOnly(Keywords, db.session, category="Жанры, слова", name='Ключевые слова'))
    admin.add_view(EditOnly(Genres, db.session, category="Жанры, слова", name='Жанры'))

    admin.add_view(EditOnly(Questions, db.session, category="Опросники", name='Вопросы'))
    admin.add_view(EditOnly(QListName, db.session, category="Опросники", name='Опросники'))

    admin.add_view(FolkloreBaseView(GeoText, db.session, category="География", name='Географический объект'))
    admin.add_view(NoDeleteView(Region, db.session, category="География", name='Регион'))
    admin.add_view(NoDeleteView(District, db.session, category="География", name='Район'))
    admin.add_view(NoDeleteView(Village, db.session, category="География", name='Населенный пункт'))

    admin.add_view(ViewOnly(GImages, db.session, category="Галерея", name='Изображения'))
    admin.add_view(EditOnly(GTags, db.session, category="Галерея", name='Теги'))

    admin.add_link(MenuLink(name='Назад к архиву', url='/'))
    return admin


def create_app():
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
# app.route = prefix_route(app.route, '/foklore/')
# db.create_all()
# app.app_context().push()
login_manager.init_app(app)

photos = UploadSet('photos', IMAGES)
app.config['UPLOADED_PHOTOS_DEST'] = 'folklore_app/static/imgs'
app.config['UPLOAD_FOLDER'] = '/folklore_app/static'
configure_uploads(app, photos)

# -------------------------


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


@app.route("/check_path")
def check_path():
    return str(app.url_map)


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
                TVideo.id.in_(old_video + new_videos)).all()

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
                TAudio.id.in_(old_audio + new_audios)).all()
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
    # print(request.form)
    # print(request.files)
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

    ordered_letters = sorted(lettered.keys())

    return render_template('keywords.html', lettered=lettered, ordered_letters=ordered_letters)


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
    # print(download_link)
    if request.args:
        if 'download_txt' in request.args:
            return download_file_txt(request)
        elif 'download_json' in request.args:
            return download_file_json(request)
        else:
            page = request.args.get(get_page_parameter(), type=int, default=1)
            offset = (page - 1) * PER_PAGE
            result = get_result(request)
            # print(result.count())
            number = result.count()
            pagination = Pagination(
                page=page, per_page=PER_PAGE, total=number,
                search=False, record_name='result', css_framework='bootstrap3',
                display_msg='Результаты <b>{start} - {end}</b> из <b>{total}</b>'
            )
            # print(pagination.display_msg)
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
                textdata.raw_text, html_br=False))) + '\n'
            text += '=' * 120 + '\n'
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
    if request.form:
        uid = request.form.get('id')
        password = generate_password_hash(request.form.get('password'))
        email = request.form.get('email')
        name = request.form.get('name')
        if User.query.filter_by(id=uid).one_or_none():
            cur_user = User.query.filter_by(id=uid).one_or_none()
            # print(cur_user)
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
    # print(graph)
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
            geo_res = geo_res.filter(getattr(GeoText, 'id_' + str(name)).in_(idxs))
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
        # print(request.args.get('old_id', type=str))
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

    kw_plus = request.args.get('keywords', type=str, default='').split(';')
    kw_mode = request.args.get('kw_mode')
    kw_no = request.args.get('keywords_no', type=str, default='').split(';')
    if kw_plus != ['']:
        if kw_mode == "or":
            result = result.filter(Texts.keywords.any(Keywords.word.in_(kw_plus)))
        elif kw_mode == "and":
            for word in kw_plus:
                result = result.filter(Texts.keywords.any(Keywords.word == word))
    if kw_no != ['']:
        # for word in kw_no:
        #     result = result.filter(not_(Texts.keywords.any(Keywords.word == word)))
        result = result.filter(not_(Texts.keywords.any(Keywords.word.in_(kw_no))))

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
    # print(selection['current_geo_text'])
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


get_accents = {item[1] + '\\': item[0] for item in ACCENTS.items()}


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
        try:
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
        except IndexError:
            pass

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
    error_log = defaultdict(list)
    for text in texts:
        try:
            with open('./folklore/{}.json'.format(text.id), 'w') as f:
                json.dump(tsakorpus_file(text), f, ensure_ascii=False)
        except Exception as e:
            error_log[e].append(text.id)
    del texts
    print(error_log)
    return render_template('update_all.html', bad=error_log)


def get_gallery_main_structure():
    query = "SELECT rus, id FROM glr_tags WHERE geo_lvl IS NULL ORDER BY rus"
    keywords = [(k.replace(" ", "&nbsp;").capitalize(), i) for k, i in db.session.execute(query).fetchall()]
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
        i.image_name = quote(i.image_name)
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
