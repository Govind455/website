#!/usr/bin/env python
# -*- coding: UTF-8 -*-
#
# phpMyAdmin web site generator
#
# Copyright (C) 2008 Michal Cihar <michal@cihar.com>
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License along
# with this program; if not, write to the Free Software Foundation, Inc.,
# 51 Franklin Street, Fifth Floor, Boston, MA 02110-1301 USA.

import sys
import os
import re
import glob
import shutil
import csv
import traceback
from genshi.template import TemplateLoader
from genshi.template import NewTextTemplate
from genshi.input import XML
from optparse import OptionParser

import helper.cache
import helper.log
import helper.date

import data.md5sums
import data.awards
import data.themes
import data.langnames
import data.menu
import data.screenshots
import data.redirects
import data.sf
import data.sitemap

# Project part
PROJECT_ID = 23067
PROJECT_NAME = 'phpmyadmin'

# Filtering
FILES_MARK = 'all-languages.'
BRANCH_REGEXP = re.compile('^([0-9]+\.[0-9]+)\.')
MAJOR_BRANCH_REGEXP = re.compile('^([0-9]+)\.')
TESTING_REGEXP = re.compile('.*(beta|alpha|rc).*')
SIZE_REGEXP = re.compile('.*\(([0-9]+) bytes, ([0-9]+) downloads to date')
COMMENTS_REGEXP = re.compile('^(.*)\(<a href="([^"]*)">([0-9]*) comments</a>\)$')
LANG_REGEXP ='((translation|lang|%s).*update|update.*(translation|lang|%s)|^updated?$|new lang|better word|fix.*translation)'

# Base URL (including trailing /)
SERVER = 'http://www.phpmyadmin.net'
BASE_URL = '/home_page/'
EXTENSION = 'php'

# How many security issues are shown in RSS
TOP_ISSUES = 10

# File locations
TEMPLATES = './templates'
CSS = './css'
JS = './js'
IMAGES = './images'
OUTPUT = './output'
STATIC = './static'

# Which JS files are not templates
JS_TEMPLATES = []

# Generic sourceforge.net part
PROJECT_FILES_RSS = 'https://sourceforge.net/export/rss2_projfiles.php?group_id=%d&rss_limit=100' % PROJECT_ID
PROJECT_NEWS_RSS = 'https://sourceforge.net/export/rss2_projnews.php?group_id=%d&rss_fulltext=1&limit=10' % PROJECT_ID
PROJECT_SUMMARY_RSS = 'https://sourceforge.net/export/rss2_projsummary.php?group_id=%d' % PROJECT_ID
DONATIONS_RSS = 'https://sourceforge.net/export/rss2_projdonors.php?group_id=%d&limit=20' % PROJECT_ID
PROJECT_SVN_RSS = 'http://cia.vc/stats/project/phpmyadmin/.rss'
PROJECT_DL = 'http://prdownloads.sourceforge.net/%s/%%s?download' % PROJECT_NAME
PROJECT_SVN = 'https://phpmyadmin.svn.sourceforge.net/svnroot/phpmyadmin/trunk/phpMyAdmin/'
TRANSLATIONS_SVN = '%slang/' % PROJECT_SVN

# Data sources
SVN_MD5 = 'http://dl.cihar.com/phpMyAdmin/trunk/md5.sums'
SVN_SIZES = 'http://dl.cihar.com/phpMyAdmin/trunk/files.list'

# Clean output before generating
CLEAN_OUTPUT = True

# RSS parsing
SUMMARY_DEVS = re.compile('Developers on project: ([0-9]*)')
SUMMARY_ACTIVITY = re.compile('Activity percentile \(last week\): ([0-9.]*%)')
SUMMARY_DOWNLOADS = re.compile('Downloadable files: ([0-9]*) total downloads to date')
SUMMARY_LISTS = re.compile('Mailing lists \(public\): ([0-9]*)')
SUMMARY_FORUMS = re.compile('Discussion forums \(public\): ([0-9]*), containing ([0-9]*) messages')
SUMMARY_TRACKER = re.compile('Tracker: (.*) \(([0-9]*) open/([0-9]*) total\)')

