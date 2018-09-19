#!/usr/bin/env python3
"""
Script which downloads & formats an online text (article, blogpost) for printing / easier reading.

Uses pandoc, BeautifulSoup and exiftool. Can produce most formats that pandoc can output to (PDF, HTML, DOCX, EPUB, ODT,
RTF, etc.), MHT (custom generator) or ZIP archive of HTML + images.

Sample usage:
getdoc.py http://some.website.com/some-awesome-article-or-blogpost -o pdf

Installing dependencies (can be automated for Ubuntu - run `getdoc.py --setup`):
- install Python 3
- pip3 install beautifulsoup4 lxml
- install xelatex and exiftool
    - Ubuntu Linux: `sudo apt install texlive-xetex libimage-exiftool-perl`
    - Windows:
        - install `basic-miktex-*.exe` from https://www.ctan.org/tex-archive/systems/win32/miktex/setup/windows-x64
        - place `exiftool.exe` from https://sourceforge.net/projects/exiftool/files/ somewhere in your `%PATH%`

Author: Vlad Ioan Topan (vtopan/gmail)
Version: 0.1.1 (2018.09.19)
"""

import argparse
import base64
import email
import glob
import gzip
import hashlib
import mimetypes
import os
import quopri
import re
import subprocess
import sys
import tempfile
import urllib
from urllib import request
from urllib.parse import urljoin
import zipfile

try:
    from bs4 import BeautifulSoup, NavigableString, Comment
except:
    print('[!] Can\'t import BeautifulSoup; run with --setup to try to automatically install it on Ubuntu.')
    bs4 = None


USER_AGENT = 'Mozilla/5.0 (compatible; NoOS 1.0)'
REMOVE_TAGS = ('frame', 'iframe', 'embed', 'object', 'script', 'link', 'meta', 'style', 'aside', 'footer', 'form',
        'nav')
OPTIONS = {
    'cache_dir':'.dldcache',
    }

RX = {
    'sp-b-tags':(b'(>)[ \r\n\t]+(</?[a-z])',),
    'clean-fn':('[^a-z0-9 ,_.-]+', re.I),
    'merge-blanks':('[ \t\r\n]+', re.I),
    }
for k in RX:
    RX[k] = re.compile(*RX[k])

APPID = 'getdoc-by-vtopan'


def cache_path(s):
    """
    Generates the path where a URL would be cached.
    """
    h = hashlib.md5(s.encode('utf8')).hexdigest()
    if not os.path.isdir(OPTIONS['cache_dir']):
        os.makedirs(OPTIONS['cache_dir'])
    return '%s/%s' % (OPTIONS['cache_dir'], h)


def download(url, user_agent=USER_AGENT, referer=None, cache=True):
    """
    Download from a URL.
    """
    if cache:
        p = cache_path(url)
        if os.path.isfile(p):
            return 200, None, open(p, 'rb').read()
    print('[#] URL: %s' % url)
    headers = {'User-Agent':user_agent}
    if referer:
        headers['Referer'] = referer
    req = request.Request(url, headers=headers)
    r = request.urlopen(req)
    data = r.read()
    if cache:
        open(p, 'wb').write(data)
    return r.code, r.headers, data


def clean_fn(s):
    """
    Cleans a title to make it usable as a filename.
    """
    return RX['merge-blanks'].sub(' ', RX['clean-fn'].sub('', s))


def rm_by_attr(bs, tag=None, attr=None, val=None):
    """
    Remove all nodes matching the tag/attribute/values given.

    :param bs: BeautifulSoup object
    :param tag: tag name or list of names (optional)
    :param attr: attribute name (e.g. 'class', 'id', 'href', ...)
    :param val: attribute value or list of values (the value can be a string or a regex)
    """
    if type(val) not in (list, tuple):
        val = [val]
    for v in val:
        # print('[*] Looking for %s/%s/%s' % (tag, attr, v))
        nodes = bs.find_all(tag, attrs={attr:v})
        for n in nodes:
            n.extract()


