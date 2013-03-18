try:
    from unittest2 import unittest
except ImportError:
    import unittest

try:
    from cStringIO import StringIO
except ImportError:
    from StringIO import StringIO

from datetime import datetime

from sockjs_gevent import util


class WSGITestApp(object):
    def __init__(self, test):
        self.test = test
        self.status = None
        self.headers = None
        self.out = StringIO()

    def start_response(self, status, headers):
        self.status = status
        self.headers = headers

        return self.out.write

    def assertStatus(self, status):
        self.test.assertEqual(self.status, status)

    def assertContentType(self, content_type):
        response_type = self.getHeader('Content-Type')

        self.test.assertEqual(len(response_type), 1,
                              'More than one Content-Type header found')

        self.test.assertEqual(response_type[0], content_type)

    def assertHeaders(self, headers):
        assert self.status, 'start_response not called'

        if len(headers) != len(self.headers):
            self.test.assertEqual(headers, self.headers)

        for header in self.headers:
            if header not in headers:
                self.test.assertEquals(headers, self.headers)

    def getHeader(self, key):
        """
        Returns a list of values for a specific header.
        """
        ret = []

        for response_header in self.headers:
            if key != response_header[0]:
                continue

            ret.append(response_header[1])

        return ret

    def assertHasHeader(self, header):
        """
        Ensures that the headers from the call to `start_response` contain
        this header tuple only once.
        """
        found = False

        for response_header in self.headers:
            if header[0] != response_header[0]:
                continue

            if found:
                raise AssertionError('Multiple headers found %r' % (
                    self.headers,
                ))

            self.test.assertEqual(header[1], response_header[1])
            found = True

        if found:
            return

        raise AssertionError('No header %r found' % (header,))

    def assertCookie(self):
        """
        Checks the response from the call to ``start_response`` for a SockJS
        compliant cookie
        """
        found = False

        for header in self.headers:
            if header[0] != 'Set-Cookie':
                continue

            if found:
                raise AssertionError('Multiple cookie headers found %r' % (
                    self.headers,
                ))

            self.test.assertEqual(header[1], 'JSESSIONID=dummy; Path=/')
            found = True

        if found:
            return

        raise AssertionError('No cookie header found')

    def assertCached(self):
        """
        Checks the response from ``start_response`` for a valid cacheable
        response.
        """
        expected_headers = [
            ('Cache-Control', 'max-age=31536000, public'),
            ('Access-Control-Max-Age', '31536000'),
        ]

        for header in expected_headers:
            self.assertHasHeader(header)

        expires = self.getHeader('Expires')

        self.test.assertEqual(len(expires), 1,
                              'More than one Expires header found')

        expires = datetime.strptime(expires[0], '%a, %d %b %Y %H:%M:%S GMT')
        seconds_delta = (expires - datetime.utcnow()).seconds

        self.test.assertEqual(seconds_delta, 86399)

    def assertCors(self):
        """
        Ensures that the response is cross domain compatible.
        """
        expected_headers = [
            ('Access-Control-Allow-Origin', '*'),
            ('Access-Control-Allow-Credentials', 'true'),
        ]

        for header in expected_headers:
            self.assertHasHeader(header)


class BaseHandlerTestCase(unittest.TestCase):
    """
    Tests for `util.BaseHandler`
    """

    def make_app(self):
        return WSGITestApp(self)

    def make_handler(self, environ, start_response):
        if environ is None:
            environ = {}

        return util.BaseHandler(environ, start_response)


class OptionHandlerTestCase(BaseHandlerTestCase):
    """
    Tests for `util.BaseHandler.handle_option`
    """

    def test_disallowed_method(self):
        """
        Attempting to fetch a disallowed method must result in a error http
        response.
        """
        environ = {
            'REQUEST_METHOD': 'PATCH'
        }
        app = self.make_app()
        handler = self.make_handler(environ, app.start_response)

        result = handler.handle_options('GET')

        self.assertTrue(result)
        app.assertStatus('405 Not Allowed')
        app.assertHeaders([
            ('Allow', 'OPTIONS, GET'),
            ('Connection', 'close'),
        ])
        self.assertEqual(app.out.getvalue(), '')

    def test_allowed_method(self):
        """
        Fetching a resource with an allowed method must not result in an http
        status.
        """
        environ = {
            'REQUEST_METHOD': 'GET'
        }
        app = self.make_app()
        handler = self.make_handler(environ, app.start_response)

        result = handler.handle_options('GET')

        self.assertFalse(result)
        self.assertFalse(app.status)

    def test_options(self):
        """
        Fetching a resource with the OPTIONS method must provide a list of
        allowed HTTP verbs
        """
        environ = {
            'REQUEST_METHOD': 'OPTIONS'
        }
        app = self.make_app()
        handler = self.make_handler(environ, app.start_response)

        result = handler.handle_options('GET', 'POST')

        self.assertTrue(result)
        app.assertStatus('204 No Content')
        app.assertCookie()
        app.assertCached()
        app.assertCors()
        app.assertHasHeader(
            ('Access-Control-Allow-Methods', 'OPTIONS, GET, POST'),
        )


class WriteTestCase(BaseHandlerTestCase):
    """
    Tests for `util.BaseHandler.write_*`.
    """

    def test_write_text(self):
        """
        Writing a text response must call `start_response` with the correct
        content type.
        """
        app = self.make_app()
        handler = self.make_handler({}, app.start_response)

        result = handler.write_text('This is a test!')

        self.assertEqual(result, app.out.write)
        app.assertStatus('200 OK')
        app.assertContentType('text/plain; encoding=UTF-8')
