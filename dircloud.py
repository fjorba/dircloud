#!/usr/bin/python
# -*- coding: utf-8 -*-

# dircloud.py
#
# Yet another program to display the contents of a disc to see who is
# eating it using a wordcloud interface.
#
# Released under GPLv3 or later

import sys
import os
import time
import re
import fnmatch
from bottle import route, run, debug, request, response, static_file

if sys.version_info[0] == 2:
    import commands as subprocess
else:
    import subprocess

settings = {
    # Bottle specific
    'verbose': False,
    'debug': True,
    'reloader': False,

    # Server information
    'host': 'localhost',
    'port': 2010,

    # du file details
    'filename': '/tmp/du.out',
    'du_units': 1024,  # GNU's coreutils du default is 1k

    # Apache-like options
    'DocumentRoot': '/',
    'HeaderName': 'HEADER.html',
    'ReadmeName': 'README.html',
    'VersionSort': True,
    'IndexIgnore': ['*~'],
    'mimetypes': {	# Overwrite defaults, if any
        '.info': 'text/plain',
        '.dir': 'text/plain',
        },
    'robots.txt': 'User-agent: *\nDisallow: *',

    # Misc options
    'update_du_with_read_from_disk': False, # Should get rid of this one
    'search_client': 'dicoclient',
    'search_tip': 'Search files or directories',
    'checkbox_tip': 'Search using a regular expression',
    'read_from_disk_tip': 'Read the contents of the disc, bypassing the cache',
    'logo_href': 'http://localhost',
    'logo_img': 'http://localhost/whatever.png',
    }

if settings['search_client'] == 'dicoclient':
    try:
        from dicoclient import DicoClient, DicoNotConnectedError
        dico = DicoClient()
        dico.open('localhost')
    except:
        settings['search_client'] = 'locate'

sep = os.path.sep
du = {}
du_last_read = 0
read_from_disk = '!'
df = []


@route('/')
@route('/:dirpath#.+#')
def dircloud(dirpath='/'):
    global du, df
    du = read_du_file_maybe(settings['filename'])

    if not df:
        df = read_df_output()

    directory = {}
    if not dirpath.endswith(read_from_disk):
        directory = get_directory_from_du(dirpath)
    if directory:
        entries = len(directory)
        total_size = sum(directory.values())
        header = '<div class="stale_info">%s directories, <a href="/statistics">%s</a></div>' % (entries, human_readable(total_size))
        footer = ''
    else:
        if dirpath == read_from_disk:
            dirname = settings['DocumentRoot']
        else:
            dirname = settings['DocumentRoot'] + dirpath.rstrip(read_from_disk)
        if os.path.isdir(dirname):
            directory = read_directory_from_disk(dirname)
            header = read_file_if_exists(dirname, settings['HeaderName'])
            footer = read_file_if_exists(dirname, settings['ReadmeName'])
        else:
            (path, filename) = os.path.split(dirname)
            (basename, ext) = os.path.splitext(filename)
            if ext in settings['mimetypes']:
                return static_file(filename, root=path, mimetype=settings['mimetypes'][ext])
            else:
                return static_file(filename, root=path)

    cloud = make_cloud(dirpath, directory)
    page = make_html_page(dirpath=dirpath, header=header,
                          search='', body=cloud, footer=footer)

    return page


@route('/search')
def search():
    q = str(request.GET.get('q'))
    match = request.GET.get('match')
    if settings['search_client'] == 'dicoclient':
        result = dico_define(q)
        results = ''
        if 'error' in result:
            if not match == 'on':
                result = dico_match(q, [['lev', 'Maybe you mean...']])
                if 'error' in result[0][1]:
                    results = 'No files found'
                else:
                    results = dico_match2html(result)
        else:
            results = dico_define2html(result)
        if match == 'on':
            result = dico_match(q)
            results += dico_match2html(result)
    else:
        if match == 'on':
            opt = '--regex'
        else:
            opt = ''
        cmd = '/usr/bin/locate %s %s' % (opt, q)
        out = subprocess.getoutput(cmd)
        results = locate2html(out)

    page = make_html_page(dirpath='/', header='',
                          search=q, body=results)
    return page


@route('/robots.txt')
def robots():
    response.content_type = 'text/plain'
    return settings['robots.txt']


