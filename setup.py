#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;
import os

from setuptools import find_packages, setup

setup(
    name = 'TracCrashDump',
    version = '0.41',
    packages=find_packages(exclude=['*.tests*']),
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
        #'Development Status :: 3 - Alpha',
        #'Development Status :: 4 - Beta',
        'Development Status :: 5 - Production/Stable',
        #'Development Status :: 6 - Mature',
        #'Development Status :: 7 - Inactive',
        'Environment :: Web Environment',
        'License :: OSI Approved :: BSD License',
        'Natural Language :: English',
        'Operating System :: OS Independent',
        'Programming Language :: Python',
    ],
    
    install_requires = ['Trac>=0.12'],
    test_suite='crashdump.tests.test_suite',
    tests_require=[],
    entry_points = {
        'trac.plugins': [
            'crashdump.web_ui = crashdump.web_ui',
            'crashdump.submit = crashdump.submit',
            'crashdump.api = crashdump.api',
        ]
    }
)
