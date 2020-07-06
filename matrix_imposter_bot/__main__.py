import sys

from . import app
from . import config


debug = False
skip_prep = False

for arg in sys.argv[1:]:
    if arg == '-g':
        debug = True
    elif arg == '--skip':
        skip_prep = True
    else:
        print(f'Invalid argument: {arg}')
        sys.exit(-1)

if not skip_prep:
    from .meta import prep
    prep()
    sys.argv.append('--skip')


app.run(host=config.cfg_settings['appservice']['host'],
        port=config.cfg_settings['appservice']['port'],
        debug=debug)