def copytree(src, dst):
    '''
    Trimmed down version of shutil.copytree. Recursively copies a directory
    tree using shutil.copy2().

    The destination directory must not already exist.
    If exception(s) occur, an Error is raised with a list of reasons.

    It handles only files and dirs and ignores .svn and *.swp* files and
    files starting with underscore (_).
    '''
    names = os.listdir(src)
    errors = []
    for name in names:
        if name == '.svn' or name.find('.swp') != -1 or name[0] == '_':
            continue
        srcname = os.path.join(src, name)
        dstname = os.path.join(dst, name)
        try:
            if os.path.isdir(srcname):
                os.makedirs(dstname)
                copytree(srcname, dstname)
            else:
                shutil.copy2(srcname, dstname)
        except (IOError, os.error), why:
            errors.append((srcname, dstname, str(why)))
        # catch the Error from the recursive copytree so that we can
        # continue with other files
        except OSError, err:
            errors.extend(err.args[0])
    if errors:
        raise OSError, errors

def fmt_bytes(number):
    '''
    Formats bytes to human readable form.
    '''
    number = int(number)
    if number > 10 * 1024 * 1024:
        return '%d MiB' % (number / ( 1024 * 1024 ))
    elif number > 1024 * 1024:
        return '%.1f MiB' % (number / ( 1024.0 * 1024 ))
    if number > 10 * 1024:
        return '%d KiB' % (number / 1024 )
    elif number > 1024:
        return '%.1f KiB' % (number / 1024.0 )
    else:
        return '%d bytes' % number

