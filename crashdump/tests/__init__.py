#!/usr/bin/python
# -*- coding: utf-8 -*-
# kate: space-indent on; indent-width 4; mixedindent off; indent-mode python;

import unittest

from crashdump.tests import api, web_ui, model


def test_suite():
    suite = unittest.TestSuite()
    suite.addTest(api.test_suite())
    suite.addTest(web_ui.test_suite())
    suite.addTest(model.test_suite())

    return suite


# Start test suite directly from command line like so:
#   $> PYTHONPATH=$PWD python crashdump/tests/__init__.py
if __name__ == '__main__':
    unittest.main(defaultTest="test_suite")
