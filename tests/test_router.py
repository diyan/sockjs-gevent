"""
Tests for wsgi.py
"""

try:
    import unittest2 as unittest
except ImportError:
    import unittest

import mock

from sockjs_gevent import router, transports

from test_util import BaseHandlerTestCase


class RequestHandlerTestCase(BaseHandlerTestCase):
    """
    Tests for router.RequestHandler
    """

    handler_class = router.RequestHandler


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
        handler = self.make_handler(environ, app.start_response)

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
        handler = self.make_handler(environ, app.start_response)

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
        handler = self.make_handler(environ, app.start_response)

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
        handler = self.make_handler(environ, app.start_response)

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
        handler = self.make_handler(environ, app.start_response)

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
        handler = self.make_handler(environ, app.start_response)
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
        handler = self.make_handler(environ, app.start_response)

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
        handler = self.make_handler(environ, app.start_response)

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
        handler = self.make_handler(environ, app.start_response)
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
        handler = self.make_handler(environ, app.start_response)
        endpoint = mock.Mock()

        endpoint.client_url = 'http://unittest/foobar'

        result = handler.do_iframe(endpoint)

        self.assertIsNone(result)

        app.assertStatus('304 Not Modified')
        app.assertHeaders([])


class TransportTestCase(RequestHandlerTestCase):
    """
    Tests for `RequestHandler.do_transport`
    """

    def make_endpoint(self):
        endpoint = mock.Mock()

        endpoint.transport_allowed.return_value = True

        return endpoint

    def test_transport_not_allowed(self):
        """
        Attempting to connect to an endpoint that does not allow the transport
        type must result in ``not_found`` being called.
        """
        environ = {}

        app = self.make_app()
        endpoint = mock.Mock()
        handler = self.make_handler(environ, app.start_response)

        endpoint.transport_allowed.return_value = False

        handler.do_transport(endpoint, None, None, 'foobar')

        app.assertStatus('404 Not Found')
        app.assertCookie()
        app.assertContentType('text/plain; encoding=UTF-8')

    @mock.patch.object(transports, 'get_transport_class')
    def test_missing_transport(self, mock_get_transport_class):
        """
        If transports.get_transport_class returns ``None`` then ``not_found``
        must be called.
        """
        environ = {}

        app = self.make_app()
        endpoint = self.make_endpoint()
        handler = self.make_handler(environ, app.start_response)

        mock_get_transport_class.return_value = None
        handler.do_transport(endpoint, None, None, 'foobar')

        app.assertStatus('404 Not Found')
        app.assertCookie()
        app.assertContentType('text/plain; encoding=UTF-8')

    @mock.patch.object(transports, 'get_transport_class')
    def test_bind_new_session(self, mock_get_transport_class):
        """
        A new session must make a new connection and bind to it.
        """
        environ = {}

        app = self.make_app()
        endpoint = self.make_endpoint()
        handler = self.make_handler(environ, app.start_response)

        readable_transport = mock.Mock()
        mock_get_transport_class.return_value = readable_transport

        readable_transport.socket = False
        readable_transport.writable = False

        session = mock.Mock()
        endpoint.get_session.return_value = session

        handler.do_transport(endpoint, None, 'xyz', 'foobar')

    @mock.patch.object(transports, 'get_transport_class')
    def test_unknown_transport_session(self, mock_get_transport_class):
        """
        If ``get_session_for_transport`` does not return a valid session,
        ``not_found`` must be called.
        """
        environ = {}

        app = self.make_app()
        endpoint = self.make_endpoint()
        handler = self.make_handler(environ, app.start_response)

        endpoint.get_session_for_transport.return_value = None
        readable_transport = mock.Mock()
        mock_get_transport_class.return_value = readable_transport

        readable_transport.socket = False

        handler.do_transport(endpoint, None, 'xyz', 'foobar')

    @mock.patch.object(transports, 'get_transport_class')
    def test_session_interrupt_on_exc(self, mock_get_transport_class):
        """
        If a transport raises an exception, it must be propagated.
        The session must be interrupted.
        """
        endpoint = self.make_endpoint()
        handler = self.make_handler({}, None)
        transport_cls = mock.Mock()
        session = mock.Mock()

        session.new = False
        transport_cls.socket = False

        endpoint.get_session_for_transport.return_value = session
        mock_get_transport_class.return_value = transport_cls

        transport = mock.Mock()

        transport_cls.return_value = transport

        transport.handle_request.side_effect = RuntimeError

        with self.assertRaises(RuntimeError) as ctx:
            handler.do_transport(endpoint, None, 'xyz', 'foobar')

        transport_cls.assert_called_with(handler, {}, session)
        session.interrupt.assert_called_with()

    @mock.patch.object(transports, 'get_transport_class')
    def test_session_interrupt_socket_error(self, mock_get_transport_class):
        """
        If a transport raisea a socket.error exception, it must be swallowed.
        The session must be interrupted.
        """
        import socket

        endpoint = self.make_endpoint()
        handler = self.make_handler({}, None)
        transport_cls = mock.Mock()
        session = mock.Mock()

        session.new = False
        transport_cls.socket = False

        endpoint.get_session_for_transport.return_value = session
        mock_get_transport_class.return_value = transport_cls

        transport = mock.Mock()

        transport_cls.return_value = transport
        transport.handle_request.side_effect = socket.error

        handler.do_transport(endpoint, None, 'xyz', 'foobar')

        transport_cls.assert_called_with(handler, {}, session)
        session.interrupt.assert_called_with()

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
    Tests for ``router.route_request``
    """

    def make_environ(self, path):
        """
        Return a wsgi compatible environ dict based on the supplied url.
        """
        return {
            'PATH_INFO': path
        }

    def make_app(self, **endpoints):
        if not endpoints:
            endpoints = {
                'foo': mock.Mock()
            }

        return MockApp(endpoints)

    def run_path(self, app, path, test_app=None):
        environ = self.make_environ(path)

        handler = mock.Mock()
        router.route_request(app, environ, handler)

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
        endpoint = mock.Mock()
        app = self.make_app(foo=endpoint)
        path = '/foo/bar/baz/gak'

        handler = self.run_path(app, path)

        handler.do_transport.assert_called_with(endpoint, 'bar', 'baz', 'gak')

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
