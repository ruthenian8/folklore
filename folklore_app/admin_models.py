"""
This module creates classes for admin panel views
with certain rights
"""
import os
# from unicodedata import category
import flask_admin as f_admin
from flask_admin import expose, BaseView
from wtforms.fields import PasswordField
from wtforms.validators import Optional
from flask_admin.contrib.sqla import ModelView
from flask_admin.base import MenuLink
from flask_admin.form import FileUploadField
from flask_login import current_user
from flask import redirect, url_for, flash, request, has_request_context
from markupsafe import Markup, escape
from folklore_app.settings import PDF_PATH

from folklore_app.models import *

# COLUMN_NAMES = {}


class FolkloreBaseView(ModelView):
    """
    Base class for admin modals. Callbacks for
    non-authenticated users.
    """
    page_size = 25
    can_export = True
    column_display_pk = True
    edit_role = 'admin'
    delete_role = 'admin'

    @property
    def can_create(self):
        return has_request_context() and current_user.is_authenticated and current_user.has_roles(self.edit_role)

    @property
    def can_edit(self):
        return self.can_create

    @property
    def can_delete(self):
        return has_request_context() and current_user.is_authenticated and current_user.has_roles(self.delete_role)

    def is_accessible(self):
        if not current_user.is_authenticated:
            return False
        return current_user.has_roles("guest")

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        return redirect(url_for('login'))


class UserView(FolkloreBaseView):
    edit_role = 'chief'
    form_choices = {
        "role": [
            ("admin", "Уровень 0 - Админ"),
            ("chief", "Уровень 1 - Руководитель"),
            ("editor", "Уровень 2 - Редактор (метаинформация)"),
            ("student", "Уровень 3 - Студент (тексты)"),
            ("guest", "Уровень 4 - Гость (просмотр)"),
        ]
    }

    form_extra_fields = {
        'new_password': PasswordField('New Password')
    }

    form_columns = ("username", "role", "email", "name", "new_password")
    column_list = ("username", "role", "email", "name")

    def is_accessible(self):
        if not current_user.is_authenticated:
            return False
        return current_user.has_roles("chief")

    def on_model_change(self, form, User, is_created=False):
        User.password = form.new_password.data


class ChiefUpperFull(FolkloreBaseView):
    edit_role = delete_role = 'chief'


class EditorUpperFull(FolkloreBaseView):
    edit_role = delete_role = 'editor'


class StudentNoDelete(FolkloreBaseView):
    edit_role = 'student'
    delete_role = 'editor'


class GeographyView(EditorUpperFull):
    def on_model_change(self, form, model, is_created):
        from folklore_app.search_settings import SEARCH_BACKEND
        if SEARCH_BACKEND != 'mysql' or is_created:
            return
        from sqlalchemy import text
        self.session.flush()
        if isinstance(model, GeoText):
            condition = 'g.id = :id'
        else:
            condition = {Region: 'g.id_region = :id', District: 'g.id_district = :id',
                         Village: 'g.id_village = :id'}[type(model)]
        self.session.execute(text('''
            UPDATE texts_sentences s
            JOIN texts t ON t.id = s.text_id
            JOIN g_geo_text g ON g.id = t.geo_id
            LEFT JOIN g_villages v ON v.id = g.id_village
            LEFT JOIN g_districts d ON d.id = g.id_district
            LEFT JOIN g_regions r ON r.id = g.id_region
            SET s.geo = CASE WHEN v.id IS NOT NULL THEN v.village_name
                             WHEN d.id IS NOT NULL THEN d.district_name
                             ELSE r.region_name END
            WHERE ''' + condition), {'id': model.id})