def getdoc(url, filename=None, workdir='.'):
    """
    Main workhorse - retrieves an article from a URL (and the inline images) and produces the output document.
    """
    r = download(url)
    data = r[2]
    tags = set()
    fn = os.path.join(workdir, 'out.html')

    data = RX['sp-b-tags'].sub(rb'\1\2', data)
    bs = BeautifulSoup(data, 'lxml')
    obs = BeautifulSoup('<!DOCTYPE html><html><head/><body/></html>', 'lxml')
    cdiv = bs.find('article') \
            or bs.find('div', {'class':re.compile('^(post|(inner-|main_)content)$')}) \
            or bs.find('div', {'class':re.compile('^content$')}) \
            or bs.find('div', {'id':re.compile('^(content|gist-pjax-container)$')})   ## keep this generic one last
    if cdiv:
        print('[*] Found content entry (%s/#%s/.%s)...' % (cdiv.name, cdiv.get('id'), cdiv.get('class')))
        cdiv.name = 'body'
        obs.head.replace_with(bs.head)
        obs.body.replace_with(cdiv)
    else:
        obs = bs
    ## get meta before it's gone
    meta = {
        'og-sitename':(obs.find_all('meta', attrs={'name':'og:site_name'}) or [{}])[0].get('content'),
        'canonical-url':(obs.find_all('link', attrs={'rel':'canonical'}) or [{}])[0].get('href'),
        }
    ## remove tags
    for tag in obs(REMOVE_TAGS):
        tag.decompose()
    ## stackoverflow votes
    if obs.find('td', attrs={'class':'votecell'}):
        print('[*] StackOverflow-like site')
        tags.add('stackoverflow')
        for tag in obs.find_all('td', attrs={'class':'vt'}):
            tag.extract()
        rm_by_attr(obs, 'table', 'class', 'fw')
        rm_by_attr(obs, 'td', 'class', ['comment-score'])
        rm_by_attr(obs, 'div', 'class', ['post-taglist', 'answers-subheader'])
        rm_by_attr(obs, 'div', 'id', re.compile('^(tabs|comments-link-.+)$'))
        rm_by_attr(obs, 'a', 'class', 'btn-outlined')
        rm_by_attr(obs, 'a', 'title', 'feed of this question and its answers')
        ansid = 0
        ttitle = obs.body.h1
        votecells = obs.find_all('td', attrs={'class':'votecell'})
        obs.body.clear()
        obs.body.append(ttitle)
        for vc in votecells:
            vt = vc.find_parent('table')
            comment = 0
            for i, td in enumerate(vt.find_all('td', attrs={'class':'votecell'})):
                td = td.parent
                for e in td.find_all(['h1', 'h2', 'h3', 'h4', 'h5']):
                    e.name = 'h%s' % (int(e.name[1]) + 2)
                h = None
                ts = td.find_all('div', attrs={'class':'post-text'})
                if not ts:
                    ts = td.find_all('div', attrs={'class':'comment-body'})
                    if not ts:
                        continue
                    h = ('h4', 'Comments')
                    comment = 1
                elif vt.find(attrs={'class':'answercell'}):
                    ansid += 1
                    h = ('h2', 'Answer %s' % ansid)
                if h:
                    ht = obs.new_tag(h[0])
                    ht.string = h[1]
                    obs.body.append(ht)
                for e in ts:
                    obs.body.append(e)
                    if not comment:
                        e.unwrap()
                    else:
                        e.name = 'p'
    title = obs.head.title.string.strip()
    # open('out-pre.html', 'w').write(obs.prettify(formatter='html'))
    ## remove irrelevant items
    if meta['og-sitename'] == 'DigitalOcean':
        ## digitalocean
        rm_by_attr(obs, 'div', 'class', ['postable-info-bar-container', 'info-cta'])
        rm_by_attr(obs, 'h1', 'class', ['content-title'])
        rm_by_attr(obs, 'img', 'class', ['tutorial-image', 'tutorial-image-mobile'])
        rm_by_attr(obs, 'button', 'class', ['new-upvote-button'])
    ## wordpress
    rm_by_attr(obs, 'div', 'class', ('wpcnt', 'sharedaddy', 'share-subscribe'))
    rm_by_attr(obs, 'div', 'id', 'respondcon')
    ## wiki*pedia
    for tag in obs.find_all(attrs={'class':re.compile(
                '^(mw-(jump|editsection)|navbar|noprint|navigation|share-button|bottom-notice)$')}):
        # print('DEL/cls: %s' % str(tag)[:50])
        tag.decompose()
    ## wikia
    rm_by_attr(obs, 'div', 'id', 'WikiaArticleMsg')
    rm_by_attr(obs, 'span', 'class', 'editsection')
    ## gist
    rm_by_attr(obs, 'div', 'class', ['gist-file-navigation', 'js-header-wrapper', 'js-discussion'])
    rm_by_attr(obs, 'a', 'class', 'float-right')
    ## misc
    rm_by_attr(obs, 'div', 'id', 'comment_form')     # core sec blog
    for tag in obs.find_all(attrs={'id':re.compile('sidebar')}):
        tag.decompose()
    ## remove comments and empty tags
    for tag in obs.find_all(text=lambda text:isinstance(text, Comment)):
        tag.extract()
    while 1:
        changed = 0
        for tag in obs.find_all():
            if ((not tag.contents) or (len(tag.contents) == 1 and type(tag.contents[0]) == NavigableString and
                        not tag.contents[0].string.strip())) and tag.name not in ('img',):
                tag.extract()
                changed = 1
        if not changed:
            break
    for tag in obs():
        if tag.name not in ('img',) and not tag.contents:
            tag.decompose()
    ## remove div wrappers (wrapping a single other tag)
    for tag in obs.find_all('div'):
        if len(tag.contents) == 1 and tag.contents[0].name:
            tag.unwrap()
    ## fix a hrefs
    for tag in obs.find_all('a'):
        if tag.get('href') and '://' not in tag['href']:
            tag['href'] = urljoin(url, tag['href'])
    ## remove attributes
    if not OPTIONS['dbg_keepattrs']:
        for tag in obs():
            tag.attrs = {k:v for k, v in tag.attrs.items() if k in ('src', 'href', 'alt')}
    if (not filename) or len(filename) < 5:
        ext = '.html' if not filename else ('.' + filename.strip('.'))
        filename = clean_fn(obs.head.title.string) + ext
        print('[*] Guessed filename: %s' % filename)
    ## retrieve images
    for i, t in enumerate(obs.find_all('img')):
        if not t.get('src'):
            t.extract()
            continue
        src = t['src']
        if '://' not in src:
            src = urljoin(url, src)
        print('[-] Getting image [%s]...' % src.rsplit('/', 1)[-1])
        imgdata = download(src, referer=url)[2]
        ext = src.rsplit('.', 1)[-1].lower()
        if imgdata.startswith(b'\x1F\x8B'):
            ## gzip-compresed data
            imgdata = gzip.decompress(imgdata)
        if ext not in ('jpg', 'jpeg', 'png', 'gif'):
            ## attempt to identify image format by header
            if imgdata.startswith(b'\x89PNG'):
                ext = 'png'
            elif imgdata.startswith(b'GIF'):
                ext = 'gif'
            elif imgdata.startswith(b'\xFF\xD8\xFF'):
                ext = 'jpg'
            else:
                print('[!] Unknown image format (%s): %s' % (src, imgdata[:16]))
                t.extract()
                continue
        imgfn = 'image%03d.%s' % (i, ext)
        t['src'] = imgfn
        imgfull = os.path.join(workdir, imgfn)
        open(imgfull, 'wb').write(imgdata)
        if ext == 'jpg':
            out = subprocess.check_output('file "%s"' % imgfull, shell=True)
            if b'DPI' not in out:
                subprocess.call('exiftool -jfif:Xresolution=72 -jfif:Yresolution=72 -jfif:ResolutionUnit=inch %s'
                    % imgfull, shell=True)
                os.remove('%s_original' % imgfull)
    htmlfn = os.path.join(workdir, 'index.html')    # must be index.html for MHT!
    rawtext = obs.prettify(formatter='html').encode('utf8')
    open(htmlfn, 'wb').write(rawtext)
    ext = filename.lower().rsplit('.', 1)[-1]
    files = glob.glob('%s/*' % workdir)
    if ext in ('htm', 'html'):
        open(filename, 'wb').write(open(htmlfn, 'rb').read())
    elif ext == 'zip':
        zf = zipfile.ZipFile(filename, 'w', compression=zipfile.ZIP_DEFLATED)
        for f in files:
            zf.writestr(os.path.basename(f), open(f, 'rb').read())
        zf.close()
    elif ext == 'mht':
        ## MHT generation inspired by https://github.com/Modified/MHTifier/blob/master/mhtifier.py
        msg = email.message.Message()
        msg['MIME-Version'] = '1.0'
        msg['Subject'] = title
        msg['Snapshot-Content-Location'] = url
        msg['From'] = '<%s>' % APPID
        msg.add_header('Content-Type', 'multipart/related', type='text/html')
        for f in sorted(files, key=lambda x:(0,0) if 'index.html' in x else (1, x)):
            part = email.message.Message()
            mt = mimetypes.guess_type(f)[0]
            data = open(f, 'rb').read()
            if mt and mt.startswith('text/'):
                part['Content-Transfer-Encoding'] = 'quoted-printable'
                data = quopri.encodestring(data)
            else:
                part['Content-Transfer-Encoding'] = 'base64'
                data = base64.b64encode(data)
            part.set_payload(data)
            if f.endswith('index.html'):
                part.add_header('Content-Type', 'text/html', charset='utf-8')
                part['Content-Location'] = url
            else:
                part['Content-Location'] = os.path.basename(f)
                if mt:
                    part['Content-Type'] = mt
            msg.attach(part)
        open(filename, 'wb').write(msg.as_bytes())
    elif ext in ('pdf', 'epub', 'rtf', 'docx', 'odt'):
        xargs = []
        if ext == 'pdf':
            xargs = ['--pdf-engine=xelatex', '-V', 'geometry:paperwidth=210mm,paperheight=297mm,margin=1.5cm']
        fn = os.path.abspath(filename)
        print('[*] Generating %s with pandoc...' % ext)
        subprocess.call(['pandoc', '-s', htmlfn, '-o', fn] + xargs, cwd=workdir)
    else:
        raise ValueError('[!] Invalid / unknown output format [%s]!' % ext)
    if os.path.isfile(filename):
        print('[*] Document [%s] created.' % filename)
    else:
        print('[!] Failed creating document!')


argp = argparse.ArgumentParser()
argp.add_argument('url', help='Document / article URL')
argp.add_argument('-S', '--setup', help='Install required libs/packages on Ubuntu', action='store_true')
argp.add_argument('-o', '--output', help='Output filename (extension controls format)', default='out.html')
argp.add_argument('-dk', '--dbg-keepattrs', help='Keep tag attributes for debugging', action='store_true')
argp.add_argument('-cd', '--cache-dir', help='Download cache dir', default=OPTIONS['cache_dir'])
args = argp.parse_args()
OPTIONS.update(vars(args))

if args.setup:
    print('[*] Installing xelatex (texlive-xetex) and exiftool (libimage-exiftool-perl)...')
    os.system('sudo apt install python3 texlive-xetex libimage-exiftool-perl')
    print('[*] Installing the BeautifulSoup 4 and lxml Python packages...')
    os.system('pip3 install --user beautifulsoup4 lxml')
    sys.exit('[*] Installed all required packages/modules.')

with tempfile.TemporaryDirectory() as tempd:
    getdoc(args.url, args.output, tempd)

