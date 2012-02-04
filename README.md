dircloud
========

Dircloud is yet another program to show and navigate through the
contents of a disc.  The key issue in this one is that it works easily
via web using a wordcloud interface with minimal dependencies.

I was looking for something like xdu (or xdiskusage) to display the
contents of a server via web in a graphical way, showing the big
directories bigger so it could be easier to see how is it used, but I
didn't find anything.  There are plenty for a desktop box, but nothing
that I like for a server to show via web.  The home page of
http://repo.or.cz/ gave me the inspiration and CSS magic.

Like the original xdu (still my favourite for desktop use), you have
to run du yourself, keeping the output in a file.

Installation
-------------

Dependecies are minimal and easily found in any Linux box.

* python
* bottle.py, the wonderful yet minimal web building framework
* du, from GNU coreutils
* locate, mlocate or sclocate, with a provision of using something
  else (here using dict as an example: http://dict.org)

On a Debian based system, bottle.py is found in the pacakge python-bottle.


Usage
-----

<pre>
$ du / >/tmp/du.out
$ python dircloud.py /tmp/du.out
 Bottle server starting up (using WSGIRefServer())...
 Listening on http://localhost:2010/
 Use Ctrl-C to quit.
</pre>

Point your browser to http://localhost:2010/


Forks, paches or comments welcome.

Ferran Jorba
Ferran.Jorba@gmail.com
