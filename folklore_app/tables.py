"""Auto generated tables for search results"""

from flask_table import Table, Col, NestedTableCol
INFORMANT_LINK = '/informator/{}'


class InformatorSubTable(Table):
    """Informant sub table"""
    classes = ['sub-table']
    code = Col('Код')
    gender = Col('Гендер')
    birth_year = Col('Год рождения')
    # current_region = Col('')


class KeywordsSubTable(Table):
    """Keyword sub table"""
    classes = ['sub-table']
    word = Col('Ключевое слово', th_html_attrs={'hidden': 'True'})


class QuestionsSubTable(Table):
    """Question sub table"""
    classes = ['sub-table']
    question_list = Col('Лист')
    question_code = Col('Вопрос')


class MainSearchTable(Table):
    """Main search table"""
    classes = ['large-table']
    id = Col('ID', th_html_attrs={'class': 'large-th'})
    old_id = Col('Прежний ID', th_html_attrs={'class': 'large-th'})
    # raw_text = LinkCol(
    # 'текст', 'text/',
    # url_kwargs=dict(id='id'), th_html_attrs={'class':'large-th'})
    year = Col('Год', th_html_attrs={'class': 'large-th'})
    region = Col('Регион', th_html_attrs={'class': 'large-th'})
    district = Col('Район', th_html_attrs={'class': 'large-th'})
    village = Col('Населенный пункт', th_html_attrs={'class': 'large-th'})
    genre = Col('Жанр', th_html_attrs={'class': 'large-th'})
    informators = NestedTableCol(
        'Инфоманты', InformatorSubTable, th_html_attrs={'class': 'large-th'})
    questions = NestedTableCol(
        'Вопросы', QuestionsSubTable, th_html_attrs={'class': 'large-th'})
    keywords = Col('keywords', th_html_attrs={'class': 'large-th'})
    # keywords = NestedTableCol(
    # 'Ключевые слова', KeywordsSubTable, th_html_attrs={'class':'large-th'})


def shorten_regions(text):
    """Region type shortenings"""
    if text is None:
        return text
    for pair in [('область', 'обл.'), ('район', 'р-н')]:
        text = text.replace(pair[0], pair[1])
    return text


class TextForTable:
    """Text for table view"""
    def __init__(self, text_object):
        self.id = text_object.id
        self.old_id = text_object.old_id
        self.year = text_object.year
        self.region = shorten_regions(text_object.geo.region.name)
        self.district = shorten_regions(text_object.geo.district.name)
        self.village = text_object.geo.village.name
        self.informators = text_object.informators
        self.questions = text_object.questions
        self.questions = text_object.questions
        self.genre = text_object.genre
        self.keywords = '<br>'.join(
            sorted([keyword.word for keyword in text_object.keywords])[:3]) + '<br>...'
        self.text = text_object.raw_text or ''
        self.text = self.text[:200].replace('\\', '').replace('у%', 'ў').replace('У%', 'U̯')
        # if object.video is not None:
        #     self.video = object.video.split('\n')
        # else:
        #     self.video = []


class InformatorSubTableText:
    """Informant table"""
    code = Col('Код')
    gender = Col('Гендер')
    birth_year = Col('Год рождения')
    current_region = Col('Регион проживания')
    current_district = Col('Район проживания')
    current_village = Col('Населенный пункт')
    birth_region = Col('Регион рождения')
    birth_district = Col('Район рождения')
    birth_village = Col('Место рождения')


class GeoStats:
    """Geo inforamtion table"""
    def __init__(self, geo_object):
        self.count = geo_object[0]
        self.region = geo_object[1]
        self.district = geo_object[2]
        self.village = geo_object[3]
