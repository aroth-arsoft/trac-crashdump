import subprocess
import re

from pkg_resources import resource_filename
from genshi.core import Markup, START, END, TEXT
from genshi.builder import tag

from trac.core import *
from trac.web.api import IRequestHandler, IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import (
    Chrome, INavigationContributor, ITemplateProvider,
    add_ctxtnav, add_link, add_notice, add_script, add_script_data,
    add_stylesheet, add_warning, auth_link, prevnext_nav, web_context
)
from trac.web import (
    arg_list_to_args, parse_arg_list
)
from trac.ticket.model import Milestone, Ticket, group_milestones
from trac.ticket.query import Query
from trac.config import Option, BoolOption, ChoiceOption
from trac.attachment import AttachmentModule
from trac.mimeview.api import Mimeview, IContentConverter
from trac.resource import (
    Resource, ResourceNotFound, get_resource_url, render_resource_link,
    get_resource_shortname
)
from trac.util import to_unicode, as_bool, as_int, get_reporter_id
from trac.util.translation import _ 
from trac.util.html import html, Markup
from trac.util.text import (
    exception_to_unicode, empty, obfuscate_email_address, shorten_line,
    to_unicode
)

from trac.util.datefmt import format_datetime, format_time, from_utimestamp, to_utimestamp
from trac.util.compat import set, sorted, partial
import os.path
import math
import time
from .model import CrashDump, CrashDumpTicketLinks
from .api import CrashDumpSystem
from .xmlreport import XMLReport

def hex_format(number, prefix='0x', width=None):
    if number is None:
        return '(none)'
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

def excection_code(platform_type, code, name):
    if platform_type == 'Linux':
        return tag.a(name + '(' + hex_format(code) + ')', href='http://en.wikipedia.org/wiki/Unix_signal')
    elif platform_type == 'Windows':
        return tag.a(name + '(' + hex_format(code) + ')', href='http://msdn.microsoft.com/en-us/library/windows/desktop/ms679356(v=vs.85).aspx')
    else:
        return name + '(' + hex_format(code) + ')'

def format_bool_yesno(val):
    if val is None:
        return '(none)'
    elif val == True:
        return _('yes')
    elif val == False:
        return _('no')
    else:
        return _('neither')

def format_source_line(source, line, line_offset=None, source_url=None):
    if source is None:
        return _('unknown')
    else:
        title = str(source) + ':' + str(line)
        if line_offset is not None:
            title += '+' + hex_format(line_offset)
        if source_url is not None:
            href = source_url
        else:
            href='file:///' + str(source)
        return tag.a(title, href=href)

def str_or_unknown(str):
    if str is None:
        return _('unknown')
    else:
        return str

