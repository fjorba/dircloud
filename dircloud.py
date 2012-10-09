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
import unicodedata
import argparse
from bottle import route, run, debug, redirect, request, response, static_file

if sys.version_info[0] == 2:
    import commands as subprocess
else:
    import subprocess


class Tree():
    '''Simple tree structure, modeled after the du output.  Branches
    names are just paths (strings), and values a tuple of a numeric
    value (filesize) and an optional string (timestamp).  It provides
    some level of tolerance and self-correction for ill formed
    paths.'''

    def __init__(self, filename = '', mtime=0, atime=0, broken=False, version_sort=False):
        self.filename = filename,
        self.branches = {}
        self.empty = [0, '']
        self.mtime = mtime
        self.atime = atime
        self.broken = broken
        self.version_sort = version_sort
        self.non_disk = False

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

    def getLastDescendantName(self, name):
        '''Look for the last value (filename) of the longest branch
        (calculated as the branch with most path separators).

        Create list of pairs (n, name) where n is the number of path
        separators.  Get the largest value using the max() builtin,
        that is calculates with the first, numeric value, of the
        pairs.  As the name is the/path/name/, to isolate `name', get
        the -2 element.
        '''
        names = [(child.count(sep), child) for child in self.branches if 
                 child.startswith(name)]
        name = max(names)
        return name[-1].split(sep)[-2]

    def getBranches(self):
        names = list(self.branches)
        if self.version_sort:
            names.sort(key=version_key)
        else:
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
    du = read_du_file_maybe(args.filename)

    if not df or df.atime < du.atime:
        df = read_df_output()

    special = request.GET.get('dircloud')
    if special == 'credits':
        page = credits_page()
    elif special == 'statistics':
        page = statistics_page()
    elif special in ['available', 'size', 'used']:
        page = space_page(special)
    else:
        directory = {}
        if dirpath.endswith(read_from_disk):
            directory = du.getChildren(dirpath.rstrip(read_from_disk))
            if len(directory) == 1 and args.openfile_fallback:
                # Handle shortcut for openfile_fallback case.  It is
                # activated when the user clicks on the (number) link
                # that appears at the right of the branch and the
                # number is (1).  In that case, go straight to read
                # the final node without needing to visit each
                # descending branch.
                name = du.getLastDescendantName(dirpath.rstrip(read_from_disk))
                return openfile_fallback(name)
        else:
            # No special request.  This should be the common case.
            # Get directory for the requested path.
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
                dirname = args.document_root
            else:
                dirname = args.document_root + dirpath.rstrip(read_from_disk)
            if os.path.isdir(dirname):
                if not dirname.endswith(sep):
                    redirect(dirname + sep)
                directory = read_directory_from_disk(dirname)
                header = read_file_if_exists(dirname, args.header_name)
                footer = read_file_if_exists(dirname, args.readme_name)
            elif os.path.isfile(dirname):
                (path, filename) = os.path.split(dirname)
                (basename, ext) = os.path.splitext(filename)
                if ext in args.mimetypes:
                    return static_file(filename, root=path, mimetype=args.mimetypes[ext])
                else:
                    return static_file(filename, root=path)
            elif args.openfile_fallback:
                filename = dirname.split(sep)[-2]
                return openfile_fallback(filename)
            else:
                return 'Unknown %s' % (dirname)

        cloud = make_cloud(dirpath, directory)
        page = make_html_page(dirpath=dirpath, header=header,
                              search='', body=cloud, footer=footer)

    return page


@route('/search')
def search():
    q = str(request.GET.get('q'))
    match = request.GET.get('match')
    if args.search_client == 'dicoclient':
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
    elif args.search_client == 'locate':
        if match == 'on':
            opt = '--regex'
        else:
            opt = ''
        cmd = '/usr/bin/locate %s %s' % (opt, q)
        out = subprocess.getoutput(cmd)
        results = locate2html(out)
    elif args.search_client == 'string':
        if match == 'on':
            q = normalize_string(q)
            lines = [line for line in du.getBranches() if normalize_string(line).count(q)]
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
    return args.robots_txt


@route('/favicon.ico')
def favicon():
    '''Provide an explicit answer for the unavoidable favicon requests

    Until we have a nice icon, return nothing.'''
    response.content_type = 'image/x-icon'
    return ''


