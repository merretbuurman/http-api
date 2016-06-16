# -*- coding: utf-8 -*-

"""
Tests
"""

# import io
# import os
import json
import unittest
# import commons.htmlcodes as hcodes
from commons.logs import get_logger
from restapi.server import create_app
from restapi.confs.config import USER, PWD, \
    TEST_HOST, SERVER_PORT, API_URL, AUTH_URL

from commons import myself

__author__ = myself
logger = get_logger(__name__, True)

API_URI = 'http://%s:%s%s' % (TEST_HOST, SERVER_PORT, API_URL)
AUTH_URI = 'http://%s:%s%s' % (TEST_HOST, SERVER_PORT, AUTH_URL)


class TestDataObjects(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        logger.info('### Setting up flask server ###')
        app = create_app(testing=True)
        cls.app = app.test_client()

        loginURI = os.path.join(AUTH_URI, 'login')
        r = cls.app.post(loginURI,
                         data=json.dumps({'username': USER, 'password': PWD}))
        content = json.loads(r.data.decode('utf-8'))
        cls.token = content['Response']['data']['token']
        cls.auth_header = {
            'Authorization': 'Bearer %s' % cls.token}

    @classmethod
    def tearDownClass(cls):
        logger.info('### Tearing down the flask server ###')

        # Tokens clean up
        from restapi.resources.services.neo4j.graph import MyGraph
        MyGraph().clean_pending_tokens()

    # def test_01_get_someendpoint(self):

    #     logger.debug("Testing a random endpoint")
    #     r = self.app.get(AUTH_URI + '/profile', headers=self.auth_header)
    #     self.assertEqual(r.status_code, hcodes.HTTP_OK_BASIC)