# -*- mode: python; coding: utf-8 -*-

# wsgi interface example for running dircloud under Apache.  Sample
# code based on existing wsgi and bottle docs.

import sys
import os

homedir = '/home/dircloud/www/dircloud/'
sys.path = [homedir] + sys.path

# Change working directory so relative paths (and template lookup) work again
os.chdir(homedir)

import bottle
import dircloud

# ... build or import your bottle application here ...
# Do NOT use bottle.run() with mod_wsgi
application = bottle.default_app()
