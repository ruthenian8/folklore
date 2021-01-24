"""
DB Models of the folklore database
"""
from flask_login import LoginManager, UserMixin
from flask_sqlalchemy import SQLAlchemy

from sqlalchemy import event
from werkzeug.security import generate_password_hash

db = SQLAlchemy()
login_manager = LoginManager()


class Collectors(db.Model):
    """Collectors"""

    __tablename__ = 'collectors'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    old_id = db.Column('old_id', db.Text)
    code = db.Column('code', db.Text)
    name = db.Column('name', db.Text)

    def __repr__(self):
        return '{} ({}) {}'.format(self.id, self.old_id, self.name)


class Informators(db.Model):
    """Informants"""

    __tablename__ = 'informators'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    old_id = db.Column('old_id', db.Text)
    code = db.Column('code', db.Text)

    name = db.Column('name', db.Text)
    gender = db.Column('gender', db.Text)
    birth_year = db.Column('birth_year', db.Integer)

    bio = db.Column('bio', db.Text(4294967295))

    current_region = db.Column('current_region', db.Text)
    current_district = db.Column('current_district', db.Text)
    current_village = db.Column('current_village', db.Text)
    birth_region = db.Column('birth_region', db.Text)
    birth_district = db.Column('birth_district', db.Text)
    birth_village = db.Column('birth_village', db.Text)

    def __repr__(self):
        return '{} ({}) {} ({})'.format(self.id, self.old_id, self.name, self.current_village)


class Keywords(db.Model):
    """Keywords"""

    __tablename__ = 'keywords'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    old_id = db.Column('old_id', db.Text)
    word = db.Column('word', db.Text)
    definition = db.Column('definition', db.Text(4294967295))

    def __repr__(self):
        return '{} {}'.format(self.id, self.word)


class Questions(db.Model):
    """Questions"""
    __tablename__ = 'questions'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    question_list = db.Column('question_list', db.Text)
    question_num = db.Column('question_num', db.Integer)
    question_letter = db.Column('question_letter', db.Text(10))
    question_text = db.Column('question_text', db.Text(4294967295))
    question_full = db.Column('question_full', db.Text(4294967295))
    question_theme = db.Column('question_theme', db.Text)

    def __repr__(self):
        return '{} {} {}{} : {}'.format(
            self.id,
            self.question_list,
            self.question_num,
            self.question_letter,
            self.question_text
        )


class Texts(db.Model):
    """Text class"""

    __tablename__ = 'texts'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    old_id = db.Column('old_id', db.Text)

    year = db.Column('year', db.Integer)
    leader = db.Column('leader', db.Text)

    # region = db.Column('region', db.Text)
    # district = db.Column('district', db.Text)
    # village = db.Column('village', db.Text)
    # geo = db.Column('geo_id', db.Integer, db.ForeignKey('g_geo_text.id'))
    geo_id = db.Column('geo_id', db.Integer, db.ForeignKey('g_geo_text.id'))
    geo = db.relationship('GeoText')
    # region = db.relationship('Region')
    # district = db.relationship('District', secondary='g_geo_text')
    # village = db.relationship('Village', secondary='g_geo_text')
    address = db.Column('address', db.Text)

    raw_text = db.Column('raw_text', db.Text(4294967295))

    genre = db.Column('genre', db.Text)

    video = db.relationship('TVideo')
    audio = db.relationship('TAudio')
    images = db.relationship('TImages')

    questions = db.relationship('Questions', secondary='t_q')
    keywords = db.relationship('Keywords', secondary='t_k')

    collectors = db.relationship('Collectors', secondary='t_c')
    informators = db.relationship('Informators', secondary='t_i')

    def __repr__(self):
        return '{} ({}) {} : {}'.format(
            self.id,
            self.old_is,
            self.geo.village.name,
            self.raw_text[:100]
        )


class TC(db.Model):
    """Text + Collector pairs"""
    __tablename__ = 't_c'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    id_collector = db.Column(
        'id_collector', db.Integer, db.ForeignKey('collectors.id'))


class TI(db.Model):
    """Text + Image pairs"""
    __tablename__ = 't_i'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    id_informator = db.Column(
        'id_informator', db.Integer, db.ForeignKey('informators.id'))


class TQ(db.Model):
    """Text + Question pairs"""
    __tablename__ = 't_q'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    id_text = db.Column(
        'id_text', db.Integer, db.ForeignKey('texts.id'))
    id_question = db.Column(
        'id_question', db.Integer, db.ForeignKey('questions.id'))


class TK(db.Model):
    """Text + Keyword pairs"""
    __tablename__ = 't_k'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    id_text = db.Column(
        'id_text', db.Integer, db.ForeignKey('texts.id'))
    id_keyword = db.Column(
        'id_keyword', db.Integer, db.ForeignKey('keywords.id'))


