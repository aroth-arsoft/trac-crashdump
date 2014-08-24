import subprocess
import re

from pkg_resources import resource_filename
from genshi.core import Markup, START, END, TEXT
from genshi.builder import tag

from trac.core import *
from trac.web.api import IRequestHandler, ITemplateStreamFilter
from trac.web.chrome import ITemplateProvider, INavigationContributor, add_stylesheet, add_script, \
                            add_ctxtnav
from trac.ticket.model import Ticket
from trac.ticket.query import Query
from trac.config import Option, BoolOption, ChoiceOption
from trac.resource import ResourceNotFound
from trac.util import to_unicode
from trac.util.translation import _ 
from trac.util.html import html, Markup
from trac.util.text import shorten_line
from trac.util.datefmt import format_datetime, format_time, from_utimestamp
from trac.util.compat import set, sorted, partial

import os.path
import math
from .model import CrashDump
from .xmlreport import XMLReport

def hex_format(number, prefix='0x', width=None):
    if width is None:
        if number > 2**48:
            width = 16
        elif number > 2**40:
            width = 12
        elif number > 2**32:
            width = 10
        elif number > 2**24:
            width = 8
        elif number > 2**16:
            width = 6
        elif number > 2**8:
            width = 4
        else:
            width = 2
    fmt = '%%0%ix' % width
    return prefix + fmt % number

class CrashDumpModule(Component):
    """Provides support for ticket dependencies."""
    
    implements(IRequestHandler, INavigationContributor, ITemplateStreamFilter,
               ITemplateProvider)

    dumpdata_dir = Option('crashdump', 'dumpdata_dir', default='dumpdata',
                      doc='Path to the crash dump data directory.')

    crashdump_fields = set(['_crash'])
    datetime_fields = set(['crashtime', 'uploadtime', 'reporttime'])

    # INavigationContributor methods
    def get_active_navigation_item(self, req):
        return 'crashdump'

    def get_navigation_items(self, req):
        yield 'mainnav', 'crashes', tag.a(_('Crashes'), href=req.href.crashdump())

    # ITemplateStreamFilter methods
    def filter_stream(self, req, method, filename, stream, data):
        if not data:
            return stream

        # We try all at the same time to maybe catch also changed or processed templates
        if filename in ["report_view.html", "query_results.html", "ticket.html", "query.html"]:
            # For ticket.html
            if 'fields' in data and isinstance(data['fields'], list):
                for field in data['fields']:
                    for f in self.crashdump_fields:
                        if field['name'] == f and data['ticket'][f]:
                            field['rendered'] = self._link_crash(req, data['ticket'][f])
            # For query_results.html and query.html
            if 'groups' in data and isinstance(data['groups'], list):
                for group, tickets in data['groups']:
                    for ticket in tickets:
                        for f in self.crashdump_fields:
                            if f in ticket:
                                ticket[f] = self._link_crash(req, ticket[f])
            # For report_view.html
            if 'row_groups' in data and isinstance(data['row_groups'], list):
                #self.log.debug('got row_groups %s' % str(data['row_groups']))
                for group, rows in data['row_groups']:
                    for row in rows:
                        if 'cell_groups' in row and isinstance(row['cell_groups'], list):
                            for cells in row['cell_groups']:
                                for cell in cells:
                                    # If the user names column in the report differently (blockedby AS "blocked by") then this will not find it
                                    self.log.debug('got cell header %s' % str(cell.get('header', {}).get('col')))
                                    if cell.get('header', {}).get('col') in self.crashdump_fields:
                                        cell['value'] = self._link_crash(req, cell['value'])
                                        cell['header']['hidden'] = False
                                        cell['header']['title'] = 'Crashdump'
                                        self.log.debug('got crash cell %s' % str(cell))
                                    elif cell.get('header', {}).get('col') in self.datetime_fields:
                                        cell['value'] = self._format_datetime(req, cell['value'])
        return stream

    # ITemplateProvider methods
    def get_htdocs_dirs(self):
        """Return the absolute path of a directory containing additional
        static resources (such as images, style sheets, etc).
        """
        return [('crashdump', resource_filename(__name__, 'htdocs'))]

    def get_templates_dirs(self):
        """Return the absolute path of the directory containing the provided
        ClearSilver templates.
        """
        return [resource_filename(__name__, 'templates')]

    # IRequestHandler methods
    def match_request(self, req):
        if not req.path_info.startswith('/crash'):
            return False

        ret = False
        path_info = req.path_info[6:]
        action = None
        self.log.debug('match_request %s' % path_info)
        match = re.match(r'/([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})(/.+)?$', path_info)
        if match:
            req.args['crashuuid'], action  = match.groups()
            ret = True
        else:
            match = re.match(r'/([0-9]+)(/.+)?$', path_info)
            if match:
                req.args['crashid'], action  = match.groups()
                ret = True
        if ret:
            req.args['action'] = action[1:] if action else None
        self.log.debug('match_request %s' % str(req.args))
        return ret

    def process_request(self, req):
        path_info = req.path_info[6:]
        if 'crashuuid' in req.args:
            object = CrashDump.find_by_uuid(self.env, req.args['crashuuid'])
        elif 'crashid' in req.args:
            object = CrashDump.find_by_id(self.env, req.args['crashid'])
        else:
            object = None
        data = { 'object': object, 'action':req.args['action'], 'hex_format':hex_format }
        if object:
            xmlfile = self._get_dump_filename(object, 'minidumpreportxmlfile')
            xmlreport = XMLReport(xmlfile)
            for f in xmlreport.fields:
                data[f] = getattr(xmlreport, f)

        add_stylesheet(req, 'crashdump/crashdump.css')
        return 'report.html', data, None

    def _format_datetime(self, req, timestamp):
        return format_datetime(from_utimestamp(long(timestamp)))


    def _get_dump_filename(self, crashdump, name):
        item_name = getattr(crashdump, name)
        crash_file = os.path.join(self.env.path, self.dumpdata_dir, item_name)
        return crash_file

    def _link_crash(self, req, uuid):
        items = []

        try:
            crash = CrashDump(self.env, uuid)
            word = \
                tag.a(
                    '%s' % uuid,
                    class_=crash.status,
                    href=req.href('crash', uuid),
                    title=uuid
                )
        except ResourceNotFound:
            pass
        items.append(word)

        if items:
            return tag(items)
        else:
            return None
