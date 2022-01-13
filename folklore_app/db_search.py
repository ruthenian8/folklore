# -*- coding: utf-8 -*-
"""
DB search module
"""
from datetime import datetime

from sqlalchemy import and_, not_

from folklore_app.models import (
    GeoText,
    Genres,
    Informators,
    Keywords,
    Questions,
    Texts,
    Region,
    District,
    Village,
    TImages2,
    TVideo,
    QListName,
)

none = ('', ' ', '-', None)


def filter_geo_text(request):
    """Filter texts by geo information about recording place"""
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
    """Filter text by geo information about informant"""
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


def filter_years(request, result):
    """Filter by years"""
    if request.args.get('year_from', type=int) is not None:
        result = result.filter(
            Texts.year >= request.args.get('year_from', type=int))
    if request.args.get('year_to', type=int) is not None:
        result = result.filter(
            Texts.year <= request.args.get('year_to', type=int))

    birth_year_to = request.args.get('birth_year_to', type=int, default=datetime.now().year)
    birth_year_from = request.args.get('birth_year_from', type=int, default=0)
    if birth_year_to and birth_year_from:
        result = result.filter(Texts.informators.any(
            and_(
                Informators.birth_year >= birth_year_from,
                Informators.birth_year <= birth_year_to)
        )
        )
    return result


def filter_by_id(request, result):
    """Filter by ID"""
    if request.args.get('new_id', type=int) is not None:
        result = result.filter(
            Texts.id == request.args.get('new_id', type=int))
    if request.args.get('old_id', type=str) not in ('', None):
        result = result.filter(
            Texts.old_id == request.args.get('old_id', type=str))
    return result


def filter_questions(request, result):
    """Filter by questions"""
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


def filter_keywords(request, result):
    """Filter by keywords"""
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
        result = result.filter(not_(Texts.keywords.any(Keywords.word.in_(kw_no))))
    return result


def query_all_if_not_none(schema, attribute):
    """Short filter all unique attributes except for none"""
    return list(
        i
        for i in sorted(set(
            getattr(i, attribute) for i in schema.query.all()
            if getattr(i, attribute) not in none
        )))


def get_geo_text_selection():
    """Get geo information structure"""
    geo_text = {}
    for i in GeoText.query.all():
        if i.region.name in geo_text:
            if i.district.name in geo_text[i.region.name]:
                geo_text[i.region.name][i.district.name].append(
                    i.village.name
                )
            else:
                geo_text[i.region.name][i.district.name] = [
                    i.village.name
                ]
        else:
            geo_text[i.region.name] = {}
            geo_text[i.region.name][i.district.name] = [i.village.name]

    for region in geo_text:
        for district in geo_text[region]:
            geo_text[region][district] = list(
                village
                for village in sorted(set(
                    geo_text[region][district]
                ))
            )
    return geo_text


def get_geo_informant_selection(mode):
    geo_dict = {}
    rgn = "current_region" if mode == "c" else "birth_region"
    dstr = "current_district" if mode == "c" else "birth_district"
    vllg = "current_village" if mode == "c" else "birth_village"
    for i in Informators.query.all():
        i_rgn, i_dstr = getattr(i, rgn), getattr(i, dstr)
        if i_rgn and i_rgn in geo_dict:
            if i_rgn in geo_dict[i_rgn]:
                geo_dict[i_rgn][i_dstr].append(getattr(i, vllg))
            else:
                geo_dict[i_rgn][i_dstr] = [getattr(i, vllg)]
        elif i_rgn:
            geo_dict[i_rgn] = {}
            if i.current_village and i.current_district:
                geo_dict[i_rgn][i_dstr] = [getattr(i, vllg)]

    for region in geo_dict:
        for district in geo_dict[region]:
            geo_dict[region][district] = list(
                village
                for village in sorted(set(geo_dict[region][district])))
    return geo_dict


def database_fields():
    """
    Query available DB parameters that can be showed in
    the search page
    """
    slct = {}
    slct['question_list'] = QListName.query.all()
    slct['question_num'] = query_all_if_not_none(Questions, "question_num")
    slct['question_letter'] = list(
        i
        for i in sorted(set(i.question_letter for i in Questions.query.all()))
        if len(i) == 1)
    slct['keywords'] = query_all_if_not_none(Keywords, "word")
    slct['code'] = query_all_if_not_none(Informators, "code")

    slct['geo_text'] = get_geo_text_selection()
    slct['current_geo_text'] = get_geo_informant_selection("c")
    slct['birth_geo_text'] = get_geo_informant_selection("b")

    slct['genres'] = [i.genre_name for i in Genres.query.all()]
    return slct


def get_result(request):
    """
    Query DB
    """
    result = Texts.query.filter()
    result = filter_by_id(request, result)

    geo_res = filter_geo_text(request)
    result = result.filter(Texts.geo_id.in_(geo_res))

    if request.args.getlist('code', type=str) != []:
        result = result.filter(Texts.informators.any(Informators.code.in_(
            request.args.getlist('code', type=str))))
    if request.args.getlist('genre', type=str) != []:
        result = result.filter(Texts.genre.in_(
            request.args.getlist('genre', type=str)))

    if request.args.get('has_media'):
        ids = set(
            [i.id_text for i in TImages2.query.all()] +
            [i.id_text for i in TVideo.query.all()])
        result = result.filter(Texts.id.in_(ids))

    result = filter_keywords(request, result)
    result = filter_questions(request, result)
    result = filter_person_geo(request, result)
    result = filter_years(request, result)
    return result
