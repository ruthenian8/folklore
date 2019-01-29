import sys
# sys.path.insert(0, '.../')
# sys.path.insert(0, '.../app/')

from folklore_app import app as application, get_locale as app_get_locale
from flask_babel import Babel

babel = Babel(application)


@babel.localeselector
def get_locale():
    return app_get_locale()


if __name__ == "__main__":
    application.run(port=5000, host='localhost', debug=True)