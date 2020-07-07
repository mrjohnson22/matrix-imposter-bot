import sys

from . import app
from . import config


dev = False
debug = False
skip_prep = False

for arg in sys.argv[1:]:
    if arg == '-d':
        dev = True
    elif arg == '-g':
        debug = True
    elif arg == '--skip':
        skip_prep = True
    else:
        print(f'Invalid argument: {arg}')
        sys.exit(-1)

if debug:
    dev = True

if not skip_prep:
    from .meta import prep
    prep()
    sys.argv.append('--skip')


host=config.cfg_settings['appservice']['host']
port=config.cfg_settings['appservice']['port']

if not dev:
    from waitress import serve
    res = serve(app, host=host, port=port)
else:
    app.run(host=host, port=port, debug=debug)