class SFGenerator:
    def __init__(self):
        self.data = {
            'releases': [],
            'releases_featured': [],
            'releases_older': [],
            'releases_beta': [],
            'themes': [],
            'news': [],
            'issues': [],
            'donations': [],
            'base_url': BASE_URL,
            'server': SERVER,
            'file_ext': EXTENSION,
            'rss_files': PROJECT_FILES_RSS,
            'rss_donations': DONATIONS_RSS,
            'rss_news': PROJECT_NEWS_RSS,
            'rss_summary': PROJECT_SUMMARY_RSS,
            'rss_security': '%s%ssecurity/index.xml' % (SERVER, BASE_URL),
            'rss_svn': PROJECT_SVN_RSS,
            'screenshots': data.screenshots.SCREENSHOTS,
            'awards': data.awards.AWARDS,
            'generated': helper.date.fmtdatetime.utcnow(),
            'themecssversions': data.themes.CSSVERSIONS,
            'sfservers': data.sf.SERVERS,
            }
        self.loader = TemplateLoader([TEMPLATES])
        self.cssloader = TemplateLoader([CSS], default_class = NewTextTemplate)
        self.staticloader = TemplateLoader([STATIC], default_class = NewTextTemplate)
        self.jsloader = TemplateLoader([JS], default_class = NewTextTemplate)
        self.feeds = helper.cache.FeedCache()
        self.urls = helper.cache.URLCache()
        self.svn = helper.cache.SVNCache(TRANSLATIONS_SVN)
        self.simplesvn = helper.cache.SimpleSVNCache(PROJECT_SVN)

    def get_outname(self, page):
        '''
        Converts page name to file name. Basically only extension is appended
        if none is already used.
        '''
        if page.find('.') == -1:
            return '%s.%s' % (page, self.data['file_ext'])
        else:
            return page

    def get_renderer(self, page):
        '''
        Returns genshi renderer type for chosen page.
        '''
        if page[:-4] == '.xml':
            return 'xml'
        return 'xhtml'

    def text_to_id(self, text):
        '''
        Converts text to something what can be used as a anchor or id (no spaces
        or other special chars).
        '''
        return re.sub('[^a-z0-9A-Z.-]', '_', text)

    def fmt_translator(self, translator):
        '''
        Formats translator information.
        '''
        lines = [x.strip() for x in translator.split('\n')]
        output = []
        for line in lines:
            try:
                name, email = line.split('(')
            except ValueError:
                name = line
                email = None
            output.append(name.strip())
        return ', '.join(output)

    def get_version_info(self, version):
        '''
        Returns description to the phpMyAdmin version.
        '''
        if version[:2] == '2.':
            text ='Version compatible with PHP 4+ and MySQL 3+.'
        elif version[:2] == '3.':
            text = 'Version compatible with PHP 5 and MySQL 5.'
        if version.find('beta1') != -1:
            text += ' First beta version.'
        elif version.find('beta2') != -1:
            text += ' Second beta version.'
        elif version.find('beta') != -1:
            helper.log.warn('Generic beta: %s' % version)
            text += ' Beta version.'
        elif version.find('rc1') != -1:
            text += ' First release candidate.'
        elif version.find('rc2') != -1:
            text += ' Second release candidate.'
        elif version.find('rc3') != -1:
            text += ' Third release candidate.'
        elif version.find('rc') != -1:
            text += ' Release candidate.'
            helper.log.warn('Generic RC: %s' % version)

        return text

    def parse_file_info(self, text):
        '''
        Parses file information from releases feed.
        '''
        m = SIZE_REGEXP.match(text)
        size = m.group(1)
        dlcount = m.group(2)
        filename = text.strip().split(' ')[0]
        url = PROJECT_DL % filename
        ext = os.path.splitext(filename)[1]
        featured = (filename.find(FILES_MARK) != -1)
        try:
            md5 = data.md5sums.md5sum[filename]
        except KeyError:
            helper.log.warn('No MD5 for %s!' % filename)
            md5 = 'N/A'
        return {
            'name': filename,
            'url': url,
            'ext': ext,
            'featured': featured,
            'size': size,
            'humansize': fmt_bytes(size),
            'dlcount': dlcount,
            'md5': md5}

    def process_releases(self, rss_downloads):
        '''
        Gets phpMyAdmin releases out of releases feed and fills releases,
        releases_beta and releases_older.
        '''
        helper.log.dbg('Processing file releases...')
        releases = []
        for entry in rss_downloads.entries:
            titleparts = entry.title.split(' ')
            type = titleparts[0]
            if type != 'phpMyAdmin':
                continue
            version = titleparts[1]
            release = {}
            release['show'] = False
            release['notes'] = entry.link
            release['version'] = version
            release['info'] = self.get_version_info(version)
            release['date'] = helper.date.fmtdatetime.parse(entry.updated)
            release['name'] = type
            release['fullname'] = '%s %s' % (type, version)
            text = entry.summary
            fileslist = text[text.find('Includes files:') + 15:]
            fileslist = fileslist[:fileslist.find('<br />')]
            release['files'] = []
            for part in fileslist.split('),'):
                release['files'].append(self.parse_file_info(part))
            releases.append(release)

        helper.log.dbg('Sorting file lists...')
        releases.sort(key = lambda x: x['version'], reverse = True)

        helper.log.dbg('Detecting versions...')
        outversions = {}
        outbetaversions = {}

        # Split up versions to branches
        for idx in xrange(len(releases)):
            version = releases[idx]
            branch = BRANCH_REGEXP.match(version['version']).group(1)
            test = TESTING_REGEXP.match(version['version'])
            if test is not None:
                try:
                    if releases[outbetaversions[branch]]['version'] < version['version']:
                        outbetaversions[branch] = idx
                except KeyError:
                    outbetaversions[branch] = idx
            else:
                try:
                    if releases[outversions[branch]]['version'] < version['version']:
                        outversions[branch] = idx
                except KeyError:
                    outversions[branch] = idx

        # Check for old beta versions
        for beta in outbetaversions.keys():
            try:
                stable_rel = releases[outversions[beta]]['version']
                beta_rel = releases[outbetaversions[beta]]['version'].split('-')[0]
                if stable_rel > beta_rel or stable_rel == beta_rel:
                    helper.log.dbg('Old beta: %s' % releases[outbetaversions[beta]]['version'])
                    del outbetaversions[beta]
            except KeyError:
                pass

        # Check for old stable releases
        for stable in outversions.keys():
            version = releases[outversions[stable]]['version']
            major_branch = MAJOR_BRANCH_REGEXP.match(version).group(1)
            for check in outversions.keys():
                check_version = releases[outversions[check]]['version']
                if major_branch == check_version[:len(major_branch)] and version < check_version:
                    helper.log.dbg('Old release: %s' % version)
                    del outversions[stable]
                    continue

        featured = max(outversions.keys())
        featured_id = outversions[featured]

        helper.log.dbg('Versions detected:')
        for idx in xrange(len(releases)):
            if idx in outversions.values():
                self.data['releases'].append(releases[idx])
                if featured_id == idx:
                    releases[idx]['info'] += ' Currently recommended version.'
                    self.data['releases_featured'].append(releases[idx])
                    helper.log.dbg(' %s (featured)' % releases[idx]['version'])
                else:
                    helper.log.dbg(' %s' % releases[idx]['version'])
            elif idx in outbetaversions.values():
                self.data['releases_beta'].append(releases[idx])
                helper.log.dbg(' %s (beta)' % releases[idx]['version'])
            else:
                self.data['releases_older'].append(releases[idx])
                helper.log.dbg(' %s (old)' % releases[idx]['version'])

    def get_snapshots_info(self):
        '''
        Retrieves SVN snapshots info and fills it in data['releases_svn'].
        '''
        md5_strings = self.urls.load(SVN_MD5).split('\n')
        size_strings = self.urls.load(SVN_SIZES).split('\n')
        md5s = {}
        for line in md5_strings:
            if line.strip() == '':
                continue
            md5, name = line.split('  ')
            md5s[name] = md5
        svn = []
        for line in size_strings:
            if line.strip() == '':
                continue
            name, size = line.split(' ')
            svn.append({
                'name' : name,
                'size' : int(size),
                'humansize' : fmt_bytes(size),
                'url' : 'http://dl.cihar.com.nyud.net/phpMyAdmin/trunk/%s' % name,
                'md5' : md5s[name],
            })
        self.data['release_svn'] = svn

    def process_themes(self, rss_downloads):
        '''
        Gets theme releases out of releases feed and fills themes.
        '''
        helper.log.dbg('Processing themes releases...')
        for entry in rss_downloads.entries:
            titleparts = entry.title.split(' ')
            type = titleparts[0]
            if type[:6] != 'theme-':
                continue
            type = type[6:]
            version = titleparts[1]
            release = {}
            release['show'] = False
            release['notes'] = entry.link
            release['version'] = version
            release['date'] = helper.date.fmtdatetime.parse(entry.updated)
            release['shortname'] = type
            release['imgname'] = 'images/themes/%s.png' % type
            try:
                release.update(data.themes.THEMES['%s-%s' % (type, version)])
            except KeyError:
                helper.log.warn('No meatadata for theme %s-%s!' % (type, version))
                release['name'] = type
                release['support'] = 'N/A'
                release['info'] = ''
            release['fullname'] = '%s %s' % (release['name'], version)
            release['classes'] = data.themes.CSSMAP[release['support']]

            text = entry.summary
            fileslist = text[text.find('Includes files:') + 15:]
            fileslist = fileslist[:fileslist.find('<br />')]
            files = fileslist.split('),')
            if len(files) > 1:
                raise Exception('Too much files in theme %s' % type)
            release['file'] = self.parse_file_info(files[0])
            self.data['themes'].append(release)

        helper.log.dbg('Sorting file lists...')
        self.data['themes'].sort(key = lambda x: x['date'], reverse = True)

    def process_news(self, feed):
        '''
        Fills in news based on news feed.
        '''
        helper.log.dbg('Processing news feed...')
        for entry in feed.entries:
            matches = COMMENTS_REGEXP.match(entry.summary)
            item = {}
            item['link'] = entry.link
            item['date'] = helper.date.fmtdatetime.parse(entry.updated)
            item['text'] = matches.group(1)
            item['comments_link'] = matches.group(2)
            item['comments_number'] = matches.group(3)
            item['title'] = entry.title
            item['anchor'] = self.text_to_id(entry.title)
            self.data['news'].append(item)

    def process_donations(self, feed):
        '''
        Fills in donations based on donations feed.
        '''
        helper.log.dbg('Processing donations feed...')
        for entry in feed.entries:
            item = {}
            item['link'] = entry.link
            item['date'] = helper.date.fmtdatetime.parse(entry.updated)
            item['text'] = entry.summary
            item['title'] = entry.title
            self.data['donations'].append(item)

    def process_summary(self, feed):
        '''
        Reads summary feed and fills some useful information into data.
        '''
        helper.log.dbg('Processing summary feed...')
        data = {}
        links = {}
        trackers = []
        for entry in feed.entries:
            if entry.title[:22] == 'Developers on project:':
                m = SUMMARY_DEVS.match(entry.title)
                data['developers'] = m.group(1)
                links['developers'] = entry.link
            elif entry.title[:19] == 'Activity percentile':
                m = SUMMARY_ACTIVITY.match(entry.title)
                data['activity'] = m.group(1)
                links['activity'] = entry.link
            elif entry.title[:19] == 'Downloadable files:':
                m = SUMMARY_DOWNLOADS.match(entry.title)
                data['downloads'] = m.group(1)
                links['downloads'] = entry.link
            elif entry.title[:13] == 'Mailing lists':
                m = SUMMARY_LISTS.match(entry.title)
                data['mailinglists'] = m.group(1)
                links['mailinglists'] = entry.link
            elif entry.title[:17] == 'Discussion forums':
                m = SUMMARY_FORUMS.match(entry.title)
                data['forums'] = m.group(1)
                data['forumposts'] = m.group(2)
                links['forums'] = entry.link
            elif entry.title[:8] == 'Tracker:':
                m = SUMMARY_TRACKER.match(entry.title)
                trackers.append({
                    'name': m.group(1),
                    'open': m.group(2),
                    'total': m.group(3),
                    'description': entry.summary[21:],
                    'link': entry.link,
                })
        self.data['info'] = data
        self.data['links'] = links
        trackers.sort(key = lambda x: x['name'])
        self.data['trackers'] = trackers

    def get_menu(self, active):
        '''
        Returns list of menu entries with marked active one.
        '''
        menu = []
        for item in data.menu.MENU:
            title = item[1]
            name = item[0]
            field = {
                'title' : title,
                'class' : {},
            }
            if name == active or '%sindex' % name == active:
                field['class'] = { 'class': 'active' }
            if len(name) > 0 and name[-1] != '/':
                name = self.get_outname(name)
            field['link'] = '%s%s' % (BASE_URL, name)
            menu.append(field)
        return menu

    def render_css(self, filename):
        '''
        Renders CSS file from template.
        '''
        helper.log.dbg('  %s' % filename)
        template = self.cssloader.load(filename)
        out = open(os.path.join(OUTPUT, 'css', filename), 'w')
        out.write(template.generate(**self.data).render())
        out.close()

    def render_static(self, templatename, outfile, extradata = {}):
        '''
        Renders "static" file from template.
        '''
        helper.log.dbg('  %s' % outfile)
        template = self.staticloader.load(templatename)
        out = open(os.path.join(OUTPUT, outfile), 'w')
        extradata.update(self.data)
        out.write(template.generate(**extradata).render())
        out.close()

    def render_js(self, filename):
        '''
        Renders JavaScript file from template. Some defined files are not processed
        through template engine as they were taken from other projects.
        '''
        helper.log.dbg('  %s' % filename)
        outpath = os.path.join(OUTPUT, 'js', filename)
        if filename not in JS_TEMPLATES:
            shutil.copy2(os.path.join(JS, filename), outpath)
            return
        template = self.jsloader.load(filename)
        out = open(outpath, 'w')
        out.write(template.generate(**self.data).render())
        out.close()

    def render(self, page):
        '''
        Renders standard page.
        '''
        helper.log.dbg('  %s' % page)
        template = self.loader.load('%s.tpl' % page)
        menu = self.get_menu(page)
        out = open(os.path.join(OUTPUT, self.get_outname(page)), 'w')
        out.write(template.generate(menu = menu, **self.data).render(self.get_renderer(page)))
        out.close()

    def render_security(self, issue):
        '''
        Renders security issue.
        '''
        helper.log.dbg('  %s' % issue)
        template = self.loader.load('security/%s' % issue)
        menu = self.get_menu('security/')
        out = open(os.path.join(OUTPUT, 'security', self.get_outname(issue)), 'w')
        out.write(template.generate(menu = menu, issue = issue, **self.data).render('xhtml'))
        out.close()


    def list_security_issues(self):
        '''
        Fills in issues and topissues with security issues information.
        '''
        issues = glob.glob('templates/security/PMASA-*')
        issues.sort(key = lambda x: int(x[24:29]) * 100 - int(x[30:]))
        for issue in issues:
            data = XML(open(issue, 'r').read())
            name = os.path.basename(issue)
            self.data['issues'].append({
                'name' : name,
                'link': '%ssecurity/%s' % (BASE_URL, self.get_outname(name)),
                'fulllink': '%s%ssecurity/%s' % (SERVER, BASE_URL, self.get_outname(name)),
                'summary': str(data.select('def[@function="announcement_summary"]/text()')),
                'date': helper.date.fmtdate.parse(str(data.select('def[@function="announcement_date"]/text()'))),
                'cve': str(data.select('def[@function="announcement_cve"]/text()')),
            })
        self.data['topissues'] = self.data['issues'][:TOP_ISSUES]

    def prepare_output(self):
        '''
        Copies static content to output and creates required directories.
        '''
        helper.log.dbg('Copying static content to output...')
        if CLEAN_OUTPUT:
            try:
                shutil.rmtree(OUTPUT)
                os.mkdir(OUTPUT)
            except OSError:
                pass
        else:
            try:
                shutil.rmtree(os.path.join(OUTPUT, 'images'))
            except OSError:
                pass
        imgdst = os.path.join(OUTPUT, 'images')
        os.makedirs(imgdst)
        copytree(IMAGES, imgdst)
        copytree(STATIC, OUTPUT)
        try:
            os.mkdir(os.path.join(OUTPUT, 'security'))
        except OSError:
            pass
        try:
            os.mkdir(os.path.join(OUTPUT, 'css'))
        except OSError:
            pass
        try:
            os.mkdir(os.path.join(OUTPUT, 'js'))
        except OSError:
            pass

    def get_sitemap_data(self, page):
        '''
        Returns metadata for page for sitemap as per http://sitemaps.org.
        '''
        priority = '0.8'
        changefreq = 'daily'
        if page[:15] == 'security/PMASA-':
            priority = '0.5'
            changefreq = 'monthly'
        elif page[:15] == '/documentation/':
            priority = '0.7'
            changefreq = 'weekly'
        elif page[:20] == '/pma_localized_docs/':
            priority = '0.6'
            changefreq = 'monthly'
        elif page in ['index', 'news']:
            priority = '1.0'
            changefreq = 'daily'
        elif page in ['improve', 'team', 'docs']:
            priority = '1.0'
            changefreq = 'weekly'
        elif page in ['downloads', 'donate', 'themes', 'translations']:
            priority = '0.9'
            changefreq = 'daily'
        elif page in ['support']:
            priority = '0.9'
            changefreq = 'weekly'
        elif page in ['sitemap']:
            priority = '0.2'
            changefreq = 'weekly'
        return {
            'lastmod' : helper.date.fmtdate.utcnow(),
            'changefreq' : changefreq,
            'priority' : priority,
        }

    def generate_sitemap(self):
        '''
        Generates list of pages with titles.
        '''
        self.data['sitemap'] = []
        self.data['sitemapxml'] = []
        helper.log.dbg('Generating sitemap:')
        for root, dirs, files in os.walk(TEMPLATES):
            if '.svn' in dirs:
                dirs.remove('.svn')  # don't visit .svn directories
            files.sort()
            dir = root[len(TEMPLATES):].strip('/')
            if len(dir) > 0:
                dir += '/'
            for file in files:
                name, ext = os.path.splitext(file)
                if ext != '.tpl' and name[:6] != 'PMASA-':
                    continue
                if name[0] in ['_', '.']:
                    continue
                if file in ['index.xml.tpl', 'sitemap.xml.tpl', '404.tpl']:
                    continue
                helper.log.dbg('- %s' % file)
                xmldata = XML(open(os.path.join(root, file), 'r').read())
                title = str(xmldata.select('def[@function="page_title"]/text()'))
                title = title.strip()
                if len(title) == 0:
                    title = str(xmldata.select('def[@function="announcement_id"]/text()'))
                    title = title.strip()
                if len(title) == 0:
                    title = 'Index'
                link = dir + self.get_outname(name)
                sitemap = {
                        'link': link,
                        'loc': '%s%s%s' % (SERVER, BASE_URL, link),
                        'title': title
                        }
                if name[:6] != 'PMASA-':
                    self.data['sitemap'].append(sitemap)
                sitemap.update(self.get_sitemap_data(dir + name))
                self.data['sitemapxml'].append(sitemap)
        for link in data.sitemap.ENTRIES:
            sitemap = {
                    'loc': SERVER + link,
                    }
            sitemap.update(self.get_sitemap_data(link))
            self.data['sitemapxml'].append(sitemap)

    def get_translation_stats(self):
        '''
        Receives translation stats from external server and parses it.
        '''
        helper.log.dbg('Processing translation stats...')
        self.data['translations'] = []
        list = self.svn.ls()
        translators = XML(self.simplesvn.cat('translators.html'))
        english = self.svn.cat('english-utf-8.inc.php')
        allmessages = len(re.compile('\n\$str').findall(english))
        for name in list:
            if name[-14:] != '-utf-8.inc.php':
                continue
            lang = name[:-14]
            try:
                baselang, ignore = lang.split('_')
            except:
                baselang = lang
            translator = translators.select('tr[@id="%s"]/td[2]/text()' % lang)
            translator = unicode(translator).strip()
            if translator == '':
                translator = translators.select('tr[@id="%s"]/td[2]/text()' % baselang)
                translator = unicode(translator).strip()
            translator = self.fmt_translator(translator)
            short = data.langnames.MAP[lang]
            helper.log.dbg(' - %s [%s]' % (lang, short))
            svnlog = self.svn.log(name)
            langs = '%s|%s|%s' % (lang, short, baselang)
            regexp = re.compile(LANG_REGEXP % (langs, langs), re.IGNORECASE)
            found = None
            if lang == 'english':
                found = svnlog[0]
            else:
                for x in svnlog:
                    if regexp.findall(x['message']) != []:
                        found = x
                        break
            content = self.svn.cat(name)
            missing = len(re.compile('\n\$str.*to translate').findall(content))
            translated = allmessages - missing
            percent = 100.0 * translated / allmessages
            if percent < 50:
                css = ' b50'
            elif percent < 80:
                css = ' b80'
            else:
                css =''
            try:
                dt = found['date']
            except TypeError:
                dt = ''
            self.data['translations'].append({
                'name': lang,
                'short': short,
                'translated': translated,
                'translator': translator,
                'percent': '%0.1f' % percent,
                'updated': dt,
                'css': css,
            })

    def fetch_data(self):
        '''
        Fetches data from remote or local sources and prepares template data.
        '''
        self.get_snapshots_info()

        rss_downloads = self.feeds.load('releases', PROJECT_FILES_RSS)
        self.process_releases(rss_downloads)
        self.process_themes(rss_downloads)

        rss_news = self.feeds.load('news', PROJECT_NEWS_RSS)
        self.process_news(rss_news)

        rss_summary = self.feeds.load('summary', PROJECT_SUMMARY_RSS)
        self.process_summary(rss_summary)

        rss_donations = self.feeds.load('donations', DONATIONS_RSS)
        self.process_donations(rss_donations)

        self.get_translation_stats()

        self.list_security_issues()

        self.generate_sitemap()

    def render_pages(self):
        '''
        Renders all content pages.
        '''
        helper.log.dbg('Rendering pages:')
        templates = [os.path.basename(x) for x in glob.glob('templates/*.tpl')]
        templates.extend([os.path.join('security', os.path.basename(x)) for x in glob.glob('templates/security/*.tpl')])
        for template in templates:
            name = os.path.splitext(template)[0]
            if os.path.basename(name)[0] == '_':
                continue
            self.render(name)

        helper.log.dbg('Rendering security issues pages:')
        for issue in self.data['issues']:
            self.render_security(issue['name'])

        helper.log.dbg('Generating CSS:')
        for css in [os.path.basename(x) for x in glob.glob('css/*.css')]:
            self.render_css(css)

        helper.log.dbg('Generating JavaScript:')
        for js in [os.path.basename(x) for x in glob.glob('js/*.js')]:
            self.render_js(js)

        helper.log.dbg('Generating static pages:')
        self.render_static('_version.php', 'version.php')
        self.render_static('_version.txt', 'version.txt')
        self.render_static('_security.php', 'security.php')
        self.render_static('_robots.txt', 'robots.txt')
        for redir in data.redirects.REDIRECTS:
            self.render_static('_redirect.tpl',
                '%s.php' % redir,
                {'location': self.get_outname(data.redirects.REDIRECTS[redir])})


    def main(self):
        '''
        Main program which does everything.
        '''
        self.prepare_output()
        self.fetch_data()
        self.render_pages()
        helper.log.dbg('Done!')

