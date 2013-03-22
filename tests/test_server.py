"""
Tests for ``sockjs_gevent.server``
"""

try:
    import unittest2 as unittest
except ImportError:
    import unittest

import mock

from sockjs_gevent import server


class ApplicationTestCase(unittest.TestCase):
    """
    Tests for server.Application
    """

    def make_app(self, **endpoints):
        return server.Application(endpoints)

    def test_init(self):
        """
        Ensure that endpoints are added at init time.
        """
        endpoint = mock.Mock()

        app = self.make_app(foo=endpoint)

        self.assertIs(endpoint, app.get_endpoint('foo'))
        self.assertIsNone(app.get_endpoint('bar'))

        # Ensure that it is not added
        self.assertFalse(endpoint.start.called)

    def test_start(self):
        """
        Starting the application must start the endpoints
        """
        endpoint = mock.Mock()
        app = self.make_app(foo=endpoint)

        self.assertFalse(app.started)
        self.assertFalse(endpoint.start.called)

        app.start()

        self.assertTrue(app.started)
        self.assertTrue(endpoint.start.called)

        endpoint.start.side_effect = RuntimeError

        app.start()

    def test_stop(self):
        """
        Ensure that stopping the application stops the endpoints
        """
        endpoint = mock.Mock()
        app = self.make_app(foo=endpoint)

        app.start()

        self.assertTrue(app.started)
        self.assertFalse(endpoint.stop.called)

        app.stop()

        self.assertFalse(app.started)
        self.assertTrue(endpoint.stop.called)

        endpoint.stop.side_effect = RuntimeError

        app.stop()

    def test_add_endpoint(self):
        """
        Ensure that the endpoint interface is upheld.
        """
        endpoint = mock.Mock()
        app = self.make_app()

        result = app.add_endpoint('foo', endpoint)

        self.assertIsNone(result)
        self.assertIs(endpoint, app.endpoints['foo'])
        endpoint.bind_to_application.assert_called_with(app)

    def test_add_endpoint_start_app(self):
        """
        Ensure that endpoint.start() is called when adding an endpoint to an
        already started applications.
        """
        endpoint = mock.Mock()
        app = self.make_app()

        app.start()

        self.assertFalse(endpoint.start.called)

        app.add_endpoint('foo', endpoint)

        self.assertTrue(endpoint.start.called)

    def test_add_existing_endpoint(self):
        """
        Adding an endpoint with a name that already exists should raise a
        ``NameError`` exception.
        """
        endpoint = mock.Mock()
        app = self.make_app(foo=endpoint)

        self.assertRaises(NameError, app.add_endpoint, 'foo', None)

    def test_remove_endpoint_missing(self):
        """
        Removing an endpoint that does not exist on the Application must raise
        a ``NameError`` exception.
        """
        app = self.make_app()

        self.assertRaises(NameError, app.remove_endpoint, 'foo')

    def test_remove_endpoint(self):
        """
        Removing an endpoint must call endpoint.stop()
        """
        endpoint = mock.Mock()
        app = self.make_app(foo=endpoint)

        result = app.remove_endpoint('foo')

        self.assertIs(result, endpoint)
        self.assertNotIn('foo', app.endpoints)
        self.assertTrue(endpoint.stop.called)


class ConnectionTestCase(unittest.TestCase):
    """
    Tests for ``server.Connection``
    """

    def make_conn(self, endpoint=None, session=None):
        """
        Make a ``Connection`` object.
        """
        endpoint = endpoint or mock.Mock()
        session = session or mock.Mock()

        return server.Connection(endpoint, session)

    def test_create(self):
        """
        Ensure that creating a ``Connection`` object works.
        """
        endpoint = object()
        session = object()

        conn = self.make_conn(endpoint, session)

        self.assertIs(endpoint, conn.endpoint)
        self.assertIs(session, conn.session)

    def test_send(self):
        """
        Sending a mesage must call ``session.add_messages``
        """
        session = mock.Mock()
        conn = self.make_conn(session=session)

        conn.send('foobar')

        session.add_messages.assert_called_with('foobar')

    def test_send_no_session(self):
        """
        If the session no longer exists, calling send must be a noop.
        """
        session = mock.Mock()
        conn = self.make_conn(session=session)

        conn.session = None

        conn.send('foobar')

        self.assertFalse(session.add_messages.called)

    def test_close(self):
        """
        Ensure that closing a connection cleans up correctly.
        """
        endpoint = mock.Mock()
        session = mock.Mock()

        conn = self.make_conn(endpoint, session)

        conn.close()

        self.assertIsNone(conn.session)
        self.assertIsNone(conn.endpoint)
        endpoint.connection_closed.assert_called_with(conn)
        self.assertTrue(session.close.called)

    def test_already_closed(self):
        """
        Closing an already closed connection must be a noop.
        """
        session = mock.Mock()

        conn = self.make_conn(session=session)

        conn.close()
        session.close.side_effect = RuntimeError

        conn.close()
