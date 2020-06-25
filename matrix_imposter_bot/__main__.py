import pkg_resources
import sqlite3
import sys

from . import app
from . import config
from .meta import prep


def run_sql(filename):
    conn = sqlite3.connect(config.db_name)
    c = conn.cursor()
    cmds = pkg_resources.resource_string(__name__, 'sql/' + filename).decode('utf8')
    for cmd in cmds.split(';\n\n'):
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
        print(f'Invalid argument: {arg}')
        sys.exit(-1)

if not skip_db_prep:
    run_sql('db_prep.sql')
    args_for_rerun.append('--skip')

sys.argv = sys.argv[:1] + args_for_rerun

prep()

app.run(host=config.cfg_settings['appservice']['host'],
        port=config.cfg_settings['appservice']['port'],
        debug=debug)
