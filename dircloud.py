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
import locale
from bottle import route, run, debug, redirect, request, response, static_file

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
    'bytes': True,     # False if we are dealing with non-disk trees

    # Apache-like options
    'DocumentRoot': '/',
    'HeaderName': 'HEADER.html',
    'ReadmeName': 'README.html',
    'VersionSort': True,
    'IndexIgnore': ['*~'],
    'mimetypes': {	# Overwrite defaults, if any
        '.dir': 'text/plain',
        '.info': 'text/plain',
        '.log': 'text/plain',
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
    'ignore_filesystems': [ # Linux virtual filesystems to ignore for df metrics
        'tmpfs',
        'udev'
        ],
    'help': '--help',
    }

if settings['search_client'] == 'dicoclient':
    try:
        from dicoclient import DicoClient, DicoNotConnectedError
        dico = DicoClient()
        dico.open('localhost')
    except:
        settings['search_client'] = 'locate'

class Tree():
    '''Simple tree structure, modeled after the du output.  Branches
    names are just paths (strings), and values a tuple of a numeric
    value (filesize) and an optional string (timestamp).  It provides
    some level of tolerance and self-correction for ill formed
    paths.'''

    def __init__(self, filename = '', last_read=0, broken=False):
        self.filename = filename,
        self.branches = {}
        self.empty = [0, '']
        self.last_read = last_read
        self.broken = broken
        self.bytes = True

    def __len__(self):
        return len(self.branches)

    def __getitem__(self, name):
        return self.getBranch(name)

    def addBranch(self, name, values):
        self.branches[name] = values
        if self.broken:
            # Add values to parents
            value = values[0]
            parent = self.getParentName(name)
            while parent:
                self.sumToBranch(parent, value)
                parent = self.getParentName(parent)

    def updateBranch(self, name, values):
        if not name in self.branches:
            name = self._normpath(name)
        old_value = self.branch[name][0]
        new_value = values[0]
        diff = old - new
        self.branches[name] = values
        if self.broken:
            # Sync values to parents
            parent = self.getParentName(name)
            while parent:
                self.sumToBranch(parent, diff)
                parent = self.getParentName(parent)

    def sumToBranch(self, name, value):
        if not name in self.branches:
            name = self._normpath(name)
        self.branches[name][0] += value

    def getBranch(self, name):
        if name in self.branches:
            return self.branches[name]
        else:
            name = self._normpath(name)
            if name in self.branches:
                return self.branches[name]
            else:
                return self.empty

    def getParentName(self, name):
        if not name in self.branches:
            name = self._normpath(name)
        name = name.rstrip(sep)
        n = name.count(sep)
        if n:
            parent = sep.join(name.split(sep)[:n]) + sep
            if self.broken and not parent in self.branches:
                values = self.getBranch(name)
                self.addBranch(parent, values)
            return parent
        else:
            return ''

    def delBranch(self, name):
        if not name in self.branches:
            name = self._normpath(name)
        if name in self.branches:
            # First, substact values to parents
            values = self.getBranch(name)
            value = -values[0]
            parent = self.getParentName(name)
            while parent:
                self.sumToBranch(parent, value)
                parent = self.getParentName(parent)
            del self.branches[name]

    def getChildren(self, name):
        if not name in self.branches:
            name = self._normpath(name)
        if name in ('', '/'):
            pos = 0
            names = [child for child in self.branches if (
                    child.count(sep) == 1)]
            if sep in names:
                names.remove(sep)
        else:
            pos = len(name)
            n = name.count(sep) + 1
            names = [child for child in self.branches if (
                    child.startswith(name) and child.count(sep) == n)]
        children = {}
        for name in names:
            children[name[pos:]] = self.branches[name]
        return children

    def getBranches(self):
        names = list(self.branches)
        ## VersionSort!!
        names.sort()
        return names

    def _normpath(self, name):
        if name in self.branches:
            return name
        elif name + sep in self.branches:
            return name + sep
        else:
            return os.path.normpath(name)


du = Tree()
df = []
sep = os.path.sep
read_from_disk = '!'
locale.setlocale(locale.LC_ALL, '')


