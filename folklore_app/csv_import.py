"""Transactional CSV upload, adapted from flapp's CSV importer."""
import csv
import io
import re
from collections import defaultdict

from sqlalchemy import text

from folklore_app.models import (
    db, Collectors, Informators, Keywords, Questions, Texts,
    Region, District, Village, GeoText,
)


FIELDS = {
    'collectors': ('код собирателя', 'фио собирателя'),
    'informants': ('инициалы', 'фио', 'биография', 'село'),
    'cards': ('текст', 'программа', 'вопрос', 'год', 'ключевые слова', 'село'),
}


def issue(errors, file, row, field, message):
    errors.append(dict(file=file, row=row, field=field, message=message))


def parse_uploads(files, errors):
    sources = {}
    for kind, required in FIELDS.items():
        upload = files.get(kind)
        if not upload or not upload.filename:
            issue(errors, kind, None, 'file', 'Выберите CSV-файл')
            continue
        try:
            content = upload.stream.read().decode('utf-8-sig')
            candidates = []
            for delimiter in (',', ';', '\t', '|'):
                header = next(csv.reader([content.splitlines()[0]], delimiter=delimiter), [])
                if len(header) > 1:
                    candidates.append((len(set(x.lower() for x in header) & set(required)), delimiter))
            if not candidates or max(x[0] for x in candidates) == 0:
                raise ValueError('Не удалось определить разделитель')
            best = max(x[0] for x in candidates)
            separators = [d for score, d in candidates if score == best]
            if len(separators) != 1:
                raise ValueError('Неоднозначный разделитель')
            reader = csv.reader(io.StringIO(content, newline=''), delimiter=separators[0], strict=True)
            header = [x.lower() for x in next(reader)]
            if not header or any(not x for x in header) or len(header) != len(set(header)):
                issue(errors, kind, 1, 'header', 'Пустые или повторяющиеся имена столбцов')
            for column in required:
                if column not in header:
                    issue(errors, kind, 1, column, 'Обязательный столбец отсутствует')
            rows = []
            sources[kind] = rows
            while True:
                line = reader.line_num + 1
                try:
                    values = next(reader)
                except StopIteration:
                    break
                if len(values) != len(header):
                    issue(errors, kind, line, 'row', 'Неверное число столбцов')
                elif len(header) == len(set(header)):
                    rows.append((line, dict(zip(header, values))))
        except (UnicodeError, csv.Error, ValueError, IndexError, StopIteration) as exc:
            issue(errors, kind, None, 'file', str(exc) or 'Пустой файл')
    return sources


def parse_questions(value):
    tokens = re.findall(r'\d+|[^\W\d_]+|[^\s]', value, re.UNICODE)
    result, problems = [], []
    number, has_letter = None, False
    for token in tokens:
        if token.isdecimal():
            if number is not None and not has_letter:
                result.append((number, ''))
            number, has_letter = int(token), False
        elif token in (',', '.', ';'):
            continue
        elif token == 'доп':
            if number is None:
                result.append((0, 'доп'))
            else:
                result.append((number, ''))
            number, has_letter = None, False
        elif len(token) == 1 and token.isalpha() and number is not None:
            result.append((number, token.replace('a', 'а')))
            has_letter = True
        else:
            problems.append('Неизвестное обозначение вопроса: {}'.format(token))
    if number is not None and not has_letter:
        result.append((number, ''))
    return result, problems