def credits_page():
    head = html_head(title='Credits', dirpath='dircloud', breadcrumb='dircloud')

    body = []
    body.append('<h1>Credits</h1>')
    body.append(' <ul>')
    body.append('  <li><a href="http://sd.wareonearth.com/~phil/xdu/">xdu</a> for the original graphical disk usage application.</li>')
    body.append('  <li><a href="http://repo.or.cz/">repo.or.cz</a> for inspiration and CSS for a web version.</li>')
    body.append('  <li><a href="http://bottlepy.org/">bottlepy</a> for a great minimalistic web framework.</li>')
    if args.search_client == 'dicoclient':
        body.append('  <li><a href="http://www.dict.org/">dict</a> for a wonderful indexing engine.</li>')
    elif args.search_client == 'locate':
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
    head = html_head(title='Statistics', dirpath=args.host,
                     breadcrumb=args.host)

    body = []
    body.append('<p />')

    if args.non_disk:
        # No disk statistics make sense for arbitrary tres
        pass
    elif args.search_client == 'dicoclient':
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
    elif args.search_client == 'locate':
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
    elif args.search_client == 'string':
        body.append(' <ul>')
        body.append('  <li>%s %s</li>' % (len(du), 'lines'))
        body.append(' </ul>')

    body.append('<p />')

    filenames = args.filename
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
        body.append('Input file %s' % (args.filename[0]))
    body.append(' <ul>')
    body.append('  <li>last modified: %s</li>' % (
                time.strftime('%Y-%m-%d %H:%M', time.localtime(du.mtime))
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
    filenames = args.filename
    filenames.remove(filename)
    filenames.insert(0, filename)
    args.filename = filenames
    du = read_du_file_maybe(args.filename)
    redirect('/')
    return du


def read_du_file_maybe(filenames):
    '''Read a du tree from disk and store as dict'''
    global du
    filename = filenames[0]
    mtime = os.path.getmtime(filename)
    if not du or mtime > du.atime or filename != du.filename:
        du = Tree(filename=filename, mtime=mtime, atime=time.time(), version_sort=args.version_sort)
        du_units = args.du_units
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
    if args.verbose:
        print >>sys.stderr, 'Reading %s fromdisk' % (dirname)
    directory = {}
    ignored = []
    global du

    filenames = os.listdir(dirname)
    for ignore in args.index_ignore:
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
        dirpath = fullpath[len(args.document_root):]
        if os.path.isdir(fullpath):
            filename += sep
            dirpath += sep
            if du.getBranch(dirpath):
                # We prefer the size of the contents, no the direntry
                values = du.getBranch(dirpath)
                size = values[0]
        directory[filename] = [size, mtime]
        if args.update_du_with_read_from_disk:
            if not dirpath in du:
                if args.verbose:
                    print >>sys.stderr,'updating du[%s] with size %s' % (dirpath,
                                                                         size)
                du[dirpath] = [size, mtime]

    return directory


def read_file_if_exists(dirpath, filename):
    if dirpath and filename:
        if os.path.isfile(os.path.join(dirpath, filename)):
            if ext in args.mimetypes:
                return static_file(filename, root=dirpath, mimetype=args.mimetypes[ext])
            else: 
                return static_file(filename, root=dirpath)
        else:
            contents = ''
    else:
        contents = ''
    return contents


def openfile_fallback(item, pre=True):
    '''Read the contents of a leaf as indicated in the
    openfile_fallback parameters

    When using dircloud to display tree-like structures that don't
    correspond to a disc directory and files, like simple catalogs,
    this funcion provides some methods to get the information of the
    final leaf, filename or record.

    Currently there are four methods: file, http(s), dict and sqlite.
    Syntax used is the canonical protocol, with a single printf-like
    %s field to indicate the record.  For sqlite, as it seems that
    there is no standard protocol syntax, we use a dict-like one, with
    two extra fields to accomodate the selected column and index
    field.

    - file://%s or file://path/%s
    - http://hostname/%s of http://hostname/whatever?field=%s
    - dict://host/d:%s or dict://host/d:%s:database
    - sqlite://path/database.db/d:%s:table:column:key

    TODO:
    - resolve how to parameterize pre
    - accept unicode strings!
    '''

    protocol = args.openfile_fallback.split(':')[0]
    contents = []

    if protocol in ['http', 'https']:
        # Web browsers already know those protocols.  Just redirect
        # and let the browser do all the job, including error handling.
        url = args.openfile_fallback % (item)
        redirect(url)
    elif protocol == 'file':
        filepath = args.openfile_fallback.replace('file://', '')
        filename =  filepath % (item)
        if os.path.isfile(filename):
            contents.append(read_file_if_exists('.', filename))
        else:
            contents.append('Cannot open %s' % (filename))
    elif protocol == 'dict':
        protocol_re = "(\w+)://([\w./]+)/d:(%s):*([\w:\*]+)*"
        (protocol, host, what, dictionary) = re.findall(protocol_re, args.openfile_fallback)[0]
        if not dictionary:
            dictionary = '*'
        try:
            fallback = DicoClient()
        except:
            contents.append('Sorry, cannot create dict client for %s' % (args.openfile_fallback))
        else:
            try:
                fallback.open(host)
            except:
                contents.append('Sorry, cannot open dict connection at %s' % (host))
            else:
                definitions = fallback.define(dictionary, item)
                if 'error' in definitions:
                    contents.append('No results found for %s at %s' % (item, args.openfile_fallback))
                else:
                    contents = [definitions['definitions'][i]['desc'] for i in range(len(definitions['definitions']))]
    elif protocol == 'sqlite':
        protocol_re = "(\w+)://([\w./]+)/d:(%s):(\w+):(\w+):(\w+)"
        (protocol, filename, what, table, column, key) = re.findall(protocol_re, args.openfile_fallback)[0]
        fallback = sqlite3.connect(filename)
        t = (item,)
        sql = 'select %(column)s from %(table)s where %(key)s=?;' % {
            'column': column,
            'table': table,
            'key': key,
            }
        for row in fallback.execute(sql, t):
            contents.append(row[0])
        if not contents:
            contents.append('No results found for %s at %s' % (item, args.openfile_fallback))
        fallback.close()

    if pre:
        out = '<pre>\n%s\n</pre>' % ('\n\n'.join(contents))
    else:
        out = '\n<p />\n'.join(contents)

    return out


def read_df_output():
    '''Calculate free and used disc space, and build a tree with tree
    branches: total size, used and available, each with filesystems as
    branches'''

    cmd = 'LC_ALL=C /bin/df -k'

    df = Tree(mtime=time.time(), atime=time.time())
    if args.non_disk:
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
        if size.isdigit() and filesystem not in args.ignore_filesystems:
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
    if args.version_sort:
        names.sort(key=version_key)
    else:
        names.sort()

    # Get the size range of our directory
    fontrange = 10
    sizes = [directory[name][0] for name in directory]
    if len(set(sizes)) == 2:
        # If there are only two different sizes, the small font size
        # would be 0 and the large 9, even if the two numbers are very
        # similar (ex., 99 and 100).  To correct that behaviour,
        # create a floor of 1 so they get a common base to be compared
        # to.  Sizes list is first converted to a set to remove
        # duplicates and we get only unique values.
        floor = 1
    else:
        floor = min(sizes)
    ceiling = max(sizes)
    increment = (ceiling - floor) / fontrange
    if not increment:
        increment = 1
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
                       'read_from_disk_tip': args.read_from_disk_tip,
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
    if args.verbose:
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
                        'read_from_disk_tip': args.read_from_disk_tip,
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
        'search_tip': args.search_tip,
        'checkbox_tip': args.checkbox_tip
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


def strip_accents(s):
    '''Remove all kinds of diacritics, accents from string.

    http://stackoverflow.com/questions/517923/what-is-the-best-way-to-remove-accents-in-a-python-unicode-string'''

    try:
        s = unicode(s,'utf-8')
    except:
        pass
    return ''.join((c for c in unicodedata.normalize('NFD', s) \
                        if unicodedata.category(c) != 'Mn'))


def normalize_string(s, alphanum=False):
    '''Strip accents and turn string lowercase.  Optionally remove non
    alphanumeric chars.
    '''

    if alphanum:
        s = strip_accents(s).lower()
        s = ''.join([c if c.isalpha() or c.isdigit() else ' ' for c in s])
        s = ' '.join(s.split())
    else:
        s = strip_accents(s).lower()
    return s


# From http://trac.edgewall.org/browser/trunk/trac/util/text.py
# def pretty_size
def human_readable(size, format='%.1f'):
    """Pretty print content size information with appropriate unit.

    :param size: number of bytes
    :param format: can be used to adjust the precision shown
    """
    if size is None:
        return ''

    if args.non_disk:
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
        'logo_href': args.logo_href,
        'logo_img': args.logo_img,
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
    parser = argparse.ArgumentParser(description='Display the contents of a disk as wordcloud')
    parser.add_argument('filename',
                        nargs='+',
                        help='input file(s), output of du command or compatible ones')

    bottle_args = parser.add_argument_group('debugging and bottle specific options')
    bottle_args.add_argument('--verbose',
                             action='store_true',
                             default=False,
                             help='verbose mode')
    bottle_args.add_argument('--debug',
                             action='store_true',
                             default=False,
                             help='debug mode')
    bottle_args.add_argument('--reloader',
                             action='store_true',
                             default=False,
                             help='reload for each script modificacion (use with care!)')

    server_args = parser.add_argument_group('web server details')
    server_args.add_argument('--host',
                             default='localhost',
                             help='server name; needed when not localhost')
    server_args.add_argument('--port',
                             default=2010,
                             type=int,
                             help='port to run the embedded web server')
    server_args.add_argument('--logo_href',
                             default='http://localhost',
                             help='Logo href')
    server_args.add_argument('--logo_img',
                             default='',
                             help='Logo source image')

    file_args = parser.add_argument_group('du file details')
    file_args.add_argument('--du_units',
                           type=int,
                           default=1024,
                           help='bytes per du block (default 1024)')
    file_args.add_argument('--non_disk',
                           action='store_true',
                           default=False,
                           help='wether we are dealing with disc data (default True)')

    apache_args = parser.add_argument_group('Apache-like options (changed CamelCase to plan_old_names)')
    apache_args.add_argument('--document_root',
                             default='/',
                             help='document root (default /)')
    apache_args.add_argument('--header_name',
                             help='file to display as header per directory, like HEADER.html for Apache')
    apache_args.add_argument('--readme_name',
                             help='file to display as footer per directory, like READE.html for Apache')
    apache_args.add_argument('--version_sort',
                             action='store_true',
                             default=True,
                             help='natural sort of (version) numbers within text (default True)')
    apache_args.add_argument('--index_ignore',
                             action='append',
                             default=['*~'],
                             help='file patterns to hide (default *~)')
    apache_args.add_argument('--mimetypes',
                             action='append',
                             default=['.dir:text/plain',
                                      '.info:text/plain',
                                      '.log:text/plain',
                                      ],
                             help='overwrite default mimetypes for certain file extensions.')
    apache_args.add_argument('--robots_txt',
                             default='User-agent: *\nDisallow: *',
                             help='robots.txt file contents (default: Disallow: * for all user agents')

    search_args = parser.add_argument_group('Searching options')
    search_args.add_argument('--search_client',
                             choices=['locate', 'dicoclient', 'string'],
                             default='locate',
                             help='search client (default: locate)')
    search_args.add_argument('--search_tip',
                             default='Search files or directories',
                             help='Search tip for search box')
    search_args.add_argument('--checkbox_tip',
                             default='Search using a regular expression',
                             help='Checkbox tip')
    search_args.add_argument('--read_from_disk_tip',
                             default='Read the contents of the disc, bypassing the cache',
                             help='Read from disk tip')

    misc_args = parser.add_argument_group('Miscellaneous options')
    misc_args.add_argument('--ignore_filesystems',
                           action='append',
                           default=['tmpfs', 'udev'],
                           help='Ignore filesystems (default: tmpfs, udev)')
    misc_args.add_argument('--update_du_with_read_from_disk',
                           action='store_true',
                           default=False,
                           help='Cache filenames read from disk into du structure (default False)')
    misc_args.add_argument('--openfile_fallback',
                           default='',
                           help='how to retrieve the final node (file://path/%%s, http://hostname/%%s, dict://host/d:%%s:database or sqlite://path/database.db/d:%%s:table:column:key)')
    args = parser.parse_args()

    # Import optional modules
    if args.openfile_fallback.startswith('sqlite'):
        import sqlite3

    if args.search_client == 'dicoclient' or args.openfile_fallback.startswith('dict'):
        try:
            from dicoclient import DicoClient, DicoNotConnectedError
            dico = DicoClient()
        except:
            args.search_client = 'locate'

    if 'DIRCLOUD_DEBUG' in os.environ:
        args.verbose = True
        args.debug = True
        args.reloader = True
    debug(args.debug)

    run(host = args.host,
        port = args.port,
        reloader = args.reloader)
