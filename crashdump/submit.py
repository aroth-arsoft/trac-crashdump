from trac.core import *
from trac.util.html import html
from trac.web import IRequestHandler
from trac.web.chrome import INavigationContributor, ITemplateProvider
from pkg_resources import resource_filename

class CrashDumpSubmit(Component):
    implements(IRequestHandler, ITemplateProvider)

    # IRequestHandler methods
    def match_request(self, req):
        return req.path_info == '/crashdump/submit'
    def process_request(self, req):
        data = {}
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
