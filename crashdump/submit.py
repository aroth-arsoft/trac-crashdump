from trac.core import *
from trac.util.html import html
from trac.web import IRequestHandler
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
    implements(IRequestHandler, ITemplateProvider)

    # IRequestHandler methods
    def match_request(self, req):
        return req.path_info == '/crashdump/submit' or req.path_info == '/submit';

    def _error_response(self, req, status, body=None):
        req.send_error(None, template='', content_type='text/plain', status=status, env=None, data=body)

    def _parse_args_for_crashdump(self, req):
        """Parse the supplied request parameters into a list of
        `(name, value)` tuples.
        """
        fp = req.environ['wsgi.input']

        # Avoid letting cgi.FieldStorage consume the input stream when the
        # request does not contain form data
        ctype = req.get_header('Content-Type')
        if ctype:
            ctype, options = cgi.parse_header(ctype)
        if ctype not in ('application/x-www-form-urlencoded',
                         'multipart/form-data',
                         'application/terra3d-crashdump'):
            fp = StringIO('')

        # Python 2.6 introduced a backwards incompatible change for
        # FieldStorage where QUERY_STRING is no longer ignored for POST
        # requests. We'll keep the pre 2.6 behaviour for now...
        if req.method == 'POST':
            qs_on_post = req.environ.pop('QUERY_STRING', '')
        fs = _FieldStorage(fp, environ=req.environ, keep_blank_values=True)
        if req.method == 'POST':
            req.environ['QUERY_STRING'] = qs_on_post

        args = []
        for value in fs.list or ():
            name = value.name
            if not value.filename:
                value = unicode(value.value, 'utf-8')
            args.append((name, value))
        args.append(('contenttype', str(ctype)))
        args.append(('fp', str(fp.name)))
        return arg_list_to_args(args)

    def process_request(self, req):
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
                    args = self._parse_args_for_crashdump(req)

                    id_str = args.get('id')
                    if id_str and id_str != '00000000-0000-0000-0000-000000000000' and id_str != '{00000000-0000-0000-0000-000000000000}':
                        crashid = UUID(id_str)
                        result = True
                    else:
                        crashid = UUID('00000000-0000-0000-0000-000000000000')
                        result = False
                    if result:
                        applicationfile = args.get('applicationfile')
                        force_str = args.get('force') or 'false'
                        force = True if force_str.lower() == 'true' else False
                        timestamp = args.get('timestamp')

                        productname = args.get('productname')
                        productversion = args.get('productversion')
                        producttargetversion = args.get('producttargetversion')
                        fqdn = args.get('fqdn')
                        username = args.get('username')
                        buildtype = args.get('buildtype')
                        buildpostfix = args.get('buildpostfix')
                        machinetype = args.get('machinetype')
                        systemname = args.get('systemname')
                        osversion = args.get('osversion')
                        osrelease = args.get('osrelease')
                        osmachine = args.get('osmachine')
                        sysinfo = args.get('sysinfo')

                    data = {'uuid': str(args)}
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
