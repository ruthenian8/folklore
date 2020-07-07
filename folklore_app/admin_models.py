from flask_admin.contrib.sqla import ModelView
from flask_login import current_user
from flask import redirect, url_for

# COLUMN_NAMES = {}


class FolkloreBaseView(ModelView):
    page_size = 50
    can_export = True
    can_export = True
    # column_labels = COLUMN_NAMES

    def is_accessible(self):
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        return redirect(url_for('login'))


class NoDeleteView(FolkloreBaseView):
    can_delete = False
    can_create = True
    can_edit = True


class EditOnly(FolkloreBaseView):
    can_delete = False
    can_create = False
    can_edit = True


class CreateOnly(FolkloreBaseView):
    can_delete = False
    can_create = True
    can_edit = False


class ViewOnly(FolkloreBaseView):
    can_delete = False
    can_create = False
    can_edit = False
