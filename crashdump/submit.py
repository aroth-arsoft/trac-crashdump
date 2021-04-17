#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

from trac.core import *
from trac.util.html import html
from trac.util.datefmt import utc, to_utimestamp, parse_date
from trac.web import IRequestHandler, IRequestFilter
from trac.web.api import arg_list_to_args, RequestDone, HTTPNotFound, HTTPMethodNotAllowed, HTTPForbidden

try:
    from trac.web.api import HTTPInternalError as HTTPInternalServerError
except ImportError:  # Trac 1.3.1+
    from trac.web.api import HTTPInternalServerError

from trac.web.chrome import ITemplateProvider, INavigationContributor,add_script, add_stylesheet

from trac.config import Option, IntOption, BoolOption, PathOption
from trac.resource import ResourceNotFound
from trac.ticket.model import Ticket, Component as TicketComponent, Milestone, Version
from trac.util import get_pkginfo
from trac.util.html import html as tag

from pkg_resources import resource_filename, get_distribution
from uuid import UUID
import os
import shutil
import re
import time
import datetime
import cgi
from xml.sax.saxutils import escape

from .model import CrashDump, CrashDumpStackFrame
from .links import CrashDumpTicketLinks
from .xmlreport import XMLReport
from .utils import *

class CrashDumpSubmit(Component):
    """Upload/Submit new crash dumps"""

    implements(IRequestHandler, IRequestFilter, INavigationContributor, ITemplateProvider)

    dumpdata_dir = PathOption('crashdump', 'dumpdata_dir', default='../dumpdata',
                      doc='Path to the crash dump data directory relative to the environment conf directory.')

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

    replace_usernames = Option('crashdump', 'replace_usernames', '',
        """List of username replacements applied when a new crash is uploaded (format username=myrealname; multiple values separated by comma).""")

    max_upload_size = IntOption('crashdump', 'max_upload_size', default=16 * 1024 * 1024,
                      doc="""Maximum allowed upload size. If set to zero the upload limit is disabled and all uploads will be accepted.""")

    upload_disabled = BoolOption('crashdump', 'upload_disabled', 'false',
                      doc="""Disable upload. No further crashdumps can be submitted.""")

    disable_manual_upload = BoolOption('crashdump', 'manual_upload_disabled', 'false',
                      doc="""Disable manual upload function. Crashes can only be uploaded automatically via the crash handler.""")

    # INavigationContributor methods
    def get_active_navigation_item(self, req):
        self.log.debug('get_active_navigation_item %s' % req.path_info)
        if not self.disable_manual_upload:
            val = re.search('/crash_upload$', req.path_info)
            if val and val.start() == 0:
                return 'upload_crash'

    def get_navigation_items(self, req):
        if not self.disable_manual_upload:
            yield ('mainnav', 'upload_crash',
                   tag.a('Upload Crash', href=req.href('crash_upload')))

    # IRequestHandler methods
    def match_request(self, req):
        if req.method == 'POST' and (req.path_info == '/crashdump/submit' or req.path_info == '/submit'):
            self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        elif req.method == 'GET' and (req.path_info == '/crashdump/submit/crashlist' or req.path_info == '/submit/crashlist'):
            self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        elif req.method == 'GET' and (req.path_info == '/crashdump/submit/capabilities' or req.path_info == '/submit/capabilities'):
            self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        elif req.method == 'GET' and (req.path_info == '/crashdump/list' or req.path_info == '/crashlist'):
            self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        elif req.method == 'GET' and (req.path_info == '/crashdump/capabilities' or req.path_info == '/capabilities'):
            self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        elif (req.method == 'GET' or req.method == 'POST') and (req.path_info == '/crashdump/crash_upload' or req.path_info == '/crash_upload'):
            return True
        else:
            self.log.debug('match_request: %s %s', req.method, req.path_info)
            return False

    def _error_response(self, req, status, body=None, content_type='text/plain', headers=None):

        self.log.debug('_error_response: %s %s -> %i: %s', req.method, req.path_info, status, body)
        if isinstance(body, unicode):
            body = body.encode('utf-8')

        req.send_response(status)
        req._outheaders = []
        req.send_header('Cache-Control', 'must-revalidate')
        req.send_header('Expires', 'Fri, 01 Jan 1999 00:00:00 GMT')
        req.send_header('Content-Type', content_type + ';charset=utf-8')
        req.send_header('Content-Length', len(body))
        if headers:
            for k,v in headers.items():
                req.send_header(k, v)
        req._send_cookie_headers()

        if req.method != 'HEAD':
            req.write(body)
        raise RequestDone

    def _success_response(self, req, body=None, content_type='text/plain', status=200, headers=None):

        if isinstance(body, unicode):
            body = body.encode('utf-8')

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

    def _manual_upload_result(self, req, error=None):
        data = {}
        action = 'upload'
        params = None
        submit_href = req.href + '/submit'
        data.update({'action': action,
                    'params': params,
                    'submit_href': submit_href,
                    'upload_error': error,
                    })
        if crashdump_use_jinja2:
            metadata = {'content_type': 'text/html'}
        else:
            add_script(req, 'common/js/folding.js')
            metadata = None
        add_script(req, 'crashdump/crashdump.js')
        add_stylesheet(req, 'crashdump/crashdump.css')
        return 'upload.html', data, metadata

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
            module_base = os.path.basename(m) if '/' in m else m
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
        if producttargetversion is None:
            return None
        possible_versions = []
        v_elems = producttargetversion.split('.')
        while len(v_elems) < 4:
            v_elems.append('0')

        for i in range(4, 0, -1):
            possible_versions.append('v' + '.'.join(v_elems[0:i]))
            possible_versions.append('.'.join(v_elems[0:i]))
        return self._find_first_milestone_from_list(possible_versions)

    def _find_version(self, productversion, producttargetversion):
        if productversion is None:
            return None
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

    def _apply_username_replacements(self, username):
        if username is None:
            return None
        self.log.debug('CrashDumpSubmit _apply_username_replacements in=\'%s\'' % username)
        ret = username
        ret_lower = username.lower()
        for pattern in self.replace_usernames.split(','):
            pattern = pattern.strip()
            self.log.debug('CrashDumpSubmit _apply_username_replacements pattern=\'%s\'' % pattern)
            if '=' in pattern:
                (find, replace) = pattern.split('=', 1)
                find = find.strip().lower()
                replace = replace.strip()
                self.log.debug('CrashDumpSubmit _apply_username_replacements find=\'%s\' -> replace=\'%s\'' % (find, replace))
                if ret_lower == find:
                    ret = replace
                    ret_lower = replace.lower()
        self.log.debug('CrashDumpSubmit _apply_username_replacements out=\'%s\'' % ret)
        return ret

    def pre_process_request(self, req, handler):
        if req.path_info != '/crashdump/submit' and req.path_info != '/submit' and \
            req.path_info != '/crashdump/crash_upload' and req.path_info != '/crash_upload':
            return handler

        self.log.debug('CrashDumpSubmit pre_process_request: %s %s %s', req.method, req.path_info, handler)
        if req.method == "POST":
            user_agent = req.get_header('User-Agent')
            if user_agent is not None and '/' in user_agent:
                user_agent, agent_ver = user_agent.split('/', 1)
            if user_agent == 'terra3d-crashuploader':
                # copy the requested form token from into the args to pass the CSRF test
                req.args['__FORM_TOKEN' ] = req.form_token

            manual_upload = req.args.as_int('manual_upload', 0)
            # for testing
            if manual_upload:
                # copy the requested form token from into the args to pass the CSRF test
                req.args['__FORM_TOKEN' ] = req.form_token

        return handler

    def post_process_request(self, req, template, data, content_type, method=None):
        return template, data, content_type, method

    def process_request(self, req):
        self.log.debug('CrashDumpSubmit process_request: %s %s', req.method, req.path_info)
        if req.path_info == '/crashdump/submit' or req.path_info == '/submit':
            self.log.debug('CrashDumpSubmit process_request_submit: %s %s', req.method, req.path_info)
            return self.process_request_submit(req)
        elif req.path_info == '/crashdump/crash_upload' or req.path_info == '/crash_upload':
            return self.process_request_crash_upload(req)
        elif req.path_info == '/crashdump/list' or req.path_info == '/crashlist' or req.path_info == '/crashdump/submit/crashlist' or req.path_info == '/submit/crashlist':
            return self.process_request_crashlist(req)
        elif req.path_info == '/crashdump/capabilities' or req.path_info == '/capabilities' or req.path_info == '/crashdump/submit/capabilities' or req.path_info == '/submit/capabilities':
            return self.process_request_capabilities(req)
        else:
            return self._error_response(req, status=HTTPMethodNotAllowed.code, body='Invalid request path %s.' % req.path_info)

    def process_request_capabilities(self, req):
        if req.method != "GET":
            return self._error_response(req, status=HTTPMethodNotAllowed.code, body='Method %s not allowed' % req.method)
        user_agent = req.get_header('User-Agent')
        if user_agent is None:
            return self._error_response(req, status=HTTPForbidden.code, body='No user-agent specified.')

        headers = {}
        headers['Max-Upload-Size'] = self.max_upload_size
        headers['Upload-Disabled'] = '1' if self.upload_disabled else '0'

        # This is a plain Python source file, not an egg
        dist = get_distribution('TracCrashDump')
        if dist:
            headers['Crashdump-Plugin-Version'] = dist.version
            headers['Upload-Disabled'] = '1' if self.upload_disabled else '0'
        if self.upload_disabled:
            body = 'Disabled'
        else:
            body = 'OK'
        return self._success_response(req, body=body.encode('utf-8'), headers=headers)

    def process_request_crash_upload(self, req):
        return self._manual_upload_result(req, error=None)

    def escape_ticket_values(self, values):
        ret = {}
        for k,v in values.items():
            if isinstance(v, str) or isinstance(v, basestring):
                ret[k] = v.replace('#', '!#')
            else:
                ret[k] = v
        return ret

    def process_request_submit(self, req):
        if req.method != "POST":
            return self._error_response(req, status=HTTPMethodNotAllowed.code, body='Method %s not allowed' % req.method)

        manual_upload = req.args.as_int('manual_upload', 0)
        if manual_upload == 0:
            user_agent_full = req.get_header('User-Agent')
            if user_agent_full is None:
                return self._error_response(req, status=HTTPForbidden.code, body='No user-agent specified.')
            if '/' in user_agent_full:
                user_agent, agent_ver = user_agent_full.split('/', 1)
            else:
                user_agent = user_agent_full
            if user_agent != 'terra3d-crashuploader':
                return self._error_response(req, status=HTTPForbidden.code, body='User-agent %s not allowed' % user_agent_full)

        headers = {}
        headers['Max-Upload-Size'] = self.max_upload_size
        headers['Upload-Disabled'] = '1' if self.upload_disabled else '0'

        if self.upload_disabled:
            return self._error_response(req, status=HTTPInternalServerError.code, body='Crashdump upload has been disabled by the administrator.', headers=headers)

        id_str = req.args.get('id')
        if not manual_upload:
            if not id_str or not CrashDump.uuid_is_valid(id_str):
                return self._error_response(req, status=HTTPInternalServerError.code, body='Invalid crash identifier %s specified.' % id_str)

        total_upload_size = self._get_total_upload_size(req)
        if self.max_upload_size > 0 and total_upload_size > self.max_upload_size:
            self.log.debug('total_upload_size %i > max_upload_size %i' % (total_upload_size, self.max_upload_size) )
            return self._error_response(req, status=HTTPInternalServerError.code, body='Upload size %i bytes exceed the upload limit of %i bytes' % (total_upload_size, self.max_upload_size), headers=headers)
        else:
            self.log.debug('total_upload_size %i <= max_upload_size %i' % (total_upload_size, self.max_upload_size) )

        if manual_upload:
            self.log.debug('manual_upload')

            files = req.args.getlist('files')
            if len(files) == 0:
                return self._error_response(req, status=HTTPInternalServerError.code, body='No files uploaded.')

            import re

            id_str = None
            minidump = None
            minidumpreportxml = None

            for file in files:
                if isinstance(file, cgi.FieldStorage):
                    filename = os.path.basename(file.filename)
                    self.log.debug('got file %s' % filename)
                    match = re.match(r'^([0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12})\.([0-9a-zA-Z\.]+)$', filename)
                    if match:
                        new_id_str = match.groups()[0]
                        ext = match.groups()[1]
                        self.log.debug('got file match %s' % new_id_str)
                        if id_str is None:
                            id_str = new_id_str
                        elif id_str == new_id_str:
                            pass
                        else:
                            return self._error_response(req, status=HTTPInternalServerError.code, body='At the moment uploading multiples crashes is not supported.')
                        if ext == 'dmp':
                            minidump = file
                        elif ext == 'dmp.xml':
                            minidumpreportxml = file
                        self.log.debug('got id %s, ext %s' % (id_str, ext))
                else:
                    self.log.debug('skip file field %s-%s' % (type(file), file) )
            if not id_str:
                return self._manual_upload_result(req, error='Cannot determine crash identifier from file upload. The files uploaded must have a UUID in its name and the extentsion must either be .dmp or .dmp.xml.')
            elif minidump is None and minidumpreportxml is None:
                return self._manual_upload_result(req, error='Uploaded files do not contain a valid crash dump information.')

            self.log.debug('got crashid %s' % id_str)
            if minidump is not None:
                req.args['minidump'] = minidump
            if minidumpreportxml is not None:
                req.args['minidumpreportxml'] = minidumpreportxml

        uuid = UUID(id_str)
        crashid = None
        crashobj = CrashDump.find_by_uuid(self.env, uuid)
        if not crashobj:
            crashobj = CrashDump(uuid=uuid, env=self.env, must_exist=False)
        else:
            crashid = crashobj.id

        force_str = req.args.get('force') or 'false'
        force = True if force_str.lower() == 'true' else False
        if crashid is not None and not force and not manual_upload:
            headers = {}
            headers['Crash-URL'] = req.abs_href('crash', str(uuid))
            headers['CrashId'] = str(crashid)
            self.log.debug('crash %s already uploaded %s' % (uuid, headers['Crash-URL']) )
            return self._error_response(req, status=HTTPInternalServerError.code, body='Crash identifier %s already uploaded.' % id_str, headers=headers)

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
            return self._error_response(req, status=HTTPInternalServerError.code, body='Unrecognized ticket string %s for crash %s.' % (ticket_str, str(uuid)))
        
        #print('ticket_str=%s' % ticket_str)
        #print('ticketobjs=%s' % str(ticketobjs))

        # we require at least one crash dump file (either minidump or coredump)
        # and any number of report files
        failure_message = None
        result = False
        ok, new_minidumpfile, errmsg = self._store_dump_file(uuid, req, 'minidump', force)
        if ok:
            result = True
        elif failure_message is None:
            failure_message = errmsg
        ok, new_minidumpreporttextfile, errmsg = self._store_dump_file(uuid, req, 'minidumpreport', force)
        ok, new_minidumpreportxmlfile, errmsg = self._store_dump_file(uuid, req, 'minidumpreportxml', force)
        # accept XML crash upload only for manual uploads
        if manual_upload and ok:
            result = True
        elif failure_message is None:
            failure_message = errmsg
        ok, new_minidumpreporthtmlfile, errmsg = self._store_dump_file(uuid, req, 'minidumpreporthtml', force)
        ok, new_coredumpfile, errmsg = self._store_dump_file(uuid, req, 'coredump', force)
        if ok:
            result = True
        elif failure_message is None:
            failure_message = errmsg
        ok, new_coredumpreporttextfile, errmsg = self._store_dump_file(uuid, req, 'coredumpreport', force)
        ok, new_coredumpreportxmlfile, errmsg = self._store_dump_file(uuid, req, 'coredumpreportxml', force)
        ok, new_coredumpreporthtmlfile, errmsg = self._store_dump_file(uuid, req, 'coredumpreporthtml', force)

        self.log.debug('new_minidumpfile \'%s\'' % new_minidumpfile)
        self.log.debug('new_minidumpreportxmlfile \'%s\'' % new_minidumpreportxmlfile)
        self.log.debug('before crashobj[minidumpfile] \'%s\'' % crashobj['minidumpfile'])
        self.log.debug('before crashobj[minidumpreportxmlfile] \'%s\'' % crashobj['minidumpreportxmlfile'])

        if manual_upload:
            if not crashobj['minidumpfile'] or force:
                crashobj['minidumpfile'] = new_minidumpfile
            if not crashobj['minidumpreporttextfile'] or force:
                crashobj['minidumpreporttextfile'] = new_minidumpreporttextfile
            if not crashobj['minidumpreportxmlfile'] or force:
                crashobj['minidumpreportxmlfile'] = new_minidumpreportxmlfile
            if not crashobj['minidumpreporthtmlfile'] or force:
                crashobj['minidumpreporthtmlfile'] = new_minidumpreporthtmlfile
            if not crashobj['coredumpfile'] or force:
                crashobj['coredumpfile'] = new_coredumpfile
            if not crashobj['coredumpreporttextfile'] or force:
                crashobj['coredumpreporttextfile'] = new_coredumpreporttextfile
            if not crashobj['coredumpreportxmlfile'] or force:
                crashobj['coredumpreportxmlfile'] = new_coredumpreportxmlfile
            if not crashobj['coredumpreporthtmlfile'] or force:
                crashobj['coredumpreporthtmlfile'] = new_coredumpreporthtmlfile
        else:
            crashobj['minidumpfile'] = new_minidumpfile
            crashobj['minidumpreporttextfile'] = new_minidumpreporttextfile
            crashobj['minidumpreportxmlfile'] = new_minidumpreportxmlfile
            crashobj['minidumpreporthtmlfile'] = new_minidumpreporthtmlfile
            crashobj['coredumpfile'] = new_coredumpfile
            crashobj['coredumpreporttextfile'] = new_coredumpreporttextfile
            crashobj['coredumpreportxmlfile'] = new_coredumpreportxmlfile
            crashobj['coredumpreporthtmlfile'] = new_coredumpreporthtmlfile

        self.log.debug('after crashobj[minidumpfile] \'%s\'' % crashobj['minidumpfile'])
        self.log.debug('after crashobj[minidumpreportxmlfile] \'%s\'' % crashobj['minidumpreportxmlfile'])

        new_applicationfile = req.args.get('applicationfile')
        if not crashobj['applicationfile']:
            crashobj['applicationfile'] = new_applicationfile

        self.log.debug('crashtimestamp from http form \'%s\'' % req.args.get('crashtimestamp'))
        self.log.debug('reporttimestamp from http form \'%s\'' % req.args.get('reporttimestamp'))

        try:
            crashtimestamp = parse_date(req.args.get('crashtimestamp', ''), hint='iso8601' )
        except TracError:
            crashtimestamp = None
            self.log.warn('invalid crash timestamp \'%s\'' % (req.args.get('crashtimestamp')))
        try:
            reporttimestamp = parse_date(req.args.get('reporttimestamp', ''), hint='iso8601' )
        except TracError:
            reporttimestamp = None
            self.log.warn('invalid crash report timestamp \'%s\'' % (req.args.get('reporttimestamp')))

        crashobj['crashtime'] = crashtimestamp if crashtimestamp else None
        crashobj['reporttime'] = reporttimestamp if reporttimestamp else None
        crashobj['uploadtime'] = datetime.datetime.now(utc)

        self.log.debug('crashtimestamp %s' % (crashobj['crashtime']))
        self.log.debug('reporttimestamp %s' % (crashobj['reporttime']))
        self.log.debug('uploadtime %s' % (crashobj['uploadtime']))

        if not manual_upload:
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

        if result:

            xmlreport = None
            try:
                if crashobj['minidumpreportxmlfile']:
                    xmlfile = self._get_dump_filename(crashobj, 'minidumpreportxmlfile')
                    xmlreport = XMLReport(xmlfile)
                elif crashobj['coredumpreportxmlfile']:
                    xmlfile = self._get_dump_filename(crashobj, 'coredumpreportxmlfile')
                    xmlreport = XMLReport(xmlfile)
            except XMLReport.XMLReportException as e:
                return self._error_response(req, status=HTTPInternalServerError.code, body='Failed to process crash dump %s: %s' % (uuid, str(e)))

            if xmlreport and manual_upload:

                if xmlreport.crash_info:
                    crashobj['crashtime'] = xmlreport.crash_info.crash_timestamp
                    crashobj['reporttime'] = xmlreport.crash_info.report_time
                    crashobj['uploadhostname'] = req.remote_addr
                    crashobj['uploadusername'] = req.remote_user
                    crashobj['applicationfile'] = xmlreport.crash_info.application
                if xmlreport.fast_protect_version_info:
                    crashobj['productname'] = xmlreport.fast_protect_version_info.product_name
                    crashobj['productcodename'] = xmlreport.fast_protect_version_info.product_code_name
                    crashobj['productversion'] = xmlreport.fast_protect_version_info.product_version
                    crashobj['producttargetversion'] = xmlreport.fast_protect_version_info.product_target_version
                    crashobj['buildtype'] = xmlreport.fast_protect_version_info.product_build_type
                    crashobj['buildpostfix'] = xmlreport.fast_protect_version_info.product_build_postfix

                if xmlreport.fast_protect_system_info:
                    crashobj['crashhostname'] = xmlreport.fast_protect_system_info.fqdn
                    crashobj['crashusername'] = xmlreport.fast_protect_system_info.username
                    crashobj['machinetype'] = xmlreport.fast_protect_system_info.machine_type

                if xmlreport.system_info:
                    crashobj['systemname'] = xmlreport.system_info.platform_type
                    crashobj['osversion'] = xmlreport.system_info.os_version
                    crashobj['osrelease'] = xmlreport.system_info.os_build_number
                    crashobj['osmachine'] = xmlreport.system_info.cpu_type

            # get the application name from the application file
            if crashobj['applicationfile']:
                appfile = crashobj['applicationfile']
                if '/' in appfile:
                    appbase = appfile.split('/')[-1]
                elif '\\' in appfile:
                    appbase = appfile.split('\\')[-1]
                else:
                    appbase = os.path.basename(appfile)
                (appbase, ext) = os.path.splitext(appbase)
                if crashobj['buildpostfix'] and appbase.endswith(crashobj['buildpostfix']):
                    appbase = appbase[:-len(crashobj['buildpostfix'])]
                crashobj['applicationname'] = appbase

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
                    if xmlreport is not None and xmlreport.exception is not None and xmlreport.exception.involved_modules:
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
                    if default_to_owner:
                        crashobj['owner'] = default_to_owner
                    else:
                        # If the current owner is "< default >", we need to set it to
                        # _something_ else, even if that something else is blank.
                        crashobj['owner'] = crashobj['crashusername']
                else:
                    crashobj['owner'] = self.default_owner
                if self.default_reporter == '< default >':
                    crashobj['reporter'] = crashobj['crashusername']
                else:
                    crashobj['reporter'] = self.default_reporter

                # apply replacements on usernames in owner and reporter field
                crashobj['owner'] = self._apply_username_replacements(crashobj['owner'])
                crashobj['reporter'] = self._apply_username_replacements(crashobj['reporter'])

                crashid = crashobj.insert()
                result = True if crashid else False
                if result:
                    if xmlreport is not None and xmlreport.exception is not None:
                        ex_thread = xmlreport.exception.thread
                    else:
                        ex_thread = None
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
                values['uuid'] = crashobj.uuid
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
                    comment = """The crash [[/crash/%(uuid)s|CrashId#%(crashid)s - %(uuid)s]] has been uploaded by **%(uploadusername)s**
from **%(uploadhostname)s** and this ticket has been automatically created to track the progress in finding and resolving the cause of the crash.
""" % values
                    new_ticket['description'] = comment
                    # copy over some fields from the crash itself
                    for field in ['status', 'priority', 'milestone', 'component',
                                'severity', 'keywords']:
                        new_ticket[field] = crashobj[field]

                    # apply replacements on usernames in owner and reporter field
                    new_ticket['owner'] = self._apply_username_replacements(crashobj['owner'])
                    new_ticket['reporter'] = self._apply_username_replacements(crashobj['reporter'])

                    new_ticket['linked_crash'] = str(crashid)
                    new_ticket.insert()

                # Now add the newly linked tickets as well
                for tkt_obj in ticketobjs:
                    if tkt_obj.id not in crashobj.linked_tickets:
                        ticket_values = self.escape_ticket_values(values)
                        #self.log.debug('ticket_values=%s' % str(ticket_values))
                        comment = """The crash [[/crash/%(uuid)s|CrashId#%(crashid)s - %(uuid)s]] has been uploaded by **%(uploadusername)s**
from **%(uploadhostname)s** and linked to this ticket.

The crash occured at //%(crashtimestamp)s UTC// on **%(crashhostname)s** with user **%(crashusername)s** while running `%(applicationfile)s`. The
application was running as part of %(productname)s (%(productcodename)s) version %(productversion)s (%(producttargetversion)s, %(buildtype)s) on a
%(systemname)s/%(machinetype)s with %(osversion)s (%(osrelease)s/%(osmachine)s).
""" % ticket_values
                        linked_crashes = tkt_obj['linked_crash'] if tkt_obj['linked_crash'] else ''
                        linked_crashes = set([int(x.strip()) for x in linked_crashes.split(',') if x.strip()])
                        #print('crashid=%s' % crashid)
                        #print('linked_crashes=%s' % linked_crashes)
                        linked_crashes.add(crashid)
                        #print('linked_crashes=%s' % linked_crashes)
                        tkt_obj['linked_crash'] = ', '.join(str(x) for x in sorted(linked_crashes))
                        tkt_obj.save_changes(author=crashobj['reporter'], comment=comment)
                    
                        linked_tickets.add(tkt_obj.id)
                        with self.env.db_transaction as db:
                            links = CrashDumpTicketLinks(self.env, tkt=tkt_obj, db=db)
                            links.crashes.add(crashid)
                            links.save(author=crashobj['reporter'], db=db)

            if result:
                if manual_upload:
                    req.redirect(req.abs_href('crash', str(uuid)))
                else:
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
                return self._error_response(req, status=HTTPInternalServerError.code, body='Failed to add crash dump %s to database' % uuid)
            else:
                headers = {}
                headers['Crash-URL'] = req.abs_href('crash', str(uuid))
                headers['CrashId'] = str(crashid)
                return self._error_response(req, status=HTTPInternalServerError.code, body='Failed to update crash dump %s to database' % uuid, headers=headers)
        else:
            if failure_message is None:
                body = 'Failed to process crash dump %s' % uuid
            else:
                body = 'The following occured while processing the crash dump %s: %s' % (uuid, failure_message)
            return self._error_response(req, status=HTTPInternalServerError.code, body=body)

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
            
            body = body + '<crash id=\"%i\" uuid=\"%s\" url=\"%s\" xmlreport=\"%s\" rawfile=\"%s\">\r\n' % \
                (crashobj.id, crashobj['uuid'], 
                    req.href('crash', crashobj['uuid']),
                    req.href('crash', crashobj['uuid'], 'xml'),
                    req.href('crash', crashobj['uuid'], 'raw'),
                    )

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
                body = body + '<ticket id=\"%i\" url=\"%s\">\r\n' % (tkt, req.href.ticket(tkt))
                body = body + '</ticket>\r\n'
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

    def _get_total_upload_size(self, req):
        ret = 0
        files_fields = ['minidump', 'minidumpreport', 'minidumpreportxml', 'minidumpreporthtml',
                        'coredump', 'coredumpreport', 'coredumpreportxml', 'coredumpreporthtml']

        for name in files_fields:
            file = req.args.get(name) if name in req.args else None
            if file is None:
                continue
            if hasattr(file, 'fileno'):
                size = os.fstat(file.fileno())[6]
            else:
                file.file.seek(0, 2) # seek to end of file
                size = file.file.tell()
                file.file.seek(0)
            self.log.debug('found file name %s, size %i' % (name, size))
            ret = ret + size
        return ret

    def _store_dump_file(self, uuid, req, name, force):
        item_name = None
        ret = False
        file = req.args.get(name) if name in req.args else None
        errmsg = None
        if file is None:
            errmsg = 'Field %s not available' % name
        else:
            filename = file.filename
            fileobj = file.file
            item_name = os.path.join(str(uuid), filename)
            crash_dir = os.path.join(self.env.path, self.dumpdata_dir, str(uuid))
            crash_file = os.path.join(crash_dir, filename)
            self.log.debug('_store_dump_file env.path %s' % (self.env.path))
            self.log.debug('_store_dump_file self.dumpdata_dir %s' % (self.dumpdata_dir))
            
            self.log.debug('_store_dump_file item_name %s' % (item_name))
            self.log.debug('_store_dump_file crash_dir %s' % (crash_dir))
            self.log.debug('_store_dump_file crash_file %s' % (crash_file))
            if not os.path.isdir(crash_dir):
                os.makedirs(crash_dir)

            flags = os.O_CREAT + os.O_WRONLY
            flags += os.O_TRUNC
            #if force:
                #flags += os.O_TRUNC
            #else:
                #if os.path.isfile(crash_file):
                    #errmsg = 'File %s already exists.' % crash_file
                    #return (False, item_name, errmsg)
                #flags += os.O_EXCL
            if hasattr(os, 'O_BINARY'):
                flags += os.O_BINARY
            targetfileobj = None
            try:
                targetfileobj = os.fdopen(os.open(crash_file, flags, 0660), 'w')
            except OSError as e:
                errmsg = str(e)
            except IOError as e:
                errmsg = str(e)

            if targetfileobj is None:
                ret = False
                if errmsg is None:
                    errmsg = 'Cannot open file %s.' % crash_file
            else:
                try:
                    shutil.copyfileobj(fileobj, targetfileobj)
                    ret = True
                except OSError as e:
                    errmsg = str(e)
                except IOError as e:
                    errmsg = str(e)
        return (ret, item_name, errmsg)

    def _get_dump_filename(self, crashobj, name):
        item_name = crashobj[name]
        crash_file = os.path.join(self.env.path, self.dumpdata_dir, item_name)
        return crash_file