class GalleryView(EditorUpperFull):
    column_list = (GImages.id, GImages.image_file, GImages.description)
    form_excluded_columns = ("folder_path", "image_name")

    page_size = 10

    def _gallery_view(view, context, model, name):
        if not model.image_file:
            return ''
        file_type = model.image_file.split(".")[-1].lower()
        # url = url_for('static', filename=os.path.join('gallery', model.image_file))
        url = "/api/gallery/100/" + model.image_file

        if file_type in ['jpg', 'jpeg', 'png', 'svg', 'gif']:
            return Markup('<img src="{}" width="100">').format(escape(url))

    column_formatters = {
        'image_file': _gallery_view
    }

    # form_extra_fields = {
    #     'file': form.FileUploadField('file')
    # }

# def pdf_prefix_name(obj, _):
#     idx = obj.id.data
#     path = '%s.%s' % (idx, "pdf")
#     return path


class CTextsView(StudentNoDelete):
    column_searchable_list = ('id', 'old_id', 'year', 'leader')
    form_widget_args = {'id': {'readonly': True}}
    form_columns = [c.key for c in Texts.__table__.columns][:1] + ["informators", "collectors", "questions", "keywords"] + [c.key for c in Texts.__table__.columns][2:] + ["file", "images"]
    form_extra_fields = {
        'file': FileUploadField('file', base_path=PDF_PATH)
    }

    def on_model_change(self, form, model, is_created):
        from folklore_app.search_settings import SEARCH_BACKEND
        if SEARCH_BACKEND == 'mysql':
            from folklore_app.search_backends.mysql_indexer import _index_texts
            self.session.flush()
            _index_texts([model], commit=False)

    def on_model_delete(self, model):
        from folklore_app.search_settings import SEARCH_BACKEND
        if SEARCH_BACKEND == 'mysql':
            from sqlalchemy import text
            self.session.execute(text('DELETE FROM texts_sentences WHERE text_id = :id'), {'id': model.id})
    def _change_path_data(self, _form):
        print(dir(_form))
        storage_file = _form.file.data

        if storage_file is not None:
            idx = _form.id.data
            path = '%s.%s' % (idx, "pdf")
            # print(path)

            storage_file.save(
                os.path.join(PDF_PATH, path)
            )

            _form.pdf.data = path

            del _form.file

        return _form

    def edit_form(self, obj=None):
        return self._change_path_data(
            super(CTextsView, self).edit_form(obj)
        )

    def create_form(self, obj=None):
        form = super(CTextsView, self).create_form(obj)
        form.id.validators = [Optional()]
        return self._change_path_data(form)


class CCollectorsView(EditorUpperFull):
    column_searchable_list = ('id', 'old_id', 'code', 'name')


class CKeywordsView(EditorUpperFull):
    column_searchable_list = ('word',)


class CGenreView(ChiefUpperFull):
    column_searchable_list = ('genre_name',)


class CInformatorsView(EditorUpperFull):
    column_searchable_list = (
        'id', 'old_id', 'code', 'name', 'birth_year',
        'current_village', 'current_district', 'current_region',
        'birth_village', 'birth_district', 'birth_region',
    )


class CQuestionsView(EditorUpperFull):
    column_searchable_list = ('question_list', 'question_text', 'question_theme')


class CAudioView(EditorUpperFull):
    column_searchable_list = ('id', 'id_text', 'audio')


class CVideoView(EditorUpperFull):
    column_searchable_list = ('id', 'id_text', 'video')


class CSVImportView(BaseView):
    """Upload three CSV files in a single database transaction."""

    def is_accessible(self):
        return current_user.is_authenticated and current_user.has_roles('chief')

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for('login'))

    @expose('/', methods=['GET', 'POST'])
    def index(self):
        errors = []
        count = None
        mode = None
        if request.method == 'POST':
            from folklore_app.csv_import import parse_uploads, run_import, issue
            try:
                mode = request.form.get('mode')
                if mode not in ('dry-run', 'commit'):
                    issue(errors, 'upload', None, 'mode', 'Выберите проверку или импорт')
                else:
                    sources = parse_uploads(request.files, errors)
                    if not errors:
                        count = run_import(sources, errors, dry_run=(mode == 'dry-run'))
            except Exception as exc:
                db.session.rollback()
                issue(errors, 'database', None, 'transaction', str(getattr(exc, 'orig', exc)))
        return self.render('admin/csv_import.html', errors=errors, count=count, mode=mode)


