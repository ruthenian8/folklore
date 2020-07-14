import sys
# sys.path.insert(0, '.../')
# sys.path.insert(0, '.../app/')

from folklore_app import app as application

if __name__ == "__main__":
    application.run(port=5000, host='localhost', debug=True)