def run_import(sources, errors, dry_run=False):
    """Validate and write in one transaction, rolling back a dry run."""
    people = {'collectors': defaultdict(list), 'informants': defaultdict(list)}
    plans = []

    def resolve(items, file, line, field, value, target):
        if len(items) != 1:
            if not items:
                message = 'Не найдено: {} {!r}'.format(target, value)
            else:
                message = 'Неоднозначная ссылка: {} {!r} (совпадений: {})'.format(target, value, len(items))
            issue(errors, file, line, field, message)
            return None
        return items[0]

    existing = {}
    for kind, model in (('collectors', Collectors), ('informants', Informators)):
        index = defaultdict(list)
        for person in model.query.all():
            index[((person.code or '').strip(), (person.name or '').strip())].append(person)
        existing[kind] = index
    for kind, model, code_field, name_field in (
        ('collectors', Collectors, 'код собирателя', 'фио собирателя'),
        ('informants', Informators, 'инициалы', 'фио'),
    ):
        source_collectors = {}
        for line, row in sources.get(kind, []):
            code, name = row.get(code_field, '').strip(), row.get(name_field, '').strip()
            if not code or not name:
                issue(errors, kind, line, code_field, 'Код и ФИО обязательны')
                continue
            key = (code, name)
            matches = existing[kind].get(key, [])
            if matches:
                for person in matches:
                    if person not in people[kind][code]:
                        people[kind][code].append(person)
                continue
            if kind == 'collectors':
                person = source_collectors.get(key) or model(code=code, name=name, old_id=row.get('номер') or None)
                source_collectors[key] = person
            else:
                person = model(code=code, name=name, bio=row.get('биография') or None,
                               current_village=row.get('село') or None, old_id=row.get('номер') or None)
            if kind == 'informants' and people[kind][code] and person not in people[kind][code]:
                issue(errors, kind, line, code_field, 'Повторный код информанта')
            if person not in people[kind][code]:
                people[kind][code].append(person)
    existing_codes = defaultdict(list)
    for (code, _), matches in existing['collectors'].items():
        existing_codes[code].extend(matches)

    def build_index(model, columns):
        index = defaultdict(list)
        for item in model.query.all():
            index[tuple(getattr(item, column) or '' for column in columns)].append(item)
        return index

    regions = build_index(Region, ('name',))
    districts = build_index(District, ('name',))
    village_index = build_index(Village, ('name',))
    keywords = build_index(Keywords, ('word',))
    question_index = build_index(Questions, ('question_list', 'question_num', 'question_letter'))

    for ordinal, (line, row) in enumerate(sources.get('cards', []), 1):
        def fail(field, message):
            issue(errors, 'cards', line, field, message)
        raw = row.get('текст', '')
        if not raw.strip():
            fail('текст', 'Текст обязателен')
        year = row.get('год', '').strip()
        if not re.fullmatch(r'[0-9]{4}', year) or not 1901 <= int(year) <= 2155:
            fail('год', 'Укажите год от 1901 до 2155')
        parts = [x.strip() for x in row.get('село', '').split(',')]
        geo = None
        if len(parts) != 3 or not all(parts):
            fail('село', 'Укажите регион, район и населённый пункт через запятую')
        else:
            region_name = re.sub(r'\bобл\.(?=\s|$)', 'область', parts[0], flags=re.IGNORECASE)
            region = resolve(regions.get((region_name,), []), 'cards', line, 'село', parts[0], 'регион')
            district = resolve(districts.get((parts[1].replace('р-н', 'район'),), []), 'cards', line, 'село', parts[1], 'район')
            villages = village_index.get((parts[2],), [])
            if len(villages) > 1:
                fail('село', 'Неоднозначный населённый пункт')
            elif region and district:
                geo = (region, district, villages[0] if villages else parts[2])
        links = {'collectors': [], 'informants': [], 'keywords': [], 'questions': []}
        for kind, prefix in (('collectors', 'собиратель'), ('informants', 'информант')):
            for n in range(1, 5):
                field = prefix + (str(n) if n > 1 else '')
                code = row.get(field, '').strip()
                if n == 1:
                    alias = row.get(prefix + '1', '').strip()
                    if code and alias and code != alias:
                        fail(field, 'Разные значения в столбцах {} и {}1'.format(prefix, prefix))
                        continue
                    code = code or alias
                if code:
                    matches = people[kind].get(code, [])
                    if kind == 'collectors' and not matches:
                        matches = existing_codes.get(code, [])
                    person = resolve(matches, 'cards', line, field, code,
                                     'собиратель' if kind == 'collectors' else 'информант')
                    if person is not None:
                        if person in links[kind]:
                            fail(field, 'Повторная связь с человеком')
                        else:
                            links[kind].append(person)
        seen_keywords = set()
        for word in row.get('ключевые слова', '').split(','):
            word = re.sub(r' +', ' ', word.strip())
            if not word or word in seen_keywords:
                continue
            seen_keywords.add(word)
            keyword = resolve(keywords.get((word,), []), 'cards', line, 'ключевые слова', word, 'ключевое слово')
            if keyword and keyword not in links['keywords']:
                links['keywords'].append(keyword)
        program = row.get('программа', '').replace('а', 'a').replace('Х', 'X').strip()
        if not program:
            fail('программа', 'Укажите программу')
        questions, problems = parse_questions(row.get('вопрос', ''))
        for problem in problems:
            fail('вопрос', problem)
        for number, letter in questions:
            matches = question_index.get((program, number or '', letter), [])
            question = resolve(matches, 'cards', line, 'вопрос', '{} {}{}'.format(program, number, letter), 'вопрос')
            if question:
                if question in links['questions']:
                    fail('вопрос', 'Повторная связь с вопросом')
                else:
                    links['questions'].append(question)
        plans.append((row.get('номер', '').strip() or str(ordinal), raw, year, geo, links))

    if errors:
        db.session.rollback()
        return 0
    connection = None
    old_sql_mode = None
    try:
        connection = db.session.connection()
        if connection.dialect.name == 'mysql':
            names = ('texts', 'collectors', 'informators', 'keywords', 'questions', 'g_regions', 'g_districts', 'g_villages', 'g_geo_text', 't_c', 't_i', 't_k', 't_q')
            from folklore_app.search_settings import SEARCH_BACKEND
            if SEARCH_BACKEND == 'mysql':
                names += ('texts_sentences',)
            engines = dict(connection.execute(text('SELECT TABLE_NAME, ENGINE FROM information_schema.TABLES WHERE TABLE_SCHEMA = DATABASE()')).fetchall())
            unsafe = [name for name in names if (engines.get(name) or '').lower() != 'innodb']
            if unsafe:
                raise ValueError('Отсутствуют транзакционные таблицы: ' + ', '.join(unsafe))
            old_sql_mode = connection.execute(text('SELECT @@SESSION.sql_mode')).scalar()
            connection.execute(text("SET SESSION sql_mode = 'STRICT_ALL_TABLES,NO_ZERO_DATE,NO_ZERO_IN_DATE,ERROR_FOR_DIVISION_BY_ZERO,NO_ENGINE_SUBSTITUTION'"))
        for kind in people.values():
            for persons in kind.values():
                db.session.add_all(persons)
        created = []
        villages = {}
        geos = {}
        for old_id, raw, year, geo, links in plans:
            region, district, village = geo
            if isinstance(village, str):
                if village not in villages:
                    villages[village] = Village(name=village)
                    db.session.add(villages[village])
                village = villages[village]
            key = (region.id, district.id, village.name)
            if key not in geos:
                if village.id is not None:
                    matches = GeoText.query.filter_by(id_region=region.id, id_district=district.id, id_village=village.id).all()
                    if len(matches) > 1:
                        raise ValueError('Неоднозначная география: {}'.format(village.name))
                else:
                    matches = []
                geos[key] = matches[0] if matches else GeoText(region=region, district=district, village=village)
            obj = Texts(old_id=old_id, raw_text=raw, year=int(year), geo=geos[key],
                        collectors=links['collectors'], informators=links['informants'],
                        keywords=links['keywords'], questions=links['questions'])
            db.session.add(obj)
            created.append(obj)
        db.session.flush()
        from folklore_app.search_settings import SEARCH_BACKEND
        if SEARCH_BACKEND == 'mysql':
            from folklore_app.search_backends.mysql_indexer import _index_texts
            _index_texts(created, commit=False)
        if old_sql_mode is not None:
            connection.execute(text('SET SESSION sql_mode = :mode'), {'mode': old_sql_mode})
            old_sql_mode = None
        if dry_run:
            db.session.rollback()
        else:
            db.session.commit()
        return len(created)
    except Exception:
        if old_sql_mode is not None:
            try:
                connection.execute(text('SET SESSION sql_mode = :mode'), {'mode': old_sql_mode})
            except Exception:
                connection.invalidate()
        db.session.rollback()
        raise
