"""
Tests for wsgi.py
"""

try:
    import unittest2 as unittest
except ImportError:
    import unittest

import mock

from sockjs_gevent import wsgi

from test_util import BaseHandlerTestCase


class RequestHandlerTestCase(BaseHandlerTestCase):
    """
    Tests for wsgi.RequestHandler
    """

    handler_class = wsgi.RequestHandler


class GreetingTestCase(RequestHandlerTestCase):
    """
    Tests for `RequestHandler.do_greeting`
    """

    def test_non_get(self):
        """
        Greetings must only respond to GET http verbs
        """
        environ = {}

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)

        expected_headers = [
            ('Allow', 'OPTIONS, GET'),
            ('Connection', 'close'),
        ]

        for verb in ['POST', 'PUT']:
            environ['REQUEST_METHOD'] = verb
            result = handler.do_greeting()

            self.assertIsNone(result)

            app.assertStatus('405 Not Allowed')

            for header in expected_headers:
                app.assertHasHeader(header)

            self.assertEqual(app.out.getvalue(), '')

    def test_OPTIONS(self):
        """
        Greetings must respond correctly to OPTIONS requests
        """
        environ = {
            'REQUEST_METHOD': 'OPTIONS'
        }

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)

        result = handler.do_greeting()

        self.assertIsNone(result)

        app.assertStatus('204 No Content')
        app.assertCookie()
        app.assertCached()
        app.assertCors()

        app.assertHasHeader(
            ('Access-Control-Allow-Methods', 'OPTIONS, GET')
        )

    def test_GET(self):
        """
        Greetings must say hello!
        """
        environ = {
            'REQUEST_METHOD': 'GET'
        }

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)

        result = handler.do_greeting()

        self.assertIsNone(result)

        app.assertStatus('200 OK')
        app.assertCached()
        self.assertEqual(app.out.getvalue(), 'Welcome to SockJS!\n')


class InfoTestCase(RequestHandlerTestCase):
    """
    Tests for `RequestHandler.do_info`
    """

    def test_non_get(self):
        """
        Info requests must only respond to GET http verbs
        """
        environ = {}

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)

        expected_headers = [
            ('Allow', 'OPTIONS, GET'),
            ('Connection', 'close'),
        ]

        for verb in ['POST', 'PUT']:
            environ['REQUEST_METHOD'] = verb
            result = handler.do_info(None)

            self.assertIsNone(result)

            app.assertStatus('405 Not Allowed')

            for header in expected_headers:
                app.assertHasHeader(header)

            self.assertEqual(app.out.getvalue(), '')

    def test_OPTIONS(self):
        """
        Info requests must respond correctly to OPTIONS requests
        """
        environ = {
            'REQUEST_METHOD': 'OPTIONS'
        }

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)

        result = handler.do_info(None)

        self.assertIsNone(result)

        app.assertStatus('204 No Content')
        app.assertCookie()
        app.assertCached()
        app.assertCors()

        app.assertHasHeader(
            ('Access-Control-Allow-Methods', 'OPTIONS, GET')
        )

    def test_GET(self):
        """
        Info requests must provide some info.
        """
        environ = {
            'REQUEST_METHOD': 'GET'
        }

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)
        endpoint = mock.Mock()

        endpoint.get_info.return_value = {'foo': 'bar'}

        result = handler.do_info(endpoint)

        self.assertIsNone(result)

        app.assertStatus('200 OK')
        app.assertNotCached()
        app.assertCors()
        app.assertContentType('application/json; encoding=UTF-8')
        self.assertEqual(app.out.getvalue(), '{"foo": "bar"}')


class IframeTestCase(RequestHandlerTestCase):
    """
    Tests for `RequestHandler.do_iframe`
    """

    def test_non_get(self):
        """
        Info requests must only respond to GET http verbs
        """
        environ = {}

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)

        expected_headers = [
            ('Allow', 'OPTIONS, GET'),
            ('Connection', 'close'),
        ]

        for verb in ['POST', 'PUT']:
            environ['REQUEST_METHOD'] = verb
            result = handler.do_iframe(None)

            self.assertIsNone(result)

            app.assertStatus('405 Not Allowed')

            for header in expected_headers:
                app.assertHasHeader(header)

            self.assertEqual(app.out.getvalue(), '')

    def test_OPTIONS(self):
        """
        Info requests must respond correctly to OPTIONS requests
        """
        environ = {
            'REQUEST_METHOD': 'OPTIONS'
        }

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)

        result = handler.do_iframe(None)

        self.assertIsNone(result)

        app.assertStatus('204 No Content')
        app.assertCookie()
        app.assertCached()
        app.assertCors()

        app.assertHasHeader(
            ('Access-Control-Allow-Methods', 'OPTIONS, GET')
        )

    def test_GET(self):
        """
        Info requests must provide some info.
        """
        environ = {
            'REQUEST_METHOD': 'GET'
        }

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)
        endpoint = mock.Mock()

        endpoint.client_url = 'http://unittest/foobar'

        result = handler.do_iframe(endpoint)

        self.assertIsNone(result)

        app.assertStatus('200 OK')
        app.assertCached()
        app.assertCors()
        app.assertContentType('text/html; encoding=UTF-8')
        self.assertIn(endpoint.client_url, app.out.getvalue())

    def test_cached(self):
        """
        A cached response must be returned if the correct request is made.
        """
        etag = '4b13e587b0fa3c4008d9f850a20f4fc8'
        environ = {
            'REQUEST_METHOD': 'GET',
            'HTTP_IF_NONE_MATCH': etag
        }

        app = self.make_app()
        handler = self.make_handler(None, environ, app.start_response)
        endpoint = mock.Mock()

        endpoint.client_url = 'http://unittest/foobar'

        result = handler.do_iframe(endpoint)

        self.assertIsNone(result)

        app.assertStatus('304 Not Modified')
        app.assertHeaders([])


