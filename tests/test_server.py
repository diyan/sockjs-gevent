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

    def test_del_exception(self):
        """
        Ensure that when __del__ is called, no exception is raised.
        """
        app = self.make_app()

        with mock.patch.object(app, 'stop') as mock_stop:
            mock_stop.side_effect = RuntimeError

            app.__del__()


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




class EndpointTestCase(unittest.TestCase):
    """
    Tests for ``server.Endpoint``
    """

    def make_endpoint(self, **kwargs):
        return server.Endpoint(**kwargs)

    def test_create(self):
        """
        Ensure that creating an Endpoint works.
        """
        endpoint = self.make_endpoint()

        self.assertIsNone(endpoint.app)
        self.assertIsNone(endpoint.session_pool)
        self.assertFalse(endpoint.started)
        self.assertIs(endpoint.connection_class, server.Connection)

        # config
        self.assertFalse(endpoint.use_cookie)
        self.assertFalse(endpoint.trace)
        self.assertEqual(endpoint.client_url, server.DEFAULT_CLIENT_URL)
        self.assertEqual(
            endpoint.heartbeat_interval,
            server.HEARTBEAT_INTERVAL
        )
        self.assertEqual(endpoint.disabled_transports, [])

    def test_bind_to_app(self):
        """
        Ensure that options are written only by default
        """
        endpoint = self.make_endpoint()
        app = mock.Mock()

        app.default_options = {}

        endpoint.bind_to_application(app)

        self.assertIs(endpoint.app, app)

    def test_default_options(self):
        """
        Ensure that an overridden option on an endpoint does not get trampled
        when binding to the application
        """
        endpoint = self.make_endpoint(client_url='foobar')
        app = mock.Mock()

        app.default_options = {
            'client_url': 'spam-eggs'
        }

        endpoint.bind_to_application(app)

        self.assertIs(endpoint.app, app)
        self.assertEqual(endpoint.client_url, 'foobar')

    def test_apply_options_transport(self):
        """
        Ensure that applying options for disabled_transports is additive.
        """
        endpoint = self.make_endpoint()

        endpoint.disabled_transports = ['foo', 'bar']

        endpoint.apply_options({
            'disabled_transports': ['foo', 'gak']
        })

        self.assertEqual(endpoint.disabled_transports, ['foo', 'bar', 'gak'])

    def test_apply_options_extra(self):
        """
        Unknown options must raise a ValueError.
        """
        endpoint = self.make_endpoint()

        with self.assertRaises(ValueError) as ctx:
            endpoint.apply_options({
                'foo': 'bar'
            })

        self.assertEqual(
            unicode(ctx.exception),
            u"Unknown config {'foo': 'bar'}"
        )

    @mock.patch('warnings.warn')
    def test_finalise_options(self, mock_warning):
        """
        Ensure that ``finalise_options`` will clean up disabled_transports
        """
        from sockjs_gevent import transports

        endpoint = self.make_endpoint(client_url=None)

        self.assertIsNone(endpoint.client_url)

        patcher = mock.patch.object(transports, 'get_transports')

        with patcher as mock_get_transports:
            mock_get_transports.return_value = ['test']

            endpoint.finalise_options()

        mock_warning.assert_called_with(
            'client_url not supplied, disabling CORS transports',
            RuntimeWarning
        )

        self.assertEqual(endpoint.disabled_transports, ['test'])

    def test_make_connection(self):
        """
        Ensure that ``make_conenction`` does the right thing.
        """
        sentinel = object()
        session = object()
        connection_class = mock.Mock()
        connection_class.return_value = sentinel
        endpoint = self.make_endpoint(connection_class=connection_class)

        result = endpoint.make_connection(session)

        self.assertIs(sentinel, result)
        connection_class.assert_called_with(endpoint, session)

    def test_transport_allowed(self):
        """
        Basic sanity checks for ``Endpoint.transport_allowed``.
        """
        endpoint = self.make_endpoint(disabled_transports=['foo'])

        self.assertTrue(endpoint.transport_allowed('spam'))
        self.assertFalse(endpoint.transport_allowed('foo'))

    def test_start(self):
        """
        Ensure that when the endpoint is started that the session pool is
        started.
        """
        pool_class = mock.Mock()
        session_pool = mock.Mock()

        pool_class.return_value = session_pool

        endpoint = self.make_endpoint()

        endpoint.pool_class = pool_class

        self.assertFalse(endpoint.started)

        endpoint.start()

        self.assertTrue(endpoint.started)

        self.assertIs(endpoint.session_pool, session_pool)
        self.assertTrue(session_pool.start.called)

        # now check that calling start again is a noop
        session_pool.side_effect = RuntimeError

        endpoint.start()

    def test_stop(self):
        """
        Stopping a started endpoint must stop the session pool
        """
        session_pool = mock.Mock()
        endpoint = self.make_endpoint()

        endpoint.start()

        endpoint.session_pool = session_pool

        endpoint.stop()

        self.assertIsNone(endpoint.session_pool)
        session_pool.stop.assert_called_with()
        self.assertFalse(endpoint.started)

    def test_stop_not_started(self):
        """
        Stopping an endpoint that has not been started must be a no-op.
        """
        session_pool = mock.Mock()
        session_pool.stop.side_effect = RuntimeError
        endpoint = self.make_endpoint()

        endpoint.session_pool = session_pool

        endpoint.stop()

    def test_make_session(self):
        """
        Make session should return a session instance.
        """
        endpoint = self.make_endpoint()
        session_class = endpoint.session_class = mock.Mock()

        endpoint.make_session('foobar')

        session_class.assert_called_with('foobar')

    def test_get_session_not_started(self):
        """
        Calling ``get_session`` when the endpoint has not been started must
        raise a RuntimeError.
        """
        endpoint = self.make_endpoint()

        self.assertIsNone(endpoint.session_pool)

        self.assertRaises(RuntimeError, endpoint.get_session, None)

    def test_get_session(self):
        """
        Basic sanity checks for ``get_session``
        """
        endpoint = self.make_endpoint()
        session = object()

        endpoint.session_pool = {
            'foobar': session
        }

        self.assertIs(endpoint.get_session('foobar'), session)
        self.assertIsNone(endpoint.get_session('foo'))

    def test_remove_session(self):
        """
        Basic sanity checks for ``remove_session``.
        """
        endpoint = self.make_endpoint()
        session_pool = endpoint.session_pool = mock.Mock()

        endpoint.remove_session('foobar')

        session_pool.remove.assert_called_with('foobar')

    def test_add_session(self):
        """
        Basic sanity checks for ``add_session``.
        """
        endpoint = self.make_endpoint()
        session_pool = endpoint.session_pool = mock.Mock()
        session = object()

        endpoint.add_session('foobar', session)

        session_pool.add.assert_called_with('foobar', session)

    def test_remove_session_not_started(self):
        """
        Calling ``remove_session`` when the endpoint has not been started must
        raise a RuntimeError.
        """
        endpoint = self.make_endpoint()

        self.assertIsNone(endpoint.session_pool)

        self.assertRaises(RuntimeError, endpoint.remove_session, None)

    def test_get_info(self):
        """
        Sanity check for ``get_info``
        """
        endpoint = self.make_endpoint()
        cookie_needed = endpoint.use_cookie = object()
        heartbeat_interval = endpoint.heartbeat_interval = object()

        randint = mock.Mock()
        randint.return_value = 54

        result = endpoint.get_info(randint)

        self.assertEqual(result, {
            'cookie_needed': cookie_needed,
            'websocket': True,
            'origins': ['*:*'],
            'entropy': 54,
            'server_heartbeat_interval': heartbeat_interval
        })

    def test_get_info_no_websocket(self):
        """
        If websocket is in the disabled_transports list, get_info must return
        ``False`` for the ``websocket`` key.
        """
        endpoint = self.make_endpoint(disabled_transports=['websocket'])

        result = endpoint.get_info()

        self.assertFalse(result['websocket'])