class SearchReindexView(BaseView):
    """Admin-only view for triggering a full search reindex.

    NOTE: rebuild_index runs synchronously inside the request cycle. For very
    large corpora consider offloading the work to a background task queue
    (Celery / RQ) to avoid blocking a WSGI worker.
    """

    def is_accessible(self):
        return (
            current_user.is_authenticated
            and current_user.has_roles("admin")
        )

    def inaccessible_callback(self, name, **kwargs):
        return redirect(url_for("login"))

    @expose('/')
    def index(self):
        from folklore_app.search_backends import mysql_indexer

        total_texts = Texts.query.count()
        indexed_texts = mysql_indexer.get_indexed_text_count()
        return self.render(
            "admin/search_reindex.html",
            total_texts=total_texts,
            indexed_texts=indexed_texts,
        )

    @expose('/run', methods=['POST'])
    def run_reindex(self):
        from folklore_app.search_backends import mysql_indexer

        truncate = request.form.get("truncate") == "on"
        try:
            result = mysql_indexer.rebuild_index(
                truncate_first=truncate, batch_size=1000
            )
            flash(
                "Переиндексация завершена: обработано {} из {} текстов.".format(
                    result["indexed"], result["total"]
                ),
                "success",
            )
        except Exception as exc:
            flash("Ошибка переиндексации: {}".format(exc), "error")

        return redirect(url_for(".index"))


def admin_views(admin):
    """List of admin views"""

    # student no delete
    admin.add_view(CTextsView(Texts, db.session, name='Тексты'))

    admin.add_view(UserView(User, db.session, category="Люди", name='Пользователи'))

    # chief upper full
    admin.add_view(CKeywordsView(Keywords, db.session, category="Жанры, слова", name='Ключевые слова'))
    admin.add_view(CGenreView(Genres, db.session, category="Жанры, слова", name='Жанры'))

    # editor upper full
    admin.add_view(CCollectorsView(Collectors, db.session, category="Люди", name='Собиратели'))
    admin.add_view(CInformatorsView(Informators, db.session, category="Люди", name='Информанты'))
    admin.add_view(CQuestionsView(Questions, db.session, category="Метаданные", name='Вопросы'))
    admin.add_view(EditorUpperFull(QListName, db.session, category="Метаданные", name='Опросники'))
    admin.add_view(CAudioView(TAudio, db.session, category="Метаданные", name="Аудиофайлы"))
    admin.add_view(CVideoView(TVideo, db.session, category="Метаданные", name="Видеофайлы"))

    admin.add_view(GeographyView(
        GeoText, db.session, category="География", name='Географический объект'))
    admin.add_view(GeographyView(Region, db.session, category="География", name='Регион'))
    admin.add_view(GeographyView(District, db.session, category="География", name='Район'))
    admin.add_view(GeographyView(Village, db.session, category="География", name='Населенный пункт'))

    admin.add_view(GalleryView(GImages, db.session, category="Галерея", name='Изображения'))
    admin.add_view(EditorUpperFull(GTags, db.session, category="Галерея", name='Теги'))

    admin.add_link(MenuLink(name='Загрузить картинки', url='/upload_images'))
    admin.add_link(MenuLink(name='Назад к архиву', url='/'))

    admin.add_view(SearchReindexView(
        name='Переиндексация', endpoint='search_reindex',
        category='Метаданные'
    ))

    admin.add_view(CSVImportView(name='Импорт CSV', endpoint='csv_import', category='Метаданные'))

    return admin


class AdminIndexView(f_admin.AdminIndexView):
    """
    Admin index view only for authenticated users
    """
    @expose('/')
    def index(self):
        """Index page check auth"""
        if not current_user.is_authenticated:
            return redirect(url_for("login"))
        return super(AdminIndexView, self).index()
