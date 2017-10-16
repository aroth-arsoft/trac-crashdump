#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;
from StringIO import StringIO
from arsoft.inifile import IniFile

class FastprotectVersionInfo(object):
    def __init__(self, rawdata):

        import StringIO
        stream = StringIO.StringIO(rawdata)
        ini = IniFile(filename=None, commentPrefix=';', keyValueSeperator='=', qt=True)
        ini.open(stream)

        self.product_name = ini.get(None, 'productName')
        self.product_code_name = ini.get(None, 'productCodename')
        self.product_version = ini.get(None, 'productVersion')
        self.product_target_version = ini.get(None, 'productTargetVersion')
        self.product_build_type = ini.get(None, 'productBuildType')
        self.product_build_postfix = ini.get(None, 'productBuildPostfix')
        self.root_revision = ini.get(None, 'sourceRootRevision')
        self.buildtools_revision = ini.get(None, 'sourceBuildtoolsRevision')
        self.external_revision = ini.get(None, 'sourceExternalRevision')
        self.third_party_revision = ini.get(None, 'source3rdPartyRevision')
        self.terra3d_revision = ini.get(None, 'sourceTerra3DRevision')
        self.manual_revision = ini.get(None, 'sourceManualRevision')
        self.jenkins_job_name = ini.get(None, 'jenkinsJobName')
        self.jenkins_build_number = ini.getAsInteger(None, 'jenkinsJobBuildNumber')
        self.jenkins_build_id = ini.get(None, 'jenkinsJobBuildId')
        self.jenkins_build_tag = ini.get(None, 'jenkinsJobBuildTag')
        self.jenkins_build_url = ini.get(None, 'jenkinsJobBuildUrl')
        self.jenkins_git_revision = ini.get(None, 'jenkinsJobBuildGitRevision')
        self.jenkins_git_branch = ini.get(None, 'jenkinsJobBuildGitBranch')
        self.jenkins_master = ini.get(None, 'jenkinsMaster')
        self.jenkins_nodename = ini.get(None, 'jenkinsNodename')
        self.threadname_tlsslot = ini.getAsInteger(None, 'threadNameTLSSlot')

    def __str__(self):
        return '%s %s (%s)' % (self.product_name, self.product_target_version, self.product_version)