class CrashDumpModule(Component):
    """Provides support for ticket dependencies."""
    
    implements(IRequestHandler, IRequestFilter, INavigationContributor, ITemplateStreamFilter,
               ITemplateProvider)

    dumpdata_dir = Option('crashdump', 'dumpdata_dir', default='dumpdata',
                      doc='Path to the crash dump data directory.')

    crashlink_query = Option('crashdump', 'crashlink_query',
        default='?status=!closed',
        doc="""The base query to be used when linkifying values of ticket
            fields. The query is a URL query
            string starting with `?` as used in `query:`
            [TracQuery#UsingTracLinks Trac links].
            (''since 0.12'')""")

    crashdump_fields = set(['_crash'])
    datetime_fields = set(['crashtime', 'uploadtime', 'reporttime'])
    crashdump_link_fields = set(['linked_crash'])

    @property
    def must_preserve_newlines(self):
        return True

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
                    for f in self.crashdump_link_fields:
                        if field['name'] == f and data['ticket'][f]:
                            field['rendered'] = self._link_crashes_by_id(req, data['ticket'][f])
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

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type):
        if req.path_info.startswith('/ticket/'):
            # In case of an invalid ticket, the data is invalid
            if not data:
                return template, data, content_type
            tkt = data['ticket']
            links = CrashDumpTicketLinks(self.env, tkt)

            for change in data.get('changes', {}):
                if not change.has_key('fields'):
                    continue
                for field, field_data in change['fields'].iteritems():
                    if field in self.crashdump_link_fields:
                        if field_data['new'].strip():
                            new = set([int(n) for n in field_data['new'].split(',')])
                        else:
                            new = set()
                        if field_data['old'].strip():
                            old = set([int(n) for n in field_data['old'].split(',')])
                        else:
                            old = set()
                        add = new - old
                        sub = old - new
                        elms = tag()
                        if add:
                            elms.append(
                                tag.em(u', '.join([unicode(n) for n in sorted(add)]))
                            )
                            elms.append(u' added')
                        if add and sub:
                            elms.append(u'; ')
                        if sub:
                            elms.append(
                                tag.em(u', '.join([unicode(n) for n in sorted(sub)]))
                            )
                            elms.append(u' removed')
                        field_data['rendered'] = elms

        return template, data, content_type

    def _prepare_data(self, req, crashobj, absurls=False):
        data = {'object': crashobj,
                'to_utimestamp': to_utimestamp,
                'hex_format':hex_format,
                'excection_code': excection_code,
                'format_bool_yesno': format_bool_yesno,
                'format_source_line': format_source_line,
                'str_or_unknown': str_or_unknown,
                'context': web_context(req, crashobj.resource, absurls=absurls),
                'preserve_newlines': self.must_preserve_newlines,
                'emtpy': empty}
        xmlfile = self._get_dump_filename(crashobj, 'minidumpreportxmlfile')
        if xmlfile:
            start = time.time()
            xmlreport = XMLReport(xmlfile)
            for f in xmlreport.fields:
                data[f] = getattr(xmlreport, f)
            end = time.time()
            data['parsetime'] = end - start
        return data

    def _get_prefs(self, req):
        return {'comments_order': req.session.get('ticket_comments_order',
                                                  'oldest'),
                'comments_only': req.session.get('ticket_comments_only',
                                                 'false')}

    def process_request(self, req):
        path_info = req.path_info[6:]
        start = time.time()
        if 'crashuuid' in req.args:
            crashobj = CrashDump.find_by_uuid(self.env, req.args['crashuuid'])
            if not crashobj:
                raise ResourceNotFound(_("Crash %(id)s does not exist.",
                                        id=req.args['crashuuid']), _("Invalid crash identifier"))
        elif 'crashid' in req.args:
            crashobj = CrashDump.find_by_id(self.env, req.args['crashid'])
            if not crashobj:
                raise ResourceNotFound(_("Crash %(id)s does not exist.",
                                        id=req.args['crashid']), _("Invalid crash identifier"))
        else:
            raise ResourceNotFound(_("No crash identifier specified."))
        end = time.time()
        xhr = req.get_header('X-Requested-With') == 'XMLHttpRequest'

        #req.perm('crash', id, version).require('TICKET_VIEW')
        action = req.args.get('action', ('history' in req.args and 'history' or
                                        'view'))
        data = self._prepare_data(req, crashobj)
        data['dbtime'] = end - start

        linked_tickets = []
        for tkt_id in crashobj.linked_tickets:
            a = self._link_ticket_by_id(req, tkt_id)
            if a:
                linked_tickets.append(a)

        field_changes = {}
        data.update({'action': None,
                    # Store a timestamp for detecting "mid air collisions"
                    'start_time': crashobj['changetime'],
                    'linked_tickets':linked_tickets
                    })

        self._insert_crashdump_data(req, crashobj, data,
                                get_reporter_id(req, 'author'), field_changes)

        add_script_data(req, {'comments_prefs': self._get_prefs(req)})
        add_stylesheet(req, 'crashdump/crashdump.css')
        add_script(req, 'common/js/folding.js')

        return 'report.html', data, None

    def _query_link(self, req, name, value, text=None):
        """Return a link to /query with the appropriate name and value"""
        default_query = self.crashlink_query.lstrip('?')
        args = arg_list_to_args(parse_arg_list(default_query))
        args[name] = value
        if name == 'resolution':
            args['status'] = 'closed'
        return tag.a(text or value, href=req.href.query(args))

    def _insert_crashdump_data(self, req, crashobj, data, author_id, field_changes):
        """Insert crashobj data into the template `data`"""
        replyto = req.args.get('replyto')
        data['replyto'] = replyto
        data['version'] = crashobj.resource.version
        data['description_change'] = None
        data['author_id'] = author_id

        if crashobj.resource.version is not None:
            crashobj.values.update(values)

        context = web_context(req, crashobj.resource)

        # Display the owner and reporter links when not obfuscated
        chrome = Chrome(self.env)
        for user in 'reporter', 'owner':
            if chrome.format_author(req, crashobj[user]) == crashobj[user]:
                data['%s_link' % user] = self._query_link(req, user,
                                                          crashobj[user])
        data['context'] = context

    def _format_datetime(self, req, timestamp):
        return format_datetime(from_utimestamp(long(timestamp)))

    def _get_dump_filename(self, crashobj, name):
        item_name = crashobj[name]
        crash_file = os.path.join(self.env.path, self.dumpdata_dir, item_name)
        return crash_file

    def _link_ticket_by_id(self, req, ticketid):
        ret = None
        try:
            ticket = Ticket(self.env, ticketid)
            if 'TICKET_VIEW' in req.perm(ticket.resource):
                ret = \
                    tag.a(
                        '#%s' % ticket.id,
                        class_=ticket['status'],
                        href=req.href.ticket(int(ticket.id)),
                        title=shorten_line(ticket['summary'])
                    )
        except ResourceNotFound:
            pass
        return ret

    def _link_crash_by_id(self, req, id):
        ret = None
        try:
            crash = CrashDump(env=self.env, id=id)
            ret = \
                tag.a(
                    'CrashId#%i' % crash.id,
                    class_=crash.status,
                    href=req.href('crash', crash['uuid']),
                    title=crash['uuid']
                )
        except ResourceNotFound:
            pass
        return ret

    def _link_crashes_by_id(self, req, ids):
        items = []

        for i, word in enumerate(re.split(r'([;,\s]+)', ids)):
            if i % 2:
                items.append(word)
            elif word:
                crashid = word
                word = 'CrashId#%s' % word

                try:
                    crash = CrashDump(env=self.env, id=crashid)
                    word = \
                        tag.a(
                            'CrashId#%i' % crash.id,
                            class_=crash.status,
                            href=req.href('crash', crash['uuid']),
                            title=crash['uuid']
                        )
                except ResourceNotFound:
                    pass
                items.append(word)

        if items:
            return tag(items)
        else:
            return None

    def _link_crash(self, req, uuid):
        ret = None
        try:
            crash = CrashDump(env=self.env, uuid=uuid)
            ret = \
                tag.a(
                    'CrashId#%i' % crash.id,
                    class_=crash.status,
                    href=req.href('crash', crash['uuid']),
                    title=crash['uuid']
                )
        except ResourceNotFound:
            pass
        return ret