class GeoText(db.Model):
    """Text + Geo information"""
    __tablename__ = 'g_geo_text'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)

    id_region = db.Column(
        'id_region', db.Integer, db.ForeignKey('g_regions.id'))
    region = db.relationship('Region')

    id_district = db.Column(
        'id_district', db.Integer, db.ForeignKey('g_districts.id'))
    district = db.relationship('District')

    id_village = db.Column(
        'id_village', db.Integer, db.ForeignKey('g_villages.id'))
    village = db.relationship('Village')

    def __repr__(self):
        return '{} {} {} {}'.format(
            self.id, self.region.name, self.village.name, self.district.name)


class Region(db.Model):
    """Regions"""
    __tablename__ = 'g_regions'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)

    name = db.Column(
        'region_name', db.Text(200))

    def __repr__(self):
        return '{} {}'.format(self.id, self.name)


class District(db.Model):
    """Districts"""
    __tablename__ = 'g_districts'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)

    name = db.Column(
        'district_name', db.Text(200))

    def __repr__(self):
        return '{} {}'.format(self.id, self.name)


class Village(db.Model):
    """Villages"""
    __tablename__ = 'g_villages'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)

    name = db.Column(
        'village_name', db.Text(200))

    def __repr__(self):
        return '{} {}'.format(self.id, self.name)


ROLES = {
    "admin": 0,
    "chief": 1,
    "editor": 2,
    "student": 3,
    "guest": 10
}


class User(UserMixin, db.Model):
    """User class"""

    __tablename__ = 'users'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    username = db.Column('username', db.Text(100))
    role = db.Column('role', db.Text(100))
    password = db.Column('password', db.Text(100))
    email = db.Column('email', db.Text(100))
    name = db.Column('name', db.Text(150))

    def __repr__(self):
        return '{} {}'.format(self.username, self.name)

    def has_roles(self, role):
        me = ROLES.get(self.role)
        if me is None:
            me = 100
        this = ROLES.get(role) or 0
        return me <= this

    def roles_range(self, role_lower, role_upper):
        me = ROLES.get(self.role)
        if me is None:
            me = 100
        lower = ROLES.get(role_lower) or 0
        upper = ROLES.get(role_upper) or 0
        return (lower <= me) and (me <= upper)


@event.listens_for(User.password, 'set', retval=True)
def hash_user_password(target, value, oldvalue, initiator):
    if value != oldvalue:
        return generate_password_hash(value)
    return value


class TImages(db.Model):
    """Text + Image"""
    __tablename__ = 't_images'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    imagename = db.Column('imagename', db.Text(500))

    def __repr__(self):
        return '{} {} {}'.format(self.id, self.id_text, self.imagename)


class TVideo(db.Model):
    """Text + Video"""
    __tablename__ = 't_video'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    video = db.Column('video', db.Text(500))
    start = db.Column('start', db.Integer)

    def __repr__(self):
        return '{} {} {}'.format(self.id, self.id_text, self.video)


class TAudio(db.Model):
    """Audio (currently unavailable"""
    __tablename__ = 't_audio'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    audio = db.Column('audio', db.Text(500))
    start = db.Column('start', db.Integer)


class QListName(db.Model):
    """Questionnaire name"""
    __tablename__ = 'q_list_name'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    question_list = db.Column('question_list', db.Text)
    question_list_name = db.Column('question_list_name', db.Text)

    def __repr__(self):
        return '{} {} {}'.format(
            self.id, self.question_list, self.question_list_name)


class Genres(db.Model):
    """Text genres"""

    __tablename__ = 'genres'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    genre_name = db.Column('genre_name', db.Text)

    def __repr__(self):
        return '{} {}'.format(self.id, self.genre_name)


class GTags(db.Model):
    """Gallery Tags"""
    __tablename__ = 'glr_tags'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    rus = db.Column('rus', db.Text)

    def __repr__(self):
        return '{} {}'.format(self.id, self.rus)


class GIT(db.Model):
    """Gallery Image + Tag"""
    __tablename__ = 'glr_image_tags'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    id_image = db.Column('id_image', db.Integer, db.ForeignKey('glr_images.id'))
    id_tag = db.Column('id_tag', db.Integer, db.ForeignKey('glr_tags.id'))


class GImages(db.Model):
    """Gallery Image"""
    __tablename__ = 'glr_images'

    id = db.Column(
        'id', db.Integer, primary_key=True, autoincrement=True)
    image_file = db.Column('image_id_name', db.Text)
    description = db.Column('description', db.Text)

    # legacy
    folder_path = db.Column('folder_path', db.Text)
    image_name = db.Column('image_name', db.Text)

    # tags
    tags = db.relationship('GTags', secondary='glr_image_tags')

    def __repr__(self):
        return '{} {}/{}'.format(self.id, self.folder_path, self.image_name)
