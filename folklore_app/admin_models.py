"""
This module creates classes for admin panel views
with certain rights
"""
import os
import flask_admin as f_admin
from flask_admin import expose
from wtforms.fields import PasswordField
from flask_admin.contrib.sqla import ModelView
from flask_admin.base import MenuLink
from flask_admin.form import FileUploadField
from flask_login import current_user
from flask import redirect, url_for
from jinja2 import Markup
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

    def is_accessible(self):
        if not current_user.is_authenticated:
            return False
        return current_user.has_roles("guest")

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        return redirect(url_for('login'))


class UserView(FolkloreBaseView):
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
        if current_user.has_roles("admin"):
            self.can_delete = True
            self.can_create = True
            self.can_edit = True
            return True
        elif current_user.has_roles("chief"):
            self.can_delete = False
            self.can_create = True
            self.can_edit = True
            return True
        return False

    def on_model_change(self, form, User, is_created=False):
        User.password = form.new_password.data


class ChiefUpperFull(FolkloreBaseView):
    def is_accessible(self):
        if not current_user.is_authenticated:
            return False
        if current_user.has_roles("chief"):
            self.can_delete = True
            self.can_create = True
            self.can_edit = True
        elif current_user.has_roles("student"):
            self.can_delete = False
            self.can_create = False
            self.can_edit = False
        return True


class EditorUpperFull(FolkloreBaseView):
    def is_accessible(self):
        if not current_user.is_authenticated:
            return False
        if current_user.has_roles("editor"):
            self.can_delete = True
            self.can_create = True
            self.can_edit = True
        elif current_user.has_roles("student"):
            self.can_delete = False
            self.can_create = False
            self.can_edit = False
        return True


class StudentNoDelete(FolkloreBaseView):
    def is_accessible(self):
        if not current_user.is_authenticated:
            return False
        if current_user.has_roles("editor"):
            self.can_delete = True
            self.can_create = True
            self.can_edit = True
        elif current_user.has_roles("student"):
            self.can_delete = False
            self.can_create = True
            self.can_edit = True
        return True


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
            return Markup('<img src="%s" width="100">' % url)

    column_formatters = {
        'image_file': _gallery_view
    }

    # form_extra_fields = {
    #     'file': form.FileUploadField('file')
    # }


class CTextsView(StudentNoDelete):

    column_searchable_list = ('id', 'old_id', 'year', 'leader')
    form_columns = [c.key for c in Texts.__table__.columns] + ["file"]
    form_widget_args = {'id': {'readonly': True}}
    form_extra_fields = {
        'file': FileUploadField('file', base_path=PDF_PATH)
    }

    def _change_path_data(self, _form):
        print(dir(_form))
        storage_file = _form.file.data

        if storage_file is not None:
            idx = _form.id.data
            path = '%s.%s' % (idx, "pdf")
            print(path)

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
        return self._change_path_data(
            super(CTextsView, self).create_form(obj)
        )


class CCollectorsView(EditorUpperFull):
    column_searchable_list = ('id', 'old_id', 'code', 'name')


class CKeywordsView(ChiefUpperFull):
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
    admin.add_view(CQuestionsView(Questions, db.session, category="Опросники", name='Вопросы'))
    admin.add_view(EditorUpperFull(QListName, db.session, category="Опросники", name='Опросники'))

    admin.add_view(EditorUpperFull(
        GeoText, db.session, category="География", name='Географический объект'))
    admin.add_view(EditorUpperFull(Region, db.session, category="География", name='Регион'))
    admin.add_view(EditorUpperFull(District, db.session, category="География", name='Район'))
    admin.add_view(EditorUpperFull(Village, db.session, category="География", name='Населенный пункт'))

    admin.add_view(GalleryView(GImages, db.session, category="Галерея", name='Изображения'))
    admin.add_view(EditorUpperFull(GTags, db.session, category="Галерея", name='Теги'))

    admin.add_link(MenuLink(name='Загрузить картинки', url='/upload_images'))
    admin.add_link(MenuLink(name='Назад к архиву', url='/'))
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