@route('/')
@route('/:dirpath#.+#')
def dircloud(dirpath='/'):
    global du, df
    du = read_du_file_maybe(settings['filename'])

    if not df or df.last_read < du.last_read:
        df = read_df_output()

    special = request.GET.get('dircloud')
    if special == 'credits':
        page = credits_page()
    elif special == 'statistics':
        page = statistics_page()
    elif special in ['available', 'size', 'used']:
        page = space_page(special)
    else:
        # No special request. Create normal navigation page
        directory = {}
        if not dirpath.endswith(read_from_disk):
            directory = du.getChildren(dirpath)
            if directory and not dirpath.endswith(sep):
                redirect(dirpath + sep)
        if directory:
            entries = len(directory)
            total_size = sum([directory[name][0] for name in directory])
            header = '<div class="stale_info">%s directories, <a href="/?dircloud=statistics">%s</a></div>' % (entries, human_readable(total_size))
            footer = ''
        else:
            if dirpath == read_from_disk:
                dirname = settings['DocumentRoot']
            else:
                dirname = settings['DocumentRoot'] + dirpath.rstrip(read_from_disk)
            if os.path.isdir(dirname):
                if not dirname.endswith(sep):
                    redirect(dirname + sep)
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
    elif settings['search_client'] == 'locate':
        if match == 'on':
            opt = '--regex'
        else:
            opt = ''
        cmd = '/usr/bin/locate %s %s' % (opt, q)
        out = subprocess.getoutput(cmd)
        results = locate2html(out)
    elif settings['search_client'] == 'string':
        if match == 'on':
            q = q.lower()
            lines = [line for line in du.getBranches() if line.lower().count(q)]
        else:
            lines = [line for line in du.getBranches() if line.count(q)]
        lines.sort()
        out = '\n'.join(lines)
        results = locate2html(out)

    page = make_html_page(dirpath='/', header='',
                          search=q, body=results)
    return page


@route('/robots.txt')
def robots():
    response.content_type = 'text/plain'
    return settings['robots.txt']


def credits_page():
    head = html_head(title='Credits', dirpath='dircloud', breadcrumb='dircloud')

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


def statistics_page():
    head = html_head(title='Statistics', dirpath=settings['host'], 
                     breadcrumb=settings['host'])

    body = []
    body.append('<p />')

    if not settings['bytes']:
        # No disc statistcs make sense for arbitrary tres
        pass
    elif settings['search_client'] == 'dicoclient':
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
                    n = thousands_separator(int(details[1]))
                    body.append('  <li>%s %s</li>' % (n, details[0]))
        body.append(' </ul>')
    elif settings['search_client'] == 'locate':
        cmd = '/usr/bin/locate --statistics'
        out = subprocess.getoutput(cmd)
        lines = out.split('\n')
        body.append(lines.pop(0))
        body.append(' <ul>')
        while lines:
            line = lines.pop(0)
            if line:
                details = line.split()
                if details[0].isdigit():
                    if details[1] == 'bytes':
                        n = human_readable(int(details[0]))
                        concept = ' '.join(details[2:])
                    else:
                        n = thousands_separator(int(details[0]))
                        concept = ' '.join(details[1:])
                    body.append('  <li>%s %s</li>' % (n, concept))
        body.append(' </ul>')
    elif settings['search_client'] == 'string':
        body.append(' <ul>')
        body.append('  <li>%s %s</li>' % (len(du), 'lines'))
        body.append(' </ul>')

    body.append('<p />')

    filenames = settings['filename'].split(',')
    if len(filenames) > 1:
        # When dircloud whas called with a list of comma-separated
        # input files, this form allows the end user to change fie.
        select = []
        select.append('<form action="/switch_file">')
        select.append('Input file')
        select.append(' <select name="filename" onchange="this.form.submit()">')
        for filename in filenames:
            basename = os.path.split(filename)[-1]
            basename = os.path.splitext(basename)[0]
            select.append('  <option value="%s">%s</option>' % (filename,
                                                                filename))
        select.append(' </select>')
        select.append('</form>')
        body.append('\n'.join(select))
    else:
        body.append('Input file %s' % (settings['filename']))
    body.append(' <ul>')
    body.append('  <li>updated on %s</li>' % (
                time.strftime('%Y-%m-%d %H:%M', time.localtime(du.last_read))
                ))
    body.append('  <li>%s directories</li>' % (thousands_separator(len(du))))
    body.append(' </ul>')

    space = df.getChildren('/')
    cloud = make_cloud('space/', space, prefix='?dircloud=',
                       strip_trailing_slash=True)

    body.append(cloud)
    body.append('<p />')

    footer = '\n <div class="stale_info">Page generated by <a href="/?dircloud=credits">dircloud<a></div>'
    footer += '\n</body>\n\n</html>\n'

    page = head + '\n'.join(body) + footer
    return page


def space_page(which):
    head = html_head(title='Space', title_href='/?dircloud=statistics',
                     dirpath='dircloud', breadcrumb='dircloud')

    body = []
    body.append('<p />')

    space = df.getChildren(which)
    cloud = make_cloud('space/', space)

    body.append(cloud)
    body.append('<p />')

    footer = '\n <div class="stale_info">Page generated by <a href="/?dircloud=credits">dircloud</a></div>'
    footer += '\n</body>\n\n</html>\n'

    page = head + '\n'.join(body) + footer
    return page