class MockApp(object):
    """
    A mock SockJS App that handles endpoint discovery.
    """

    def __init__(self, endpoints=None):
        self.endpoints = endpoints or {}

    def get_endpoint(self, name):
        return self.endpoints.get(name, None)


class RequestRouterTestCase(unittest.TestCase):
    """
    Tests for ``wsgi.route_request``
    """

    def make_environ(self, path):
        """
        Return a wsgi compatible environ dict based on the supplied url.
        """
        return {
            'PATH_INFO': path
        }

    def make_app(self, endpoints=None):
        if endpoints is None:
            endpoints = {
                'foo': mock.Mock()
            }

        return MockApp(endpoints)

    def run_path(self, app, path, test_app=None):
        environ = self.make_environ(path)

        handler = mock.Mock()
        wsgi.route_request(app, environ, handler)

        return handler

    def test_greeting(self):
        """
        Test all greeting urls
        """
        app = self.make_app()

        for path in ['', '/']:
            handler = self.run_path(app, path)

            self.assertTrue(handler.do_greeting.called)

    def test_endpoint(self):
        """
        Test endpoint urls
        """
        app = self.make_app()

        for path in ['/foo', '/foo/']:
            handler = self.run_path(app, path)

            self.assertTrue(handler.do_greeting.called)

    def test_missing_endpoint(self):
        """
        A request to a missing endpoint url must return a 404.
        """
        # no endpoints on this app
        app = self.make_app()

        for path in ['/bar', '/bar/']:
            handler = self.run_path(app, path)

            self.assertTrue(handler.not_found.called)

    def test_endpoint_trailing_slashes(self):
        """
        A request to a good endpoint url with trailing slashes return a 404.
        """
        app = self.make_app()
        handler = self.run_path(app, '/foo//')

        self.assertTrue(handler.not_found.called)

    def test_info(self):
        """
        /foo/info must call handler.do_info
        """
        app = self.make_app()

        for path in ['/foo/info', '/foo/info/']:
            handler = self.run_path(app, path)

            self.assertTrue(handler.do_info.called)

    def test_info_trailing_slashes(self):
        """
        /foo/info// must call handler.not_found
        """
        app = self.make_app()
        path = '/foo/info//'
        handler = self.run_path(app, path)

        self.assertTrue(handler.not_found.called)

    def test_iframe(self):
        """
        /foo/iframe must call handler.not_found
        """
        app = self.make_app()
        path = '/foo/iframe'
        handler = self.run_path(app, path)

        self.assertTrue(handler.not_found.called)

    def test_iframe_extra(self):
        """
        /foo/iframe123.html must call handler.do_iframe
        """
        app = self.make_app()
        path = '/foo/iframe123.html'
        handler = self.run_path(app, path)

        self.assertTrue(handler.do_iframe.called)

    def test_server_id(self):
        """
        /foo/. must call handler.not_found
        """
        app = self.make_app()

        for path in ['/foo/.', '/foo/bar.', '/foo/bar./']:
            handler = self.run_path(app, path)

            self.assertTrue(handler.not_found.called)

        # urls that terminat at the server_id must respond with not_found

        for path in ['/foo/bar', '/foo/bar/']:
            handler = self.run_path(app, path)

            self.assertTrue(handler.not_found.called)

    def test_session_id(self):
        """
        /foo/bar/. must call handler.not_found
        """
        app = self.make_app()

        for path in ['/foo/bar/.', '/foo/bar/baz.', '/foo/bar/baz./']:
            handler = self.run_path(app, path)

            self.assertTrue(handler.not_found.called)

        # urls that terminate at the session_id must respond with not_found

        for path in ['/foo/bar/baz', '/foo/bar/baz/']:
            handler = self.run_path(app, path)

            self.assertTrue(handler.not_found.called)

    def test_transport(self):
        """
        Urls of the form /foo/bar/baz/gak must call handler.do_transport
        """
        app = self.make_app()
        path = '/foo/bar/baz/gak'

        handler = self.run_path(app, path)

        handler.do_transport.assert_called_with('bar', 'baz', 'gak')

    def test_transport_trailing(self):
        """
        Trailing slashes on the transport url must call handler.not_found
        """
        app = self.make_app()
        path = '/foo/bar/baz/gak/'

        handler = self.run_path(app, path)

        self.assertTrue(handler.not_found.called)

    def test_raw_websocket(self):
        """
        Urls of the format /foo/websocket must call do_transport
        """
        app = self.make_app()
        path = '/foo/websocket'

        handler = self.run_path(app, path)

        handler.do_transport.assert_called_with(None, None, 'rawwebsocket')
