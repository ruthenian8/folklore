"""
This module creates classes for admin panel views
with certain rights
"""
import flask_admin as f_admin
from flask_admin import expose
from flask_admin.contrib.sqla import ModelView
from flask_admin.base import MenuLink
from flask_login import current_user
from flask import redirect, url_for


from folklore_app.models import *

# COLUMN_NAMES = {}


class FolkloreBaseView(ModelView):
    """
    Base class for admin models. Callbacks for
    non-authenticated users.
    """
    page_size = 25
    can_export = True

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


def admin_views(admin):
    """List of admin views"""

    # student no delete
    admin.add_view(StudentNoDelete(Texts, db.session, name='Тексты'))

    admin.add_view(UserView(User, db.session, category="Люди", name='Пользователи'))

    # chief upper full
    admin.add_view(ChiefUpperFull(Keywords, db.session, category="Жанры, слова", name='Ключевые слова'))
    admin.add_view(ChiefUpperFull(Genres, db.session, category="Жанры, слова", name='Жанры'))

    # editor upper full
    admin.add_view(EditorUpperFull(Collectors, db.session, category="Люди", name='Собиратели'))
    admin.add_view(EditorUpperFull(Informators, db.session, category="Люди", name='Информанты'))
    admin.add_view(EditorUpperFull(Questions, db.session, category="Опросники", name='Вопросы'))
    admin.add_view(EditorUpperFull(QListName, db.session, category="Опросники", name='Опросники'))

    admin.add_view(EditorUpperFull(
        GeoText, db.session, category="География", name='Географический объект'))
    admin.add_view(EditorUpperFull(Region, db.session, category="География", name='Регион'))
    admin.add_view(EditorUpperFull(District, db.session, category="География", name='Район'))
    admin.add_view(EditorUpperFull(Village, db.session, category="География", name='Населенный пункт'))

    admin.add_view(EditorUpperFull(GImages, db.session, category="Галерея", name='Изображения'))
    admin.add_view(EditorUpperFull(GTags, db.session, category="Галерея", name='Теги'))


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
