#!/usr/bin/env python
# -*- coding: iso-8859-1 -*-
import os

from setuptools import setup

setup(
    name = 'TracCrashDump',
    version = '0.26',
    packages = ['crashdump'],
    package_data = { 'crashdump': ['templates/*.html', 'htdocs/*.js', 'htdocs/*.css' ] },

    author = 'Andreas Roth',
    author_email = 'aroth@arsoft-online.com',
    description = 'Simple crashdump management.',
    long_description = open(os.path.join(os.path.dirname(__file__), 'README')).read(),
    license = 'BSD',
    platforms = ['Linux'],
    keywords = 'trac plugin crash dump',
    url = 'https://github.com/aroth-arsoft/trac-crashdump',
    classifiers = [
        'Framework :: Trac',
        #'Development Status :: 1 - Planning',
        #'Development Status :: 2 - Pre-Alpha',
        # 'Development Status :: 3 - Alpha',
        'Development Status :: 4 - Beta',
        #'Development Status :: 5 - Production/Stable',
        # 'Development Status :: 6 - Mature',
        # 'Development Status :: 7 - Inactive',
        'Environment :: Web Environment',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    
    install_requires = ['Trac>=0.12'],

    entry_points = {
        'trac.plugins': [
            'crashdump.web_ui = crashdump.web_ui',
            'crashdump.submit = crashdump.submit',
            'crashdump.api = crashdump.api',
        ]
    }
)
