from trac.core import *
from trac.util.html import html
from trac.web import IRequestHandler, IRequestFilter
from trac.web.api import arg_list_to_args, RequestDone, HTTPMethodNotAllowed, HTTPForbidden, HTTPInternalError
from trac.web.chrome import INavigationContributor, ITemplateProvider
from pkg_resources import resource_filename
from uuid import UUID
import cgi

class _FieldStorage(cgi.FieldStorage):
    """Our own version of cgi.FieldStorage, with tweaks."""

    def read_multi(self, *args, **kwargs):
        try:
            cgi.FieldStorage.read_multi(self, *args, **kwargs)
        except ValueError:
            # Most likely "Invalid boundary in multipart form",
            # possibly an upload of a .mht file? See #9880.
            self.read_single()

class CrashDumpSubmit(Component):
    implements(IRequestHandler, IRequestFilter, ITemplateProvider)

    # IRequestHandler methods
    def match_request(self, req):
        if req.method == 'POST' and (req.path_info == '/crashdump/submit' or req.path_info == '/submit'):
            #self.log.debug('match_request: %s %s', req.method, req.path_info)
            return True
        else:
            return False

    def _error_response(self, req, status, body=None):
        req.send_error(None, template='', content_type='text/plain', status=status, env=None, data=body)

    def pre_process_request(self, req, handler):
        self.log.debug('CrashDumpSubmit pre_process_request: %s %s', req.method, req.path_info)
        # copy the requested form token from into the args to pass the CSRF test
        req.args['__FORM_TOKEN' ] = req.form_token
        return handler

    def post_process_request(self, req, template, data, content_type, method=None):
        True

    def process_request(self, req):
        self.log.debug('CrashDumpSubmit process_request: %s %s', req.method, req.path_info)
        if req.method != "POST":
            return self._error_response(req, status=HTTPMethodNotAllowed.code, body='Method %s not allowed' % req.method)
        else:
            user_agent = req.get_header('User-Agent')
            if user_agent is None:
                return self._error_response(req, status=HTTPForbidden.code, body='No user-agent specified.')
            else:
                if '/' in user_agent:
                    user_agent, agent_ver = user_agent.split('/', 1)
                if user_agent != 'terra3d-crashuploader':
                    return self._error_response(req, status=HTTPForbidden.code, body='User-agent %s not allowed' % user_agent)
                else:
                    id_str = req.args.get('id')
                    if id_str and id_str != '00000000-0000-0000-0000-000000000000' and id_str != '{00000000-0000-0000-0000-000000000000}':
                        uuid = UUID(id_str)
                        result = True
                    else:
                        uuid = UUID('00000000-0000-0000-0000-000000000000')
                        result = False
                    if result:
                        applicationfile = req.args.get('applicationfile')
                        force_str = req.args.get('force') or 'false'
                        force = True if force_str.lower() == 'true' else False
                        timestamp = req.args.get('timestamp')

                        productname = req.args.get('productname')
                        productversion = req.args.get('productversion')
                        producttargetversion = req.args.get('producttargetversion')
                        fqdn = req.args.get('fqdn')
                        username = req.args.get('username')
                        buildtype = req.args.get('buildtype')
                        buildpostfix = req.args.get('buildpostfix')
                        machinetype = req.args.get('machinetype')
                        systemname = req.args.get('systemname')
                        osversion = req.args.get('osversion')
                        osrelease = req.args.get('osrelease')
                        osmachine = req.args.get('osmachine')
                        sysinfo = req.args.get('sysinfo')

                    data = {'uuid': str(uuid), 'applicationfile': applicationfile}
                    return 'hello.html', data, None

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