@route('/credits')
def credits_page():
    head = html_head('Credits', 'dircloud', 'dircloud')

    body = []
    body.append('<h1>Credits</h1>')
    body.append(' <ul>')
    body.append('  <li><a href="http://sd.wareonearth.com/~phil/xdu/">xdu</a> for the original graphical disk usage application.</li>')
    body.append('  <li><a href="http://repo.or.cz/">repo.or.cz</a> for inspiration and CSS for a web version.</li>')
    body.append('  <li><a href="http://bottlepy.org/">bottlepy</a> for a great minimalistic web framework.</li>')
    if settings['search_client'] == 'dicoclient':
        body.append('  <li><a href="http://www.dict.org/">dict</a> for a wonderful indexing engine.</li>')
    elif settings['search_client'] == 'locate':
        out = subprocess.getoutput('/usr/bin/locate --version')
        which_locate = out.split()[0]
        if which_locate == 'mlocate':
            url = "https://fedorahosted.org/mlocate/"
        else:
            which_locate = 'locate'
            url = "http://savannah.gnu.org/projects/findutils/"
        body.append('  <li><a href="%s">%s</a> for efficient filename searching.</li>' % (url, which_locate))
    body.append(' </ul>')

    body.append('dircloud can be found at <a href="https://github.com/fjorba/dircloud">github</a>')

    footer = '\n</body>\n\n</html>\n'

    page = head + '\n'.join(body) + footer
    return page


@route('/statistics')
def statistics_page():
    head = html_head('Statistics', 'dircloud', 'dircloud')

    body = []
    body.append('<p />')

    if settings['search_client'] == 'dicoclient':
        try:
            out = dico.show_server()
        except DicoNotConnectedError:
            dico.open('localhost')
            out = dico.show_server()
        lines = out['desc'].split('\n')
        body.append(lines.pop(0))
        body.append('<br />')
        body.append(lines.pop(0))
        body.append(' <ul>')
        while lines:
            line = lines.pop(0)
            if line:
                details = line.split()
                if details[1].isdigit():
                    body.append('  <li>%s %s</li>' % (details[1], details[0]))
        body.append(' </ul>')
    elif settings['search_client'] == 'locate':
        cmd = '/usr/bin/locate --statistics'
        out = subprocess.getoutput(cmd)
        lines = out.split('\n')
        body.append(lines.pop(0))
        body.append(' <ul>')
        while lines:
            body.append('  <li>%s</li>' % lines.pop(0))
        body.append(' </ul>')

    body.append('<p />')
    body.append('%s directories from %s' % (len(du), settings['filename']))

    space = {
        'available': df[None][0],
        'used': df[None][1],
        'free': df[None][2],
        }

    cloud = make_cloud('', space)

    body.append(cloud)
    body.append('<p />')

    footer = '\n <div class="stale_info">Page generated by <a href="/credits">dircloud<a></div>'
    footer += '\n</body>\n\n</html>\n'

    page = head + '\n'.join(body) + footer
    return page


def read_du_file_maybe(filename):
    '''Read a du tree from disk and store as dict'''
    global du
    global du_last_read
    if not du or os.path.getmtime(filename) > du_last_read:
        du_units = settings['du_units']
        f = open(filename)
        for line in f:
            fields = line.split('\t')
            size = int(fields[0]) * du_units
            name = fields[-1].lstrip('./').replace('\n', sep)
            du[name] = size
        f.close()
        if sep in du:
            del du[sep]
        du_last_read = time.time()
    return du


def get_directory_from_du(dirpath):
    '''Return a dict with the first-level names that start with
    dirpath as key, and filesize as value'''

    global du
    if dirpath in ('', '/'):
        pos = 0
        dirnames = [dirname for dirname in du if dirname.count(sep) == 1]
    else:
        pos = len(dirpath)
        n = dirpath.count(sep) + 1
        dirnames = [dirname for dirname in du if (dirname.startswith(dirpath)
                                                  and dirname.count(sep) <= n)]
        if dirpath in dirnames:
            dirnames.remove(dirpath)

    directory = {}
    for dirname in dirnames:
        directory[dirname[pos:]] = du[dirname]

    return directory


