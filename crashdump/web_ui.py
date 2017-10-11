#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import subprocess
import re

from pkg_resources import resource_filename
from genshi.core import Markup, START, END, TEXT
from genshi.builder import tag

from trac.core import *
from trac.web.api import IRequestHandler, IRequestFilter, ITemplateStreamFilter
from trac.web.chrome import (
    Chrome, ITemplateProvider,
    add_ctxtnav, add_link, add_notice, add_script, add_script_data,
    add_stylesheet, add_warning, auth_link, prevnext_nav, web_context
)
from trac.web import (
    arg_list_to_args, parse_arg_list
)
from trac.ticket.model import Milestone, Ticket, group_milestones
from trac.ticket.query import Query
from trac.config import Option, PathOption
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
from .model import CrashDump
from .links import CrashDumpTicketLinks
from .api import CrashDumpSystem
from .xmlreport import XMLReport
from .utils import *

def safe_list_get_as_int (l, idx, default=None):
    try:
        try:
            return int(l[idx])
        except ValueError:
            return default
    except IndexError:
        return default

class CrashDumpModule(Component):
    """UI for crash dumps."""
    
    implements(IRequestHandler, IRequestFilter, ITemplateStreamFilter,
               ITemplateProvider)

    dumpdata_dir = PathOption('crashdump', 'dumpdata_dir', default='../dumpdata',
                      doc='Path to the crash dump data directory relative to the environment conf directory.')

    crashlink_query = Option('crashdump', 'crashlink_query',
        default='?status=!closed',
        doc="""The base query to be used when linkifying values of ticket
            fields. The query is a URL query
            string starting with `?` as used in `query:`
            [TracQuery#UsingTracLinks Trac links].
            (''since 0.12'')""")

    crashdump_fields = set(['_crash'])
    crashdump_uuid_fields = set(['_crash_uuid'])
    datetime_fields = set(['crashtime', 'uploadtime', 'reporttime'])
    crashdump_link_fields = set(['linked_crash'])
    crashdump_ticket_fields = set(['linked_tickets'])

    @property
    def must_preserve_newlines(self):
        return True

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
                    for f in self.crashdump_uuid_fields:
                        if field['name'] == f and data['ticket'][f]:
                            field['rendered'] = self._link_crash(req, data['ticket'][f], show_uuid=True)
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
                        for f in self.crashdump_uuid_fields:
                            if f in ticket:
                                ticket[f] = self._link_crash(req, ticket[f], show_uuid=True)
                        for f in self.crashdump_ticket_fields:
                            if f in ticket:
                                ticket[f] = self._link_tickets(req, ticket[f])

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
                                    elif cell.get('header', {}).get('col') in self.crashdump_uuid_fields:
                                        cell['value'] = self._link_crash(req, cell['value'], show_uuid=True)
                                        cell['header']['hidden'] = False
                                        cell['header']['title'] = 'Crashdump'
                                        self.log.debug('got crash cell %s' % str(cell))
                                    elif cell.get('header', {}).get('col') in self.crashdump_ticket_fields:
                                        cell['value'] = self._link_tickets(req, cell['value'])
                                        cell['header']['hidden'] = False
                                        cell['header']['title'] = 'Linked tickets'
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
            if action:
                e = action[1:].split('/')
                req.args['action'] = e[0]
                req.args['params'] = e[1:] if len(e) > 1 else None
            else:
                req.args['action'] = None
                req.args['params'] = None
        self.log.debug('match_request %s' % str(req.args))
        return ret

    # IRequestFilter methods
    def pre_process_request(self, req, handler):
        return handler

    def post_process_request(self, req, template, data, content_type, method=None):
        if req.path_info.startswith('/ticket/'):
            # In case of an invalid ticket, the data is invalid
            if not data:
                return template, data, content_type
            tkt = data['ticket']
            with self.env.db_query as db:
                links = CrashDumpTicketLinks(self.env, tkt, db=db)

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
                            links.crashes = new

        return template, data, content_type, method

    def _prepare_data(self, req, crashobj, absurls=False):
        data = {'object': crashobj,
                'to_utimestamp': to_utimestamp,
                'hex_format':hex_format,
                'exception_code': exception_code,
                'format_bool_yesno': format_bool_yesno,
                'format_source_line': format_source_line,
                'format_function_plus_offset': format_function_plus_offset,
                'str_or_unknown': str_or_unknown,
                'format_cpu_type': format_cpu_type,
                'format_cpu_vendor': format_cpu_vendor,
                'format_cpu_name': format_cpu_name,
                'format_distribution_id': format_distribution_id,
                'format_distribution_codename': format_distribution_codename,
                'format_milliseconds': format_milliseconds,
                'format_seconds': format_seconds,
                'format_size': format_size,
                'format_trust_level': format_trust_level,
                'format_memory_usagetype': format_memory_usagetype,
                'context': web_context(req, crashobj.resource, absurls=absurls),
                'preserve_newlines': self.must_preserve_newlines,
                'emtpy': empty}
        xmlfile = None
        xmlfile_from_db = None
        if crashobj['minidumpreportxmlfile']:
            xmlfile_from_db = crashobj['minidumpreportxmlfile']
            xmlfile = self._get_dump_filename(crashobj, 'minidumpreportxmlfile')
            reporttextfile = self._get_dump_filename(crashobj, 'minidumpreporttextfile')
            reporthtmlfile = self._get_dump_filename(crashobj, 'minidumpreporthtmlfile')
            dumpfile = self._get_dump_filename(crashobj, 'minidumpfile')
        elif crashobj['coredumpreportxmlfile']:
            xmlfile_from_db = crashobj['coredumpreportxmlfile']
            xmlfile = self._get_dump_filename(crashobj, 'coredumpreportxmlfile')
            reporttextfile = self._get_dump_filename(crashobj, 'coredumpreporttextfile')
            reporthtmlfile = self._get_dump_filename(crashobj, 'coredumpreporthtmlfile')
            dumpfile = self._get_dump_filename(crashobj, 'coredumpfile')
        data['xmlfile_from_db'] = xmlfile_from_db
        data['xmlfile'] = xmlfile
        data['xmlfile_error'] = None
        data['minidump_xml_size'] = 0
        data['coredump_xml_size'] = 0
        data['dumpfile_size'] = 0
        data['xmlfile_size'] = 0
        data['reporttextfile_size'] = 0
        data['reporthtmlfile_size'] = 0
        data['show_debug_info'] = False
        data['parsetime'] = 0
        data['is_64_bit'] = False
        if xmlfile:
            start = time.time()
            try:
                data['dumpfile_size'] = os.path.getsize(dumpfile)
            except OSError:
                pass
            try:
                data['xmlfile_size'] = os.path.getsize(xmlfile)
            except OSError:
                pass
            try:
                data['reporttextfile_size'] = os.path.getsize(reporttextfile)
            except OSError:
                pass
            try:
                data['reporthtmlfile_size'] = os.path.getsize(reporthtmlfile)
            except OSError:
                pass
            if os.path.isfile(xmlfile):
                try:
                    xmlreport = XMLReport(xmlfile)
                    for f in xmlreport.fields:
                        data[f] = XMLReport.ProxyObject(xmlreport, f)
                    data['is_64_bit'] = xmlreport.is_64_bit
                except XMLReport.XMLReportIOError as e:
                    data['xmlfile_error'] = str(e)
            else:
                data['xmlfile_error'] = 'XML file %s does not exist' % xmlfile
            end = time.time()
            data['parsetime'] = end - start
        data['bits'] = 64 if data['is_64_bit'] else 32
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
        action = req.args.get('action') or 'view'
        params = req.args.get('params')
        if action == 'view':
            data = self._prepare_data(req, crashobj)
            
            xmlfile = data['xmlfile'] if 'xmlfile' in data else None
            data['dbtime'] = end - start

            linked_tickets = []
            for tkt_id in crashobj.linked_tickets:
                a = self._link_ticket_by_id(req, tkt_id)
                if a:
                    linked_tickets.append(a)

            field_changes = {}
            data.update({'action': action,
                         'params': params,
                        # Store a timestamp for detecting "mid air collisions"
                        'start_time': crashobj['changetime'],
                        'linked_tickets':linked_tickets
                        })

            self._insert_crashdump_data(req, crashobj, data,
                                    get_reporter_id(req, 'author'), field_changes)

            if params is None:
                add_script_data(req, {'comments_prefs': self._get_prefs(req)})
                add_stylesheet(req, 'crashdump/crashdump.css')
                add_script(req, 'common/js/folding.js')
                add_script(req, 'crashdump/crashdump.js')

                return 'report.html', data, None
            else:
                if params[0] in ['sysinfo', 'sysinfo_ex',
                                 'fast_protect_version_info', 'exception', 'memory_regions', 'modules', 'threads']:
                    return params[0] + '.html', data, None
                elif params[0] == 'memory_block':
                    block_base = safe_list_get_as_int(params, 1, 0)
                    data.update({'selected_memory_block_base': block_base })
                    return 'memory_block.html', data, None
                elif params[0] == 'stackdump':
                    threadid = safe_list_get_as_int(params, 1, 0)
                    self.log.debug('got stackdump %s' % threadid )
                    data.update({'selected_stackdump_threadid': threadid })
                    return 'stackdump.html', data, None
                else:
                    raise ResourceNotFound(_("Invalid sub-page request %(param)s for crash %(uuid)s.", param=str(params[0]), uuid=str(crashobj.uuid)))
        elif action == 'sysinfo_report':
            data = self._prepare_data(req, crashobj)
            if params is None:
                add_script_data(req, {'comments_prefs': self._get_prefs(req)})
                add_stylesheet(req, 'crashdump/crashdump.css')
                add_script(req, 'common/js/folding.js')
                add_script(req, 'crashdump/crashdump.js')
                return 'sysinfo_report.html', data, None
            else:
                if params[0] in ['sysinfo', 'sysinfo_ex',
                                    'fast_protect_version_info', 'exception', 'memory_regions', 'modules', 'threads']:
                    return params[0] + '.html', data, None
                else:
                    raise ResourceNotFound(_("Invalid sub-page request %(param)s for crash %(uuid)s.", param=str(params[0]), uuid=str(crashobj.uuid)))

        elif action == 'systeminfo_raw':
            data = self._prepare_data(req, crashobj)

            xmlfile = data['xmlfile'] if 'xmlfile' in data else None
            data['dbtime'] = end - start

            fast_protect_system_info = data['fast_protect_system_info'] if 'fast_protect_system_info' in data else None
            if fast_protect_system_info:
                if crashobj['crashhostname']:
                    filename = "%s_%s.terra4d-system-info" % (str(crashobj.uuid), str(crashobj['crashhostname']))
                else:
                    filename = "%s.terra4d-system-info" % str(crashobj.uuid)
                if fast_protect_system_info.rawdata:
                    return self._send_data(req, fast_protect_system_info.rawdata.raw, filename=filename)
            raise ResourceNotFound(_("No system information available for crash %(uuid)s.", uuid=str(crashobj.uuid)))

        elif action == 'minidump_raw':
            return self._send_file(req, crashobj, 'minidumpfile')
        elif action == 'minidump_text':
            return self._send_file(req, crashobj, 'minidumpreporttextfile')
        elif action == 'minidump_xml':
            return self._send_file(req, crashobj, 'minidumpreportxmlfile')
        elif action == 'minidump_html':
            return self._send_file(req, crashobj, 'minidumpreporthtmlfile')
        elif action == 'coredump_raw':
            return self._send_file(req, crashobj, 'coredumpfile')
        elif action == 'coredump_text':
            return self._send_file(req, crashobj, 'coredumpreporttextfile')
        elif action == 'coredump_xml':
            return self._send_file(req, crashobj, 'coredumpreportxmlfile')
        elif action == 'coredump_html':
            return self._send_file(req, crashobj, 'coredumpreporthtmlfile')
        elif action == 'raw':
            if crashobj['minidumpfile']:
                return self._send_file(req, crashobj, 'minidumpfile')
            elif crashobj['coredumpfile']:
                return self._send_file(req, crashobj, 'coredumpfile')
        elif action == 'xml':
            if crashobj['minidumpreportxmlfile']:
                return self._send_file(req, crashobj, 'minidumpreportxmlfile')
            elif crashobj['coredumpreportxmlfile']:
                return self._send_file(req, crashobj, 'coredumpreportxmlfile')
        elif action == 'html':
            if crashobj['minidumpreporthtmlfile']:
                return self._send_file(req, crashobj, 'minidumpreporthtmlfile')
            elif crashobj['coredumpreporthtmlfile']:
                return self._send_file(req, crashobj, 'coredumpreporthtmlfile')
        elif action == 'text':
            if crashobj['minidumpreporttextfile']:
                return self._send_file(req, crashobj, 'minidumpreporttextfile')
            elif crashobj['coredumpreporttextfile']:
                return self._send_file(req, crashobj, 'coredumpreporttextfile')
        raise ResourceNotFound(_("Invalid action %(action)s for crash %(uuid)s specified.", action=str(action), uuid=str(crashobj.uuid)))

    def _send_data(self, req, data, filename):
        # Force browser to download files instead of rendering
        # them, since they might contain malicious code enabling
        # XSS attacks
        req.send_header('Content-Disposition', 'attachment; filename=%s' % filename)
        req.send_header('Content-Length', '%i' % len(data))
        req.send(content=data, content_type='application/force-download', status=200)

    def _send_file(self, req, crashobj, name):
        filename = self._get_dump_filename(crashobj, name)
        item_name = os.path.basename(filename)
        # Force browser to download files instead of rendering
        # them, since they might contain malicious code enabling
        # XSS attacks
        req.send_header('Content-Disposition', 'attachment; filename=%s' % item_name)
        req.send_file(filename, mimetype='application/force-download')

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

    def _link_tickets(self, req, tickets):
        items = []

        print(tickets)

        for i, word in enumerate(re.split(r'([;,\s]+)', tickets)):
            if i % 2:
                items.append(word)
            elif word:
                ticketid = word
                word = '#%s' % word

                try:
                    ticket = Ticket(self.env, ticketid)
                    if 'TICKET_VIEW' in req.perm(ticket.resource):
                        word = \
                            tag.a(
                                '#%s' % ticket.id,
                                class_=ticket['status'],
                                href=req.href.ticket(int(ticket.id)),
                                title=shorten_line(ticket['summary'])
                            )
                except ResourceNotFound:
                    pass

                items.append(word)

        if items:
            return tag(items)
        else:
            return None

    def _link_crash_by_id(self, req, id):
        ret = None
        try:
            crash = CrashDump(env=self.env, id=id)
            ret = \
                tag.a(
                    'CrashId#%i' % crash.id,
                    class_=crash['status'],
                    href=req.href('crash', crash.uuid),
                    title=crash.uuid
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
                            class_=crash['status'],
                            href=req.href('crash', crash.uuid),
                            title=crash.uuid
                        )
                except ResourceNotFound:
                    pass
                items.append(word)

        if items:
            return tag(items)
        else:
            return None

    def _link_crash(self, req, uuid, show_uuid=False):
        ret = None
        try:
            crash = CrashDump(env=self.env, uuid=uuid)
            if show_uuid:
                ret = \
                    tag.a(
                        str(crash.uuid),
                        class_=crash['status'],
                        href=req.href('crash', crash.uuid),
                        title='CrashId#%i (%s)' % (crash.id, crash.uuid),
                        style="white-space: nowrap"
                    )
            else:
                ret = \
                    tag.a(
                        'CrashId#%i' % crash.id,
                        class_=crash['status'],
                        href=req.href('crash', crash.uuid),
                        title=crash.uuid
                    )
        except ResourceNotFound:
            pass
        return ret