@route('/switch_file')
def switch_file():
    '''Force a read of input file swapping the order of input files

    When calling dircloud with more than one input file
    (comma-separated), the default file is the first one.  This
    somewhat hasckish function puts the selected file first and forces
    a change of input file.
    '''
    global du
    filename = str(request.GET.get('filename'))
    filenames = settings['filename'].split(',')
    filenames.remove(filename)
    filenames.insert(0, filename)
    settings['filename'] = ','.join(filenames)
    du = read_du_file_maybe(filename)
    redirect('/')
    return du


def read_du_file_maybe(filenames):
    '''Read a du tree from disk and store as dict'''
    global du
    filename = filenames.split(',')[0]
    mtime = os.path.getmtime(filename)
    if not du or mtime > du.last_read or filename != du.filename:
        du = Tree(filename=filename, last_read=time.time())
        du_units = settings['du_units']
        f = open(filename)
        for line in f:
            fields = line.split('\t')
            size = int(fields[0]) * du_units
            name = fields[-1].lstrip('./').replace('\n', sep)
            if len(fields) == 3:
                mtime = fields[1]	# du --time parameter
            else:
                mtime = ''
            values = [size, mtime]
            du.addBranch(name, values)
        f.close()
        if du.getBranch(sep):
            du.delBranch(sep)
    return du


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
        fullpath = os.path.join(dirname, filename)
        size = os.path.getsize(fullpath)
        mtime = os.path.getmtime(fullpath)
        localtime = time.localtime(mtime)
        mtime = time.strftime('%Y-%m-%d %H:%M', localtime)
        dirpath = fullpath[len(settings['DocumentRoot']):]
        if os.path.isdir(fullpath):
            filename += sep
            dirpath += sep
            if du.getBranch(dirpath):
                # We prefer the size of the contents, no the direntry
                values = du.getBranch(dirpath)
                size = values[0]
        directory[filename] = [size, mtime]
        if settings['update_du_with_read_from_disk']:
            if not dirpath in du:
                if settings['verbose']:
                    print >>sys.stderr,'updating du[%s] with size %s' % (dirpath,
                                                                         size)
                du[dirpath] = [size, mtime]

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
            contents = ''
    else:
        contents = ''
    return contents


def read_df_output():
    '''Calculate free and used disc space, and build a tree with tree
    branches: total size, used and available, each with filesystems as
    branches'''

    cmd = 'LC_ALL=C /bin/df -k'

    df = Tree(last_read=time.time())
    if not settings['bytes']:
        # No disc statistcs make sense for arbitrary tres
        return df

    metrics = {
        'size': 'Total space, used and free',
        'used': 'Used space',
        'available': 'Free space available',
        }
    for metric in metrics:
        # Fill root branches with zero values
        df.addBranch(metric + sep, [0, metrics[metric]])

    bytes = {}
    out = subprocess.getoutput(cmd)
    lines = out.split('\n')
    for line in lines:
        (filesystem, size, used, available, percent, mounted_on) = line.split(None, 5)
        if size.isdigit() and filesystem not in settings['ignore_filesystems']:
            if mounted_on == '/':
                # Special case: the root filesystem.  We'll change its
                # name to 'root' to be alphanumeric and follow the
                # same rules than the others.
                mounted_on = 'root'
            bytes['size'] = int(size) * 1024
            bytes['used'] = int(used) * 1024
            bytes['available'] = int(available) * 1024
            for metric in metrics:
                # We cannot use os.path.join here because mounted_on
                # is an absolute path, and os.path.join discards all
                # previous paths components, as documented.  We can
                # use os.path.normpath, though, to remove double
                # slashes and clean it up.
                name = sep.join((metric, mounted_on))
                name = os.path.normpath(name) + sep
                values = [bytes[metric], metrics[metric]]
                df.addBranch(name, values)
                parent = metric + sep
                if parent != name:
                    # Add to root branches (metrics)
                    df.sumToBranch(parent, bytes[metric])

    return df


