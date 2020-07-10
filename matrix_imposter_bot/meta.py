import atexit
import signal
import sys
from threading import Timer

import pkg_resources
import sqlite3
from flask import Flask

from . import config
from . import utils
from .apputils import mx_request


def run_sql(filename):
    conn = sqlite3.connect(config.db_name)
    c = conn.cursor()
    cmds = pkg_resources.resource_string(__name__, 'sql/' + filename).decode('utf8')
    for cmd in cmds.split(';\n\n'):
        c.execute(cmd)
    conn.commit()
    conn.close()


def initial_setup():
    # TODO use alembic
    run_sql('db_prep.sql')

    # TODO non-blocking and error checking
    r = mx_request('GET', f'/_matrix/client/r0/profile/{config.as_botname}/displayname', wait=True)
    if r.status_code == 404:
        r = mx_request('POST', '/_matrix/client/r0/register', wait=True,
            json={
                'type': 'm.login.application_service',
                'username': config.as_botname[1:].split(':')[0]
            })

        if r.status_code == 200:
            initial_setup()
        else:
            return

    elif r.status_code != 200 or utils.get_from_dict(r.json(), 'displayname') != config.as_disname:
        mx_request('PUT', f'/_matrix/client/r0/profile/{config.as_botname}/displayname', wait=True,
            json={'displayname': config.as_disname})

    if config.as_avatar == '':
        return
    r = mx_request('GET', f'/_matrix/client/r0/profile/{config.as_botname}/avatar_url', wait=True)
    if r.status_code != 200 or utils.get_from_dict(r.json(), 'avatar_url') != config.as_avatar:
        mx_request('PUT', f'/_matrix/client/r0/profile/{config.as_botname}/avatar_url', wait=True,
            json={'avatar_url': config.as_avatar})


def leave_bad_rooms():
    app = Flask(__name__)
    with app.app_context():
        c = utils.get_db_conn().cursor()
        r = mx_request('GET', '/_matrix/client/r0/joined_rooms')
        for room_id in r.json()['joined_rooms']:
            c.execute('SELECT 1 FROM rooms WHERE room_id=?', (room_id,))
            room_found = utils.fetchone_single(c)
            if not room_found:
                c.execute('SELECT 1 FROM control_rooms WHERE room_id=?', (room_id,))
                room_found = utils.fetchone_single(c)

            if not room_found:
                mx_request('POST', f'/_matrix/client/r0/rooms/{room_id}/leave')


timer = None
def update_presence():
    mx_request('PUT', f'/_matrix/client/r0/presence/{config.as_botname}/status', wait=True,
        json={'presence': 'online'}, verbose=False)

    global timer
    timer = Timer(20.0, update_presence)
    timer.start()

def sighandler(sig, frame):
    print(f'Caught signal {sig}')

    global timer
    if timer != None:
        timer.cancel()
        sys.exit(0)


def on_exit():
    print('Shutting down')
    mx_request('PUT', f'/_matrix/client/r0/presence/{config.as_botname}/status',
        json={'presence': 'offline'})


def prep():
    initial_setup()

    # TODO is there any other missed state to sync?
    leave_bad_rooms()

    for sig in [signal.SIGINT, signal.SIGTERM, signal.SIGQUIT]:
        signal.signal(sig, sighandler)
    update_presence()

    atexit.register(on_exit)
