import pkg_resources
import sqlite3
import sys

from . import app
from . import config
from . import utils
from .apputils import mx_request


def run_sql(filename):
    conn = sqlite3.connect(config.db_name)
    c = conn.cursor()
    cmds = pkg_resources.resource_string(__name__, 'sql/' + filename).decode('utf8')
    for cmd in cmds.split(';'):
        c.execute(cmd)
    conn.commit()
    conn.close()


debug = False
skip_db_prep = False
args_for_rerun = []

for arg in sys.argv[1:]:
    if arg == '-g':
        debug = True
        args_for_rerun.append(arg)
    elif arg == '--skip':
        skip = True
    else:
        print('Invalid argument: {}'.format(arg))
        sys.exit(-1)

if not skip_db_prep:
    run_sql('db_prep.sql')
    args_for_rerun.append('--skip')

sys.argv = sys.argv[:1] + args_for_rerun

def initial_setup():
    # TODO non-blocking and error checking
    r = mx_request('GET', '/_matrix/client/r0/profile/{}/avatar_url'.format(config.as_botname))
    if r.status_code == 404:
        r = mx_request('POST', '/_matrix/client/r0/register',
            json={
                'type': 'm.login.application_service',
                'username': config.as_botname[1:].split(':')[0]
            })

        if r.status_code == 200:
            initial_setup()
        else:
            return

    elif r.status_code != 200 or utils.get_from_dict(r.json(), 'avatar_url') != config.as_avatar:
        mx_request('PUT', '/_matrix/client/r0/profile/{}/avatar_url'.format(config.as_botname),
            json={'avatar_url': config.as_avatar})

    r = mx_request('GET', '/_matrix/client/r0/profile/{}/displayname'.format(config.as_botname))
    if r.status_code != 200 or utils.get_from_dict(r.json(), 'avatar_url') != config.as_disname:
        mx_request('PUT', '/_matrix/client/r0/profile/{}/displayname'.format(config.as_botname),
            json={'displayname': config.as_disname})

initial_setup()

# TODO sync any missed state!!!


# TODO use an event loop instead
from threading import Timer
def update_presence():
    mx_request('PUT', '/_matrix/client/r0/presence/{}/status'.format(config.as_botname),
        json={'presence': 'online'})
    t = Timer(30.0, update_presence)
    t.start()

update_presence()


app.run(host=config.cfg_settings['appservice']['host'],
        port=config.cfg_settings['appservice']['port'],
        debug=debug)


def on_exit():
    print('Shutting down')
    mx_request('PUT', '/_matrix/client/r0/presence/{}/status'.format(config.as_botname),
        json={'presence': 'offline'})

import atexit
atexit.register(on_exit)
