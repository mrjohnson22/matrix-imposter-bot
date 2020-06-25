from flask import Flask


app = Flask(__name__)

from . import main

def start():
    from .meta import prep
    prep()
    return app