def read_directory_from_disk(dirname):
    '''Read a directory from disk and return a dict with filenames and sizes'''
    if settings['verbose']:
        print >>sys.stderr, 'Reading %s fromdisk' % (dirname)
    directory = {}
    ignored = []
    global du

    filenames = os.listdir(dirname)
    for ignore in settings['IndexIgnore']:
        ignored.extend(fnmatch.filter(filenames, ignore))
    ignored = set(ignored)

    for filename in filenames:
        if filename in ignored:
            continue
        fullpath = dirname + filename
        size = os.path.getsize(fullpath)
        dirpath = fullpath[len(settings['DocumentRoot']):]
        if os.path.isdir(fullpath):
            filename += sep
            dirpath += sep
            if dirpath in du:
                # We prefer the size of the contents, no the direntry
                size = du[dirpath]
        directory[filename] = size
        if settings['update_du_with_read_from_disk']:
            if not dirpath in du:
                if settings['verbose']:
                    print >>sys.stderr,'updating du[%s] with size %s' % (dirpath,
                                                                         size)
                du[dirpath] = size

    return directory


def read_file_if_exists(dirpath, filename):
    if dirpath and filename:
        filename = os.path.join(dirpath, filename)
        if os.path.isfile(filename):
            try:
                f = open(filename)
                contents = f.read()
                f.close()
            except IOError:
                contents = 'Cannot read %s' % (filename)
        else:
            contents = '%s not found' % (filename)
    else:
        contents = ''
    return contents


def read_df_output():
    '''Calculate free and used disc space'''

    cmd = 'LC_ALL=C /bin/df -k'
    filesystems = {}
    total_size = 0
    total_used = 0
    total_available = 0
    out = subprocess.getoutput(cmd)
    lines = out.split('\n')
    for line in lines:
        (filesystem, size, used, available, percent, mounted_on) = line.split(None, 5)
        if size.isdigit():
            size = int(size) * 1024
            used = int(used) * 1024
            available = int(available) * 1024
            filesystems[mounted_on] = [size, used, available]
            total_size += size
            total_used += used
            total_available += available
    filesystems[None] = [total_size, total_used, total_available]
    return filesystems


def make_cloud(dirpath, directory):
    if not directory:
        return ''

    dirpath = dirpath.rstrip(read_from_disk)

    names = list(directory.keys())
    if settings['VersionSort']:
        names.sort(key=version_key)
    else:
        names.sort()

    # Get the size range of our directory
    #fontsizes = ['tagcloud%d' % (i) for i in range(10)]
    fontrange = 10
    sizes = list(directory.values())
    floor = min(sizes)
    ceiling = max(sizes)
    increment = (ceiling - floor) / fontrange
    sizeranges = []
    for i in range(fontrange):
        sizeranges.append(floor + (increment * i))

    cloud = []
    cloud.append('<div id="htmltagcloud">')

    for name in names:
        filesize = directory[name]
        if min(sizes) == max(sizes):
            fontsize = fontrange // 2
        else:
            for fontsize in range(len(sizeranges)):
                if sizeranges[fontsize] >= filesize:
                    break
        cloud.append(' <span class="tagcloud%(fontsize)s" title="%(title)s"><a href="%(href)s">%(name)s</a></span>\n <span class="filesize"><a href="%(href)s%(read_from_disk)s" title="%(read_from_disk_tip)s">(%(filesize)s)</a></span>\n' %
                     { 'fontsize': fontsize,
                       'title': os.path.join(dirpath, name),
                       'href': name,
                       'name': name.rstrip(sep),
                       'read_from_disk': read_from_disk,
                       'read_from_disk_tip': settings['read_from_disk_tip'],
                       'filesize': human_readable(filesize).replace(' ',
                                                                    '&nbsp;')
                       })

    cloud.append('</div>')

    out = '\n'.join(cloud)

    return out


def make_html_page(dirpath='', header='', search='', body='', footer=''):

    href = sep
    breadcrumbs = []
    parents = dirpath.split(sep)[:-1]
    for parent in parents:
        href += parent + sep
        breadcrumbs.append('<a href="%(href)s">%(parent)s</a>' %
                           {'href': href,
                            'parent': parent,
                            })
    if settings['verbose']:
        print >>sys.stderr, 'dirpath = [%s]' % (dirpath)
    if dirpath in ('',  '/', read_from_disk):
        directory = get_directory_from_du('/')
        filesize = sum(directory.values())
        if dirpath in ('', read_from_disk):
            dirpath = sep
    else:
        filesize = du[dirpath.rstrip(read_from_disk)]
    breadcrumbs.append(' <span class="filesize"><a href="%(href)s" title="%(read_from_disk_tip)s">(%(filesize)s)</a></span>' %
                       {'href': read_from_disk,
                        'read_from_disk_tip': settings['read_from_disk_tip'],
                        'filesize': human_readable(filesize),
                        })
    breadcrumb = sep.join(breadcrumbs)

    head = html_head('Dircloud', dirpath, breadcrumb)

    form = '''
<form method="get" action="/search" enctype="application/x-www-form-urlencoded">
 <p align="center" class="searchbox">Search:
 <input type="text" name="q" value="%(search)s" title="%(search_tip)s"/>
 <input type="checkbox" name="match" title="%(checkbox_tip)s"/>Search also alternative results
</form>
</p>
''' % ({'search': search,
        'search_tip': settings['search_tip'],
        'checkbox_tip': settings['checkbox_tip']
        })

    footer += '\n <div class="stale_info">Page generated by <a href="/credits">dircloud<a></div>'
    footer += '\n</body>\n'
    footer += '\n</html>\n'

    return '\n<p>'.join((head, form, header, body, footer))