if __name__ == '__main__':
    parser = OptionParser()
    parser.add_option('-v', '--verbose',
                    action='store_true',
                    dest='verbose',
                    help='Output verbose information.')
    parser.add_option('-q', '--quiet',
                    action='store_false',
                    dest='verbose',
                    help='Only show errors and warnings.')
    parser.add_option('-C', '--clean',
                    action='store_true',
                    dest='clean',
                    help='Clean output directory (default).')
    parser.add_option('-N', '--no-clean',
                    action='store_false',
                    dest='clean',
                    help='Do  not clean output directory.')
    parser.add_option('-V', '--verbose-cache',
                    action='store_true',
                    dest='verbose_cache',
                    help='Output verbose caching information.')
    parser.add_option('-Q', '--quiet-cache',
                    action='store_false',
                    dest='verbose_cache',
                    help='No information from caching in output.')
    parser.add_option('-s', '--server',
                    action='store', type='string',
                    dest='server',
                    help='Name of server where data will be published, eg.: %s.' % SERVER)
    parser.add_option('-b', '--base-url',
                    action='store', type='string',
                    dest='base_url',
                    help='Base URL of document, eg.: %s.' % BASE_URL)
    parser.add_option('-e', '--extension',
                    action='store', type='string',
                    dest='extension',
                    help='Extension of generated files, default is %s.' % EXTENSION)
    parser.add_option('-l', '--log',
                    action='store', type='string',
                    dest='log',
                    help='Log filename, default is none.')

    parser.set_defaults(
        verbose = helper.log.VERBOSE,
        verbose_cache = helper.log.DBG_CACHE,
        server = SERVER,
        base_url = BASE_URL,
        clean = CLEAN_OUTPUT,
        log = None,
        extension = EXTENSION
        )

    (options, args) = parser.parse_args()

    helper.log.VERBOSE = options.verbose
    helper.log.DBG_CACHE = options.verbose_cache
    SERVER = options.server
    BASE_URL = options.base_url
    EXTENSION = options.extension
    CLEAN_OUTPUT = options.clean
    if options.log is not None:
        helper.log.LOG = open(options.log, 'w')

    gen = SFGenerator()
    gen.main()