def make_cloud(dirpath, directory, prefix='', strip_trailing_slash=False):
    if not directory:
        return ''

    dirpath = dirpath.rstrip(read_from_disk)

    names = list(directory.keys())
    if settings['VersionSort']:
        names.sort(key=version_key)
    else:
        names.sort()

    # Get the size range of our directory
    fontrange = 10
    sizes = [directory[name][0] for name in directory]
    floor = min(sizes)
    ceiling = max(sizes)
    increment = (ceiling - floor) / fontrange
    sizeranges = []
    for i in range(fontrange):
        sizeranges.append(floor + (increment * i))

    cloud = []
    cloud.append('<div id="htmltagcloud">')

    for name in names:
        (filesize, mtime) = directory[name]
        if strip_trailing_slash:
            name = name.rstrip('/')
        if min(sizes) == max(sizes):
            fontsize = fontrange // 2
        else:
            for fontsize in range(len(sizeranges)):
                if sizeranges[fontsize] >= filesize:
                    break
        if name.endswith(sep):
            style = ''
            name_stripped = name.rstrip(sep)
            if not name_stripped:
                name_stripped = sep
        else:
            style = 'style="font-style: italic;"'
            name_stripped = name
        cloud.append(' <span class="tagcloud%(fontsize)s" title="%(title)s"><a %(style)s href="%(href)s">%(name)s</a></span>\n <span class="filesize"><a %(style)s href="%(href)s%(read_from_disk)s" title="%(read_from_disk_tip)s">(%(filesize)s)</a></span>\n' %
                     { 'fontsize': fontsize,
                       'title': mtime,
                       'href': prefix + name,
                       'style': style,
                       'name': name_stripped,
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
        directory = du.getChildren('/')
        filesize = sum([directory[name][0] for name in directory])
        if dirpath in ('', read_from_disk):
            dirpath = sep
    else:
        filesize = du[dirpath.rstrip(read_from_disk)][0]
    breadcrumbs.append(' <span class="filesize"><a href="%(href)s" title="%(read_from_disk_tip)s">(%(filesize)s)</a></span>' %
                       {'href': read_from_disk,
                        'read_from_disk_tip': settings['read_from_disk_tip'],
                        'filesize': human_readable(filesize),
                        })
    breadcrumb = sep.join(breadcrumbs)

    head = html_head(title='Dircloud', dirpath=dirpath, breadcrumb=breadcrumb)

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

    footer += '\n <div class="stale_info">Page generated by <a href="/?dircloud=credits">dircloud</a></div>'
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


def thousands_separator(n):
    '''Format n with thousands separators for readability.  Mostly
    distilled from
    http://stackoverflow.com/questions/1823058/how-to-print-number-with-commas-as-thousands-separators-in-python-2-x'''
    if sys.version_info[:2] >= (3, 1):
        return format(n, ',d')
    else:
        if n < 0:
            return '-' + thousands_separator(n)
        result = ''
        while n >= 1000:
            n, r = divmod(n, 1000)
            result = ',%03d%s' % (r, result)
        return '%d%s' % (n, result)


# From http://trac.edgewall.org/browser/trunk/trac/util/text.py
# def pretty_size
def human_readable(size, format='%.1f'):
    """Pretty print content size information with appropriate unit.

    :param size: number of bytes
    :param format: can be used to adjust the precision shown
    """
    if size is None:
        return ''

    if not settings['bytes']:
        return thousands_separator(size)

    jump = 1024
    if size < jump:
        return ('%s bytes' % (size))

    units = ['KB', 'MB', 'GB', 'TB']
    i = 0
    while size >= jump and i < len(units):
        i += 1
        size /= 1024.

    return (format + ' %s') % (size, units[i-1])


def html_head(title='Dircloud', title_href='/', dirpath='', breadcrumb=''):
   return '''<html>
 <head>
  <title>%(title)s of %(dirpath)s</title>
 </head>
 %(css)s
 <body>
  <div class="page_header">
   <a title="logo" href="%(logo_href)s"><img src="%(logo_img)s" alt="logo" class="logo"/></a>
   <a href="%(title_href)s">%(title)s</a> of %(breadcrumb)s
  </div>
''' % ({'title': title,
        'title_href': title_href,
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


def help(status):
    out = []
    for key in settings:
        out.append('  --%s' % key)
    out.sort()
    print >>sys.stderr,'\n'.join(out)
    sys.exit(status)


if __name__ == '__main__':
    if 'DIRCLOUD_DEBUG' in os.environ:
        settings['verbose'] = True
        settings['debug'] = True
        settings['reloader'] = True
    debug(settings['debug'])
    if len(sys.argv) > 1:
        args = sys.argv[1:]
        while args:
            arg = args.pop(0)
            if arg.startswith('--'):
                if arg == '--help':
                    help(0)
                else:
                    try:
                        (key, value) = arg.split('=')
                        key = key[2:]
                        if key in settings:
                            if value.isdigit():
                                value = int(value)
                            settings[key] = value
                        else:
                            print >>sys.stderr,'Unknown option: %s' % (key)
                            help(1)
                    except:
                        print >>sys.stderr,'Unknown option'
                        help(1)
        if args:
            settings['filename'] = arg
    run(host = settings['host'],
        port = settings['port'],
        reloader = settings['reloader'])