def locate2html(filenames, maxresults=1000):
    fullpaths = filenames.split('\n')
    links = []
    for fullpath in fullpaths[:maxresults]:
        (dirname, filename) = os.path.split(fullpath)
        links.append('<a href="%(dirname)s/">%(dirname)s</a>/<a href="%(fullpath)s">%(filename)s</a><br/>' %
                     {'dirname': dirname,
                      'fullpath': fullpath,
                      'filename': filename,
                      })
    if len(fullpaths) > maxresults:
        links.append('<small><i>(etc.)</i></small> <br/>')
    return '\n'.join(links)


def dico_define(q):
    try:
        result = dico.define('*', q)
    except DicoNotConnectedError:
        dico.open('localhost')
        result = dico.define('*', q)
    if 'error' in result:
        pass
    return result


def dico_define2html(result):
    out = []
    out.append(' <ol>')
    for definition in result['definitions']:
        out.append('  <li>%s: <a href="/search?q=%s">%s</a></li>' %
                   (definition['db'], definition['term'], definition['term']))
        out.append('  <ul>')
        results = definition['desc'].split('\n')[1:]
        li = []
        for result in results:
            if result.startswith('/'):
                result = href_path_maybe(result)
            elif result.count(' '):
                (key, value) = result.split(None, 1)
                key = '<a href="/search?q=%s">%s</a>' % (key, key)
                if value.startswith('/'):
                    value = href_path_maybe(value)
                result = '%s %s' % (key, value)
            li.append(result)
        for desc in li:
            out.append('   <li>%s</li>' % (desc))
        out.append('  </ul>')
    out.append(' </ol>')
    html = '\n'.join(out)
    html = html.encode('utf-8')
    return html


def href_path_maybe(dirpath):
    result = dirpath
    try:
        # Placeholder for personalisation
        pass
    except:
        pass
    return result


def get_dict_strategies(dico):
    strategies = []
    result = dico.show_strategies()
    if result['count']:
        strategies = result['strategies']
    else:
        strategies = []
    return strategies


def dico_match(q, strategies=[]):
    if not strategies:
        strategies = get_dict_strategies(dico)
    results = []
    for strategy in strategies:
        strat = strategy[0]
        result = dico.match('*', strat, q)
        results.append([strategy, result])
    return results


def dico_match2html(results):
    out = []
    for result in results:
        (strat, strategy) = result[0]
        response = result[1]
        if not 'error' in response:
            if not out:
                if len(results) == 1:
                    out.append(strategy)
                else:
                    out.append(' <ol>')
            if len(results) > 1:
                out.append('  <li>%s: %s</li>' % (strat, strategy))
            out.append('  <ul>')
            for dictionary in response['matches']:
                links = []
                for alternative in response['matches'][dictionary]:
                    links.append('<a href="/search?q=%s">%s</a>' % (alternative,
                                                                   alternative))
                out.append('<li>%s: %s</li>' % (dictionary, ' '.join(links)))
            out.append('  </ul>')
    if len(results) > 1:
        out.append(' </ol>')
    html = '\n'.join(out)
    html = html.encode('utf-8')
    return html


def version_key(value):
    '''Turn a string into a list of string and number chunks, so the
    numeric parts get sorted numerically, to allow filename
    sorting like GNU coreutils `ls -v' or Apache VersionSort
    '''
    version_re = re.compile('([0-9]+)')
    return [int(chunk) if chunk.isdigit() else chunk \
                for chunk in version_re.split(value)]


