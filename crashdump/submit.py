#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

from trac.core import *
from trac.util.html import html
from trac.util.datefmt import utc, to_utimestamp
from trac.web import IRequestHandler, IRequestFilter
from trac.web.api import arg_list_to_args, RequestDone, HTTPNotFound, HTTPMethodNotAllowed, HTTPForbidden, HTTPInternalError
from trac.web.chrome import INavigationContributor, ITemplateProvider
from trac.config import Option, BoolOption, ChoiceOption, ListOption
from trac.resource import ResourceNotFound
from trac.ticket.model import Ticket, Component as TicketComponent, Milestone, Version
from pkg_resources import resource_filename
from uuid import UUID
import os
import shutil
import time
import datetime
from xml.sax.saxutils import escape

from .model import CrashDump, CrashDumpStackFrame
from .links import CrashDumpTicketLinks
from .xmlreport import XMLReport

class CrashDumpSubmit(Component):
    """Upload/Submit new crash dumps"""

    implements(IRequestHandler, IRequestFilter, ITemplateProvider)

    dumpdata_dir = Option('crashdump', 'dumpdata_dir', default='dumpdata',
                      doc='Path to the crash dump data directory.')

    default_priority = Option('crashdump', 'default_priority', default='major',
                      doc='Default priority for submitted crash reports.')

    default_milestone = Option('crashdump', 'default_milestone', '< default >',
        """Default milestone for submitted crash reports.""")

    default_version = Option('crashdump', 'default_version', '< default >',
        """Default version for submitted crash reports.""")

    default_component = Option('crashdump', 'default_component', '< default >',
        """Default component for submitted crash reports.""")

    default_severity = Option('crashdump', 'default_severity', '',
        """Default severity for submitted crash reports.""")

    default_summary = Option('crashdump', 'default_summary', '',
        """Default summary (title) for submitted crash reports.""")

    default_description = Option('crashdump', 'default_description', '',
        """Default description for submitted crash reports.""")

    default_keywords = Option('crashdump', 'default_keywords', '',
        """Default keywords for submitted crash reports.""")

    default_reporter = Option('crashdump', 'default_reporter', '< default >',
        """Default reporter for submitted crash reports.""")

    default_owner = Option('crashdump', 'default_owner', '< default >',
        """Default owner for submitted crash reports.""")

    default_ticket_type = Option('crashdump', 'ticket_type', 'defect',
        """Default ticket type for linked tickets.""")

    ignored_modules = Option('crashdump', 'ignore_modules', 'libc, kernel32, ntdll, user32, gdi32',
        """List of modules to ignore for component matching.""")

    # IRequestHandler methods
    def match_request(self, req):
        if req.method == 'POST' and (req.path_info == '/crashdump/submit' or req.path_info == '/submit'):
            self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        elif req.method == 'GET' and (req.path_info == '/crashdump/list' or req.path_info == '/crashlist'):
            self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        else:
            return False

    def _error_response(self, req, status, body=None):
        req.send_error(None, template='', content_type='text/plain', status=status, env=None, data=body)

    def _success_response(self, req, body=None, content_type='text/plain', status=200, headers=None):
        req.send_response(status)
        req.send_header('Cache-Control', 'must-revalidate')
        req.send_header('Expires', 'Fri, 01 Jan 1999 00:00:00 GMT')
        req.send_header('Content-Type', content_type + ';charset=utf-8')
        req.send_header('Content-Length', len(body))
        if headers:
            for k,v in headers.items():
                req.send_header(k, v)
        req.end_headers()

        if req.method != 'HEAD':
            req.write(body)
        raise RequestDone

    def _find_first_component_from_list(self, possible_components):
        ret = None
        for compname in possible_components:
            try:
                component = TicketComponent(self.env, compname)
                ret = component.name
                break
            except ResourceNotFound:
                # No such component exists
                pass
        return ret

    def _find_first_milestone_from_list(self, possible_milestones):
        #print('_find_first_milestone_from_list %s' % str(possible_milestones))
        ret = None
        for ms_name in possible_milestones:
            try:
                milestone = Milestone(self.env, ms_name)
                ret = milestone.name
                break
            except ResourceNotFound:
                # No such component exists
                pass
        return ret

    def _find_first_version_from_list(self, possible_versions):
        #print('_find_first_version_from_list %s' % str(possible_versions))
        ret = None
        for v_name in possible_versions:
            try:
                ver = Version(self.env, v_name)
                ret = ver.name
                break
            except ResourceNotFound:
                # No such component exists
                pass
        return ret

    def _find_component_from_involved_modules(self, module_list, buildpostfix):
        possible_components = []
        for m in module_list:
            module_base = os.path.basename(m)
            module_name, module_ext = os.path.splitext(module_base)
            if buildpostfix and module_name.endswith(buildpostfix):
                module_name = module_name[:-len(buildpostfix)]
            if '-' in module_name:
                (prefix, name) = module_name.split('-', 1)
                name_is_version = True
                for c in name:
                    if (c >= '0' and c <= '9') or c == '.':
                        pass
                    else:
                        name_is_version = False

                if name_is_version:
                    # name is a version number so check the prefix instead of the name
                    # and to not check the full module name since it would check for
                    # a matching version number as well.
                    if prefix not in self.ignored_modules:
                        possible_components.append(prefix)
                else:
                    # add the entire module name
                    if module_name not in self.ignored_modules:
                        possible_components.append(module_name)
                    # ... and the shorten name (without prefix) to the list
                    if name not in self.ignored_modules:
                        possible_components.append(name)
            else:
                if module_name not in self.ignored_modules:
                    possible_components.append(module_name)
        return self._find_first_component_from_list(possible_components)

    def _find_component_for_application(self, applicationname):
        if applicationname is None:
            return None

        possible_components = [applicationname]
        if '-' in applicationname:
            (prefix, name) = applicationname.split('-', 1)
            possible_components.append(name)

        return self._find_first_component_from_list(possible_components)

    def _find_milestone(self, productversion, producttargetversion):
        possible_versions = []
        v_elems = producttargetversion.split('.')
        while len(v_elems) < 4:
            v_elems.append('0')

        for i in range(4, 0, -1):
            possible_versions.append('v' + '.'.join(v_elems[0:i]))
            possible_versions.append('.'.join(v_elems[0:i]))
        return self._find_first_milestone_from_list(possible_versions)

    def _find_version(self, productversion, producttargetversion):
        possible_versions = []
        v_elems = productversion.split('.')
        while len(v_elems) < 4:
            v_elems.append('0')

        for i in range(4, 2, -1):
            possible_versions.append('v' + '.'.join(v_elems[0:i]))
            possible_versions.append('.'.join(v_elems[0:i]))
            if v_elems[i - 1] != '0':
                v_elems[i - 1] = '0'
            possible_versions.append('v' + '.'.join(v_elems[0:i]))
            possible_versions.append('.'.join(v_elems[0:i]))
        return self._find_first_version_from_list(possible_versions)

    def pre_process_request(self, req, handler):
        self.log.debug('CrashDumpSubmit pre_process_request: %s %s', req.method, req.path_info)
        if req.method == "POST":
            # copy the requested form token from into the args to pass the CSRF test
            req.args['__FORM_TOKEN' ] = req.form_token
        return handler

    def post_process_request(self, req, template, data, content_type, method=None):
        True

    def process_request(self, req):
        self.log.debug('CrashDumpSubmit process_request: %s %s', req.method, req.path_info)
        if req.path_info == '/crashdump/submit' or req.path_info == '/submit':
            return self.process_request_submit(req)
        elif req.path_info == '/crashdump/list' or req.path_info == '/crashlist':
            return self.process_request_crashlist(req)
        else:
            return self._error_response(req, status=HTTPMethodNotAllowed.code, body='Invalid request path %s.' % req.path_info)

    def process_request_submit(self, req):
        if req.method != "POST":
            return self._error_response(req, status=HTTPMethodNotAllowed.code, body='Method %s not allowed' % req.method)

        user_agent = req.get_header('User-Agent')
        if user_agent is None:
            return self._error_response(req, status=HTTPForbidden.code, body='No user-agent specified.')
        if '/' in user_agent:
            user_agent, agent_ver = user_agent.split('/', 1)
        if user_agent != 'terra3d-crashuploader':
            return self._error_response(req, status=HTTPForbidden.code, body='User-agent %s not allowed' % user_agent)

        id_str = req.args.get('id')
        if not id_str or not CrashDump.uuid_is_valid(id_str):
            return self._error_response(req, status=HTTPForbidden.code, body='Invalid crash identifier %s specified.' % id_str)

        uuid = UUID(id_str)
        crashid = None
        crashobj = CrashDump.find_by_uuid(self.env, uuid)
        if not crashobj:
            crashobj = CrashDump(uuid=uuid, env=self.env, must_exist=False)
        else:
            crashid = crashobj.id

        force_str = req.args.get('force') or 'false'
        force = True if force_str.lower() == 'true' else False
        # for easy testing
        force = True
        if crashid is not None and not force:
            return self._error_response(req, status=HTTPForbidden.code, body='Crash identifier %s already uploaded.' % id_str)

        ticket_str = req.args.get('ticket') or 'no'

        linked_tickets = set()
        ticketobjs = []
        new_ticket = None
        if ticket_str == 'no':
            pass
        elif '#' in ticket_str:
            ticket_ids = []
            for t in ticket_str.split(','):
                if t[0] == '#':
                    ticket_ids.append(int(t[1:]))
            ticketobjs = []
            for tkt_id in ticket_ids:
                try:
                    ticketobjs.append(Ticket(env=self.env, tkt_id=tkt_id))
                except ResourceNotFound:
                    return self._error_response(req, status=HTTPNotFound.code, body='Ticket %i not found. Cannot link crash %s to the requested ticket.' % (tkt_id, str(uuid)))

        elif ticket_str == 'auto':
            if crashid is None:
                new_ticket = Ticket(env=self.env)
                ticketobjs = [ new_ticket ]
            else:
                for tkt_id in crashobj.linked_tickets:
                    try:
                        ticketobjs.append( Ticket(env=self.env, tkt_id=tkt_id) )
                        break
                    except ResourceNotFound:
                        pass
                if len(ticketobjs) == 0:
                    new_ticket = Ticket(env=self.env)
                    ticketobjs = [ new_ticket ]
        elif ticket_str == 'new':
            new_ticket = Ticket(env=self.env)
            ticketobjs = [ new_ticket ]
        else:
            return self._error_response(req, status=HTTPForbidden.code, body='Unrecognized ticket string %s for crash %s.' % (ticket_str, str(uuid)))
        
        #print('ticket_str=%s' % ticket_str)
        #print('ticketobjs=%s' % str(ticketobjs))

        # we require at least one crash dump file (either minidump or coredump)
        # and any number of report files
        result = False
        ok, crashobj['minidumpfile'] = self._store_dump_file(uuid, req, 'minidump', force)
        if ok:
            result = True
        ok, crashobj['minidumpreporttextfile'] = self._store_dump_file(uuid, req, 'minidumpreport', force)
        ok, crashobj['minidumpreportxmlfile'] = self._store_dump_file(uuid, req, 'minidumpreportxml', force)
        ok, crashobj['minidumpreporthtmlfile'] = self._store_dump_file(uuid, req, 'minidumpreporthtml', force)
        if ok:
            result = True
        ok, crashobj['coredumpfile'] = self._store_dump_file(uuid, req, 'coredump', force)
        if ok:
            result = True
        ok, crashobj['coredumpreporttextfile'] = self._store_dump_file(uuid, req, 'coredumpreport', force)
        ok, crashobj['coredumpreportxmlfile'] = self._store_dump_file(uuid, req, 'coredumpreportxml', force)
        ok, crashobj['coredumpreporthtmlfile'] = self._store_dump_file(uuid, req, 'coredumpreporthtml', force)

        crashobj['applicationfile'] = req.args.get('applicationfile')

        crashtimestamp = datetime.datetime.strptime(req.args.get('crashtimestamp'), "%Y-%m-%dT%H:%M:%S" )
        crashtimestamp = crashtimestamp.replace(tzinfo = utc)
        reporttimestamp = datetime.datetime.strptime(req.args.get('reporttimestamp'), "%Y-%m-%dT%H:%M:%S" )
        reporttimestamp = reporttimestamp.replace(tzinfo = utc)

        crashobj['crashtime'] = crashtimestamp if crashtimestamp else None
        crashobj['reporttime'] = reporttimestamp if reporttimestamp else None
        crashobj['uploadtime'] = datetime.datetime.now(utc)

        self.log.debug('crashtimestamp %s' % (crashobj['crashtime']))
        self.log.debug('reporttimestamp %s' % (crashobj['reporttime']))
        self.log.debug('uploadtime %s' % (crashobj['uploadtime']))

        crashobj['productname'] = req.args.get('productname')
        crashobj['productcodename'] = req.args.get('productcodename')
        crashobj['productversion'] = req.args.get('productversion')
        crashobj['producttargetversion'] = req.args.get('producttargetversion')
        crashobj['uploadhostname'] = req.args.get('fqdn')
        crashobj['uploadusername'] = req.args.get('username')
        crashobj['crashhostname'] = req.args.get('crashfqdn')
        crashobj['crashusername'] = req.args.get('crashusername')
        crashobj['buildtype'] = req.args.get('buildtype')
        crashobj['buildpostfix'] = req.args.get('buildpostfix')
        crashobj['machinetype'] = req.args.get('machinetype')
        crashobj['systemname'] = req.args.get('systemname')
        crashobj['osversion'] = req.args.get('osversion')
        crashobj['osrelease'] = req.args.get('osrelease')
        crashobj['osmachine'] = req.args.get('osmachine')

        # get the application name from the application file
        if crashobj['applicationfile']:
            appbase = os.path.basename(crashobj['applicationfile'])
            (appbase, ext) = os.path.splitext(appbase)
            if crashobj['buildpostfix'] and appbase.endswith(crashobj['buildpostfix']):
                appbase = appbase[:-len(crashobj['buildpostfix'])]
            crashobj['applicationname'] = appbase

        if result:

            if crashobj['minidumpreportxmlfile']:
                xmlfile = self._get_dump_filename(crashobj, 'minidumpreportxmlfile')
                xmlreport = XMLReport(xmlfile)
            elif crashobj['coredumpreportxmlfile']:
                xmlfile = self._get_dump_filename(crashobj, 'coredumpreportxmlfile')
                xmlreport = XMLReport(xmlfile)
            else:
                xmlreport = None

            new_crash = True if crashid is None else False
            if new_crash:
                crashobj['status'] = 'new'
                crashobj['type'] = 'crash'
                crashobj['priority'] = self.default_priority
                if self.default_milestone == '< default >':
                    crashobj['milestone'] = self._find_milestone(crashobj['productversion'], crashobj['producttargetversion'])
                else:
                    crashobj['milestone'] = self.default_milestone
                if self.default_version == '< default >':
                    crashobj['version'] = self._find_version(crashobj['productversion'], crashobj['producttargetversion'])
                else:
                    crashobj['version'] = self.default_version
                if self.default_component == '< default >':
                    if xmlreport is not None and xmlreport.exception is not None:
                        crashobj['component'] = self._find_component_from_involved_modules(xmlreport.exception.involved_modules, crashobj['buildpostfix'])
                    if not crashobj['component']:
                        crashobj['component'] = self._find_component_for_application(crashobj['applicationname'])
                else:
                    crashobj['component'] = self.default_component
                crashobj['severity'] = self.default_severity
                crashobj['summary'] = self.default_summary
                crashobj['description'] = self.default_description
                crashobj['keywords'] = self.default_keywords
                if self.default_owner == '< default >':
                    default_to_owner = ''
                    if crashobj['component']:
                        try:
                            component = TicketComponent(self.env, crashobj['component'])
                            default_to_owner = component.owner # even if it's empty
                        except ResourceNotFound:
                            # No such component exists
                            pass
                    # If the current owner is "< default >", we need to set it to
                    # _something_ else, even if that something else is blank.
                    crashobj['owner'] = default_to_owner if default_to_owner else crashobj['crashusername']
                else:
                    crashobj['owner'] = self.default_owner
                if self.default_reporter == '< default >':
                    crashobj['reporter'] = crashobj['crashusername']
                else:
                    crashobj['reporter'] = self.default_reporter

                crashid = crashobj.insert()
                result = True if crashid else False
                if result:
                    ex_thread = xmlreport.exception.thread
                    if ex_thread is not None:
                        threadid = ex_thread.id
                        stackdump = ex_thread.simplified_stackdump if ex_thread.simplified_stackdump is not None else ex_thread.stackdump
                        if stackdump:
                            for frameno, frm in enumerate(stackdump.callstack):
                                frameobj = CrashDumpStackFrame(crashid, threadid,frameno, env=self.env)
                                frameobj['module'] = frm.module
                                frameobj['function'] = frm.function
                                frameobj['funcoff'] = frm.funcoff
                                frameobj['source'] = frm.source
                                frameobj['line'] = frm.line
                                frameobj['lineoff'] = frm.lineoff
                                frameobj.insert()


            else:
                #print('update crash %s' % crashobj)
                result = crashobj.save_changes(author=crashobj['crashusername'])

            if result:
                values = crashobj.values
                values['crashtimestamp'] = crashtimestamp
                values['reporttimestamp'] = reporttimestamp
                values['crashid'] = crashid
                values['app'] = crashobj['applicationname'] if crashobj['applicationname'] else crashobj['applicationfile']
                # Update all already linked tickets
                for tkt_id in crashobj.linked_tickets:
                    try:
                        new_linked_ticketobj = Ticket(env=self.env, tkt_id=tkt_id)
                        comment = """The crash [[/crash/%(uuid)s|CrashId#%(crashid)s - %(uuid)s]] has been updated by **%(uploadusername)s**
from **%(uploadhostname)s** is already linked to this ticket.
""" % values

                        new_linked_ticketobj.save_changes(author=crashobj['reporter'], comment=comment)
                        # Only add valid tickets to the linked_tickets set
                        linked_tickets.add(tkt_id)
                    except ResourceNotFound:
                        pass
                    
                if new_ticket is not None:
                    new_ticket['type'] = self.default_ticket_type
                    new_ticket['summary'] = "Crash %(uuid)s in %(app)s" % values
                    new_ticket['description'] = comment
                    # copy over some fields from the crash itself
                    for field in ['status', 'owner', 'reporter', 'priority', 'milestone', 'component',
                                'severity', 'keywords']:
                        new_ticket[field] = crashobj[field]
                    new_ticket['linked_crash'] = str(crashid)
                    new_ticket.insert()

                # Now add the newly linked tickets as well
                for tkt_obj in ticketobjs:
                    if tkt_obj.id not in crashobj.linked_tickets:
                        comment = """The crash [[/crash/%(uuid)s|CrashId#%(crashid)s - %(uuid)s]] has been uploaded by **%(uploadusername)s**
from **%(uploadhostname)s** and linked to this ticket.

The crash occured at //%(crashtimestamp)s UTC// on **%(crashhostname)s** with user **%(crashusername)s** while running %(applicationfile)s. The
application was running as part of %(productname)s (%(productcodename)s) version %(productversion)s (%(producttargetversion)s, %(buildtype)s) on a
%(systemname)s/%(machinetype)s with %(osversion)s (%(osrelease)s/%(osmachine)s).
""" % values
                        linked_crashes = tkt_obj['linked_crash'] if tkt_obj['linked_crash'] else ''
                        linked_crashes = set([int(x.strip()) for x in linked_crashes.split(',') if x.strip()])
                        #print('crashid=%s' % crashid)
                        #print('linked_crashes=%s' % linked_crashes)
                        linked_crashes.add(crashid)
                        #print('linked_crashes=%s' % linked_crashes)
                        tkt_obj['linked_crash'] = ', '.join(str(x) for x in sorted(linked_crashes))
                        tkt_obj.save_changes(author=crashobj['reporter'], comment=comment)
                    
                        linked_tickets.add(tkt_obj.id)
                        links = CrashDumpTicketLinks(self.env, tkt=tkt_obj)
                        links.crashes.add(crashid)
                        links.save(author=crashobj['reporter'])

            if result:
                headers = {}
                linked_ticket_header = []
                for tkt_id in linked_tickets:
                    linked_ticket_header.append('#%i:%s' % (tkt_id, req.abs_href.ticket(tkt_id)))
                if linked_ticket_header:
                    headers['Linked-Tickets'] = ';'.join(linked_ticket_header)
                headers['Crash-URL'] = req.abs_href('crash', str(uuid))
                headers['CrashId'] = str(crashid)

                return self._success_response(req, body='Crash dump %s uploaded successfully.' % uuid, headers=headers)
            elif new_crash:
                return self._error_response(req, status=HTTPInternalError.code, body='Failed to add crash dump %s to database' % uuid)
            else:
                return self._error_response(req, status=HTTPInternalError.code, body='Failed to update crash dump %s to database' % uuid)
        else:
            return self._error_response(req, status=HTTPInternalError.code, body='Failed to process crash dump %s' % uuid)

    def process_request_crashlist(self, req):
        if req.method != "GET":
            return self._error_response(req, status=HTTPMethodNotAllowed.code, body='Method %s not allowed' % req.method)

        user_agent = req.get_header('User-Agent')
        if user_agent is None:
            return self._error_response(req, status=HTTPForbidden.code, body='No user-agent specified.')
        if '/' in user_agent:
            user_agent, agent_ver = user_agent.split('/', 1)
        #if user_agent != 'terra3d-crashuploader':
            #return self._error_response(req, status=HTTPForbidden.code, body='User-agent %s not allowed' % user_agent)

        req_status = req.args.get('status') or 'active'
        
        headers = {}
        body = ''
        body = body + '<?xml version="1.0" encoding="utf-8"?>\r\n<crashlist>\r\n'
        for crashobj in CrashDump.query(env=self.env, status=req_status):
            
            body = body + '<crash id=\"%i\" uuid=\"%s\">\r\n' % (crashobj.id, crashobj['uuid'])
            for field in crashobj.fields:
                field_name = field['name']
                if field_name == 'uuid':
                    continue
                field_type = field['type']
                field_value = crashobj[field_name]
                if field_type == 'time':
                    field_value = str(to_utimestamp(field_value))

                body = body + '<%s type=\"%s\">' % (field_name, field_type)
                if field_value is not None:
                    #print('%s=%s' % (field_name, field_value))
                    body = body + escape(field_value)
                body = body + '</%s>\r\n' % (field_name)
            body = body + '<linked_tickets>\r\n'
            for tkt in crashobj.linked_tickets:
                body = body + '<ticket id=\"%i\"/>\r\n' % tkt
            body = body + '</linked_tickets>\r\n'
            body = body + '</crash>\r\n'
        body = body + '</crashlist>\r\n'
        return self._success_response(req, body=body.encode('utf-8'), headers=headers)

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

    @property
    def path(self):
        return self._get_path(self.env.path, self.parent_realm, self.parent_id,
                              self.filename)

    def _create_crash_file(self, filename, force):
        flags = os.O_CREAT + os.O_WRONLY
        if force:
            flags += os.O_TRUNC
        else:
            if os.path.isfile(filename):
                return None
            flags += os.O_EXCL
        if hasattr(os, 'O_BINARY'):
            flags += os.O_BINARY
        return os.fdopen(os.open(filename, flags, 0660), 'w')

    def _store_dump_file(self, uuid, req, name, force):
        item_name = None
        ret = False
        file = req.args.get(name) if name in req.args else None
        if file is not None:
            filename = file.filename
            fileobj = file.file
            item_name = os.path.join(str(uuid), filename)
            crash_dir = os.path.join(self.env.path, self.dumpdata_dir, str(uuid))
            crash_file = os.path.join(crash_dir, filename)
            self.log.debug('_store_dump_file item_name %s' % (item_name))
            self.log.debug('_store_dump_file crash_dir %s' % (crash_dir))
            self.log.debug('_store_dump_file crash_file %s' % (crash_file))
            if not os.path.isdir(crash_dir):
                os.makedirs(crash_dir)
            targetfileobj = self._create_crash_file(crash_file, force)
            if targetfileobj is None:
                ret = False
            else:
                shutil.copyfileobj(fileobj, targetfileobj)
                ret = True
        return (ret, item_name)

    def _get_dump_filename(self, crashobj, name):
        item_name = crashobj[name]
        crash_file = os.path.join(self.env.path, self.dumpdata_dir, item_name)
        return crash_file
