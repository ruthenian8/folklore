"""Regression tests for archive editing and request protection."""
import importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from unittest.mock import patch
from datetime import datetime
import json

import pytest
from flask_sqlalchemy import SQLAlchemy
from werkzeug.datastructures import MultiDict


@pytest.fixture(scope='module')
def app_modules():
    if not (Path(__file__).resolve().parents[1] / 'folklore_app/settings.py').exists():
        pytest.skip('Local application settings are missing')
    from unittest.mock import patch
    with patch.dict('os.environ', {'FLASK_SECRET_KEY': 'test-secret'}), \
         patch.object(SQLAlchemy, 'create_all'), \
         patch('pymystem3.Mystem'):
        app = importlib.import_module('folklore_app.main_app')
        admin = importlib.import_module('folklore_app.admin_models')
        search = importlib.import_module('folklore_app.db_search')
        yield app, admin, search


def test_permissions_do_not_depend_on_previous_user(app_modules, monkeypatch):
    app, admin, _ = app_modules
    view = object.__new__(admin.StudentNoDelete)
    roles = {'editor': 2, 'student': 3, 'guest': 10}
    with app.application.test_request_context():
        for role, expected in [('editor', (True, True)), ('guest', (False, False)),
                               ('student', (True, False)), ('guest', (False, False))]:
            user = SimpleNamespace(is_authenticated=True,
                                   has_roles=lambda target: roles[role] <= roles[target])
            monkeypatch.setattr(admin, 'current_user', user)
            assert (view.can_edit, view.can_delete) == expected


def test_forms_require_csrf_and_error_status_is_preserved(app_modules):
    app, _, _ = app_modules
    with app.application.test_client() as client:
        page = client.get('/login')
        assert b'name="csrf_token"' in page.data
        assert client.post('/upload_images').status_code == 403
        with client.session_transaction() as session:
            token = session['csrf_token']
        assert client.post('/upload_images', data={'csrf_token': token}).status_code == 302
        assert client.get('/missing-page').status_code == 404


def test_flask_admin_forms_include_csrf_token(app_modules):
    from flask import render_template_string
    from wtforms import Form

    class EditForm(Form):
        pass

    app, _, _ = app_modules
    with app.application.test_request_context():
        html = render_template_string(
            '{% import "admin/lib.html" as lib with context %}{{ lib.render_form_fields(form) }}',
            form=EditForm(),
        )
        assert 'name="csrf_token"' in html


def test_search_state_survives_a_new_request(app_modules):
    app, _, _ = app_modules
    search = importlib.import_module('folklore_app.tsakorpus_search')
    db_session = MagicMock()
    db_session.execute.return_value.first.return_value = SimpleNamespace(data='{}', updated_at=datetime.utcnow())
    with patch.object(search.db, 'session', db_session), patch.object(search.random, 'randrange', return_value=1):
        with app.application.test_request_context('/search'):
            from flask import session
            state = search.get_session_store()
            state['mysql_hit_ids'] = [{'text_id': 7, 'sent_no': 2}]
            state['word_constraints'] = {(1, 2): {'from': 0, 'to': 3}}
            session_id = session['session_id']
            search.save_search_session(app.application.response_class())
            statement = db_session.execute.call_args_list[-1][0][0]
            saved = statement.compile().params['data']
        db_session.execute.return_value.first.return_value = SimpleNamespace(data=saved, updated_at=datetime.utcnow())
        with app.application.test_request_context('/get_sent_context/0'):
            session['session_id'] = session_id
            restored = search.get_session_store()
            assert restored['mysql_hit_ids'][0]['text_id'] == 7
            assert restored['word_constraints'][(1, 2)]['to'] == 3
            assert json.loads(saved)['excluded_doc_ids'] == []


def test_geography_update_reindexes_matching_texts(app_modules):
    _, admin, _ = app_modules
    view = object.__new__(admin.GeographyView)
    view.session = MagicMock()
    village = admin.Village(id=42, name='New name')
    with patch('folklore_app.search_settings.SEARCH_BACKEND', 'mysql'):
        view.on_model_change(None, village, False)
    statement, params = view.session.execute.call_args[0]
    assert 'g.id_village = :id' in str(statement)
    assert params == {'id': 42}


def test_birth_year_upper_bound_is_applied(app_modules):
    _, _, search = app_modules
    result = MagicMock()
    search.filter_years(SimpleNamespace(args=MultiDict([('birth_year_to', '1950')])), result)
    expression = result.filter.call_args[0][0]
    assert 'birth_year <=' in str(expression)
    assert 1950 in expression.compile().params.values()


def test_all_birth_villages_are_kept_without_current_locations(app_modules, monkeypatch):
    _, _, search = app_modules
    people = [SimpleNamespace(birth_region='R', birth_district='D', birth_village=v)
              for v in ('A', 'B')]
    monkeypatch.setattr(search.Informators, 'query', SimpleNamespace(all=lambda: people))
    assert search.get_geo_informant_selection('b') == {'R': {'D': ['A', 'B']}}