# From http://trac.edgewall.org/browser/trunk/trac/util/text.py
# def pretty_size
def human_readable(size, format='%.1f'):
    """Pretty print content size information with appropriate unit.

    :param size: number of bytes
    :param format: can be used to adjust the precision shown
    """
    if size is None:
        return ''

    jump = 1024
    if size < jump:
        return ('%s bytes' % (size))

    units = ['KB', 'MB', 'GB', 'TB']
    i = 0
    while size >= jump and i < len(units):
        i += 1
        size /= 1024.

    return (format + ' %s') % (size, units[i-1])


def html_head(name, dirpath, breadcrumb):
   return '''<html>
 <head>
  <title>%(name)s of %(dirpath)s</title>
 </head>
 %(css)s
 <body>
  <div class="page_header">
   <a title="logo" href="%(logo_href)s"><img src="%(logo_img)s" alt="logo" class="logo"/></a>
   <a href="/">%(name)s</a> of %(breadcrumb)s
  </div>
''' % ({'name': name,
        'dirpath': dirpath,
        'breadcrumb': breadcrumb,
        'css': get_css(),
        'logo_href': settings['logo_href'],
        'logo_img': settings['logo_img'],
        })


def get_css():
    return '''<style type="text/css">
body {
	font-family: sans-serif;
	font-size: small;
	border: solid #d9d8d1;
	border-width: 1px;
	margin: 10px;
	background-color: #ffffff;
	color: #000000;
}

a {
	color: #0000cc;
}

a:hover, a:active {
	color: #880000;
}

span.cntrl {
	border: 1px dashed #AAAAAA;
	margin: 0 2px;
	padding: 0 2px;
}

img.logo {
	border-width: 0;
	float: right;
}

img.avatar {
	vertical-align: middle;
}

a.list img.avatar {
	border-style: none;
}

div.page_header {
	padding: 8px;
	font-size: 150%;
	font-weight: bold;
	height: 25px;
	background-color: #d9d8d1;
}

div.page_header a:visited, a.header {
	color: #0000cc;
}

div.page_header a:hover {
	color: #880000;
}

div.page_nav {
	padding: 8px;
}

div.page_nav a:visited {
	color: #0000cc;
}

div.page_path {
	padding: 8px;
	font-weight: bold;
	border: solid #d9d8d1;
	border-width: 0px 0px 1px;
}

div.page_footer {
	height: 17px;
	padding: 4px 8px;
	background-color: #d9d8d1;
}

div.page_footer_text {
	float: left;
	color: #555555;
	font-style: italic;
}

div.page_body {
	padding: 8px;
	font-family: monospace;
}

div.title, a.title {
	display: block;
	padding: 6px 8px;
	font-weight: bold;
	background-color: #edece6;
	text-decoration: none;
	color: #000000;
}

div.stale_info {
	display: block;
	text-align: right;
	font-style: italic;
}

div.readme {
	padding: 8px;
}

#htmltagcloud {
	text-align: center;
	line-height: 1;
}

a.text:hover { text-decoration: underline; }
span.tagcloud0   { font-size: 10px; }
span.tagcloud0 a { text-decoration: none; }
span.tagcloud1   { font-size: 13px; }
span.tagcloud1 a { text-decoration: none; }
span.tagcloud2   { font-size: 16px; }
span.tagcloud2 a { text-decoration: none; }
span.tagcloud3   { font-size: 19px; }
span.tagcloud3 a { text-decoration: none; }
span.tagcloud4   { font-size: 22px; }
span.tagcloud4 a { text-decoration: none; }
span.tagcloud5   { font-size: 25px; }
span.tagcloud5 a { text-decoration: none; }
span.tagcloud6   { font-size: 28px; }
span.tagcloud6 a { text-decoration: none; }
span.tagcloud7   { font-size: 31px; }
span.tagcloud7 a { text-decoration: none; }
span.tagcloud8   { font-size: 34px; }
span.tagcloud8 a { text-decoration: none; }
span.tagcloud9   { font-size: 37px; }
span.tagcloud9 a { text-decoration: none; }
span.filesize { font-size: 9px; }
span.filesize a { text-decoration: none; }
</style>
'''


if __name__ == '__main__':
    if 'DIRCLOUD_DEBUG' in os.environ:
        settings['verbose'] = True
        settings['debug'] = True
        settings['reloader'] = True
    debug(settings['debug'])
    if len(sys.argv) > 1:
        settings['filename'] = sys.argv[1]
    run(host = settings['host'],
        port = settings['port'],
        reloader = settings['reloader'])
