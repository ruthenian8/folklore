from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin

db = SQLAlchemy()
login_manager = LoginManager()


class Collectors(db.Model):

    __tablename__ = 'collectors'
    
    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    old_id = db.Column('old_id', db.Text)
    code = db.Column('code', db.Text)
    name = db.Column('name', db.Text)


class Informators(db.Model):

    __tablename__ = 'informators'

    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
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

class Keywords(db.Model):

    __tablename__ = 'keywords'

    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    old_id = db.Column('old_id', db.Text)
    word = db.Column('word', db.Text)
    definition = db.Column('definition', db.Text(4294967295))


class Questions(db.Model):
    __tablename__ = 'questions'
    
    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    question_list = db.Column('question_list', db.Text)
    question_num = db.Column('question_num', db.Integer)
    question_letter = db.Column('question_letter', db.Text(10))
    question_text = db.Column('question_text', db.Text(4294967295))
    question_full = db.Column('question_full', db.Text(4294967295))
    question_theme = db.Column('question_theme', db.Text)


class Texts(db.Model):

    __tablename__ = 'texts'

    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    old_id = db.Column('old_id', db.Text)

    year = db.Column('year', db.Integer)
    leader = db.Column('leader', db.Text)

    region = db.Column('region', db.Text)
    district = db.Column('district', db.Text)
    village = db.Column('village', db.Text)
    address = db.Column('address', db.Text)

    raw_text = db.Column('raw_text', db.Text(4294967295))
    view_text = db.Column('view_text', db.Text(4294967295))
    json_text = db.Column('json_text', db.Text(4294967295))

    genre = db.Column('genre', db.Text)
    
    start_text = db.Column('start_text', db.Text)
    finish_text = db.Column('finish_text', db.Text)
    start_s = db.Column('start_s', db.Integer)
    finish_s = db.Column('finish_s', db.Integer)

    video = db.relationship('TVideo')
    audio = db.relationship('TAudio')
    images = db.relationship('TImages')
        
    questions = db.relationship('Questions', secondary='t_q')
    keywords = db.relationship('Keywords', secondary='t_k')
    
    collectors = db.relationship('Collectors', secondary='t_c')
    informators = db.relationship('Informators', secondary='t_i')


class TC(db.Model):
    __tablename__ = 't_c'
    
    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    id_collector = db.Column('id_collector', db.Integer, db.ForeignKey('collectors.id'))
    
class TI(db.Model):
    __tablename__ = 't_i'

    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    id_informator = db.Column('id_informator', db.Integer, db.ForeignKey('informators.id'))

class TQ(db.Model):
    __tablename__ = 't_q'

    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    id_question = db.Column('id_question', db.Integer, db.ForeignKey('questions.id'))


class TK(db.Model):
    __tablename__ = 't_k'

    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    id_keyword = db.Column('id_keyword', db.Integer, db.ForeignKey('keywords.id'))


class User(UserMixin, db.Model):

    __tablename__ = 'users'
    
    id = db.Column('id', db.Integer, 
                primary_key=True, autoincrement=True)
    username = db.Column('username', db.Text(100))
    role = db.Column('role', db.Text(100))
    password = db.Column('password', db.Text(100))
    email = db.Column('email', db.Text(100))
    name = db.Column('name', db.Text(150))


class TImages(db.Model):
    __tablename__ = 't_images'

    id = db.Column('id', db.Integer,
                primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    imagename = db.Column('imagename', db.Text(500))


class TVideo(db.Model):
    __tablename__ = 't_video'

    id = db.Column('id', db.Integer,
                primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    video = db.Column('video', db.Text(500))
    start = db.Column('start', db.Integer)


class TAudio(db.Model):
    __tablename__ = 't_audio'

    id = db.Column('id', db.Integer,
                primary_key=True, autoincrement=True)
    id_text = db.Column('id_text', db.Integer, db.ForeignKey('texts.id'))
    audio = db.Column('audio', db.Text(500))
    start = db.Column('start', db.Integer)