class SessionForTransportTestCase(unittest.TestCase):
    """
    Tests for ``Endpoint.session_for_transport``
    """

    def make_endpoint(self, **kwargs):
        endpoint = server.Endpoint(**kwargs)

        endpoint.start()

        return endpoint

    def test_socket_transport(self):
        """
        A socket transport must not add itself to the endpoint session_pool.
        """
        socket_transport = mock.Mock()
        endpoint = self.make_endpoint()

        socket_transport.socket = True
        session = object()

        @mock.patch.object(endpoint, 'add_session')
        @mock.patch.object(endpoint, 'make_session')
        def do_test(make_session, add_session):
            add_session.side_effect = RuntimeError
            make_session.return_value = session

            return endpoint.get_session_for_transport(None, socket_transport)

        result = do_test()
        self.assertIs(session, result)

    def test_writable_transport_no_session(self):
        """
        A writable transport that does not have a session established must
        return ``None``.
        """
        endpoint = self.make_endpoint()
        writable_transport = mock.Mock()

        writable_transport.socket = False
        writable_transport.writable = True

        with mock.patch.object(endpoint, 'make_session') as mock_session:
            mock_session.side_effect = RuntimeError

            result = endpoint.get_session_for_transport(
                None, writable_transport)

        self.assertIsNone(result)

    def test_readable_transport_add_session(self):
        """
        A readable transport must register the session on the endpoint.
        """
        endpoint = self.make_endpoint()
        readable_transport = mock.Mock()

        readable_transport.socket = False
        readable_transport.writable = False

        session = object()

        @mock.patch.object(endpoint, 'add_session')
        @mock.patch.object(endpoint, 'make_session')
        def do_test(make_session, add_session):
            make_session.return_value = session

            result = endpoint.get_session_for_transport(
                'xyz', readable_transport)

            add_session.assert_called_with('xyz', session)

            return result

        result = do_test()

        self.assertIs(result, session)

    def test_get_existing_session(self):
        """
        Getting an existing session for a transport must not add it to the
        endpoint.
        """
        endpoint = self.make_endpoint()
        readable_transport = mock.Mock()

        readable_transport.socket = False

        session = object()

        @mock.patch.object(endpoint, 'add_session')
        @mock.patch.object(endpoint, 'get_session')
        def do_test(get_session, add_session):
            add_session.side_effect = RuntimeError
            get_session.return_value = session

            return endpoint.get_session_for_transport(
                'xyz', readable_transport)

        result = do_test()

        self.assertIs(result, session)
