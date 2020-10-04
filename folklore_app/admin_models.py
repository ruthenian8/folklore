"""
This module creates classes for admin panel views
with certain rights
"""

from flask_admin.contrib.sqla import ModelView
from flask_login import current_user
from flask import redirect, url_for

# COLUMN_NAMES = {}


class FolkloreBaseView(ModelView):
    """
    Base class for admin models. Callbacks for
    non-authenticated users.
    """
    page_size = 25
    can_export = True
    can_export = True
    # column_labels = COLUMN_NAMES

    def is_accessible(self):
        return current_user.is_authenticated

    def inaccessible_callback(self, name, **kwargs):
        # redirect to login page if user doesn't have access
        return redirect(url_for('login'))


class NoDeleteView(FolkloreBaseView):
    """Can't delete entries"""
    can_delete = False
    can_create = True
    can_edit = True


class EditOnly(FolkloreBaseView):
    """Can edit entries, can't delete or create"""
    can_delete = False
    can_create = False
    can_edit = True


class CreateOnly(FolkloreBaseView):
    """Can create, but not delete or edit"""
    can_delete = False
    can_create = True
    can_edit = False


class ViewOnly(FolkloreBaseView):
    """View only: no delete, create or edit"""
    can_delete = False
    can_create = False
    can_edit = False
