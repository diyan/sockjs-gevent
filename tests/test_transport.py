try:
    import unittest2 as unittest
except ImportError:
    import unittest

import mock

from sockjs_gevent import transport


class StopRequest(Exception):
    """
    This is to signal that the test must stop execution. This does not mean the
    test failed.
    """


class HandlerTestCase(unittest.TestCase):
    """
    Tests for the request handling flow.
    """

    def make_handler(self):
        handler = mock.Mock()
        handler.handle_options.return_value = False

        return handler

    def make_transport(self, handler, session=None, environ=None, klass=None,
                       **options):
        if not klass:
            class TestTransport(transport.BaseTransport):
                pass

            klass = TestTransport

        for name, value in options.iteritems():
            setattr(klass, name, value)

        session = session or mock.Mock()
        handler = handler or mock.Mock()
        environ = environ or {}

        return klass(session, handler, environ)

    def test_create(self):
        """
        Ensure that the init args are preserved.
        """
        session = object()
        handler = object()
        environ = object()

        tport = self.make_transport(handler, session, environ)

        self.assertIs(tport.session, session)
        self.assertIs(tport.handler, handler)
        self.assertIs(tport.environ, environ)

    def test_handle_options(self):
        """
        Ensure that OPTIONS requests are handled appropriately.
        """
        handler = mock.Mock()

        tport = self.make_transport(handler=handler, http_options=['GET'])

        tport.handle()

        handler.handle_options.assert_called_with('GET')

    def test_prepare_request(self):
        """
        Ensure that prepare_request is called when handling a request.
        """
        transport_mock = mock.Mock()

        class MyTransport(transport.BaseTransport):
            def prepare_request(self):
                transport_mock.prepare_request()

            def do_open(self):
                raise StopRequest

        handler = self.make_handler()
        tport = self.make_transport(handler, klass=MyTransport)

        self.assertRaises(StopRequest, tport.handle)

        transport_mock.prepare_request.assert_called_with()

    def test_socket_property(self):
        """
        Test sanity for the ``socket`` property
        """
        handler = mock.Mock()

        def make_transport(readable, writable):
            tport = self.make_transport(
                handler,
                readable=readable,
                writable=writable
            )

            return tport.socket

        self.assertFalse(make_transport(False, False))
        self.assertFalse(make_transport(False, True))
        self.assertFalse(make_transport(True, False))
        self.assertTrue(make_transport(True, True))

    def test_fail_to_acquire_session(self):
        """
        If ``session.SessionUnavailable`` is raised when acquiring a session,
        a response must be set.
        """
        from sockjs_gevent.session import SessionUnavailable

        handler = self.make_handler()
        session = mock.Mock()
        tport = self.make_transport(handler, session)

        session.lock.side_effect = SessionUnavailable(1234, 'DIE')

        result = tport.acquire_session()

        self.assertFalse(result)
        handler.start_response.assert_called_with()

    def test_acquire_session(self):
        """
        Acquiring a session must return ``True``.
        """
        handler = self.make_handler()
        session = mock.Mock()
        readable = object()
        writable = object()

        tport = self.make_transport(
            handler,
            session,
            readable=readable,
            writable=writable
        )

        result = tport.acquire_session()

        self.assertTrue(result)
        session.lock.assert_called_with(tport, readable, writable)

    def test_handle_fail_acquire(self):
        """
        Ensure that if fail to acquire, the request is short circuited
        """
        from sockjs_gevent.session import SessionUnavailable

        class MyTransport(transport.BaseTransport):
            def do_open(self):
                raise RuntimeError

        handler = self.make_handler()
        session = mock.Mock()
        tport = self.make_transport(handler, session, klass=MyTransport)

        session.lock.side_effect = SessionUnavailable(1234, 'DIE')

        tport.handle()

    def test_new_session(self):
        """
        A new session must call session.open
        """
        class MyTransport(transport.BaseTransport):
            def handle_request(self):
                raise StopRequest

        handler = self.make_handler()
        session = mock.Mock()
        tport = self.make_transport(handler, session, klass=MyTransport)

        session.new = True

        self.assertRaises(StopRequest, tport.handle)

        session.open.assert_called_with()

    def test_not_new_session(self):
        """
        If a session is not new, open must NOT be called.
        """
        class MyTransport(transport.BaseTransport):
            def handle_request(self):
                raise StopRequest

        handler = self.make_handler()
        session = mock.Mock()
        tport = self.make_transport(handler, session, klass=MyTransport)

        session.new = False

        self.assertRaises(StopRequest, tport.handle)

        session.open.assert_not_called_with()

    def test_release_session(self):
        """
        A session must be released after handling the request
        """
        handler = self.make_handler()
        handler.released = False

        class MyTransport(transport.BaseTransport):
            def handle_request(self):
                pass

            def release_session(self):
                handler.released = True

        tport = self.make_transport(handler, klass=MyTransport)

        tport.handle()

        self.assertTrue(handler.released)

    def test_release_session_on_error(self):
        """
        A session must be released after handling the request
        """
        handler = self.make_handler()
        handler.released = False

        class MyTransport(transport.BaseTransport):
            def handle_request(self):
                raise RuntimeError

            def release_session(self):
                handler.released = True

        tport = self.make_transport(handler, klass=MyTransport)

        self.assertRaises(RuntimeError, tport.handle)

        self.assertTrue(handler.released)

    def test_finalise_request(self):
        """
        Ensure that if there are no errors, finalize_request is called.
        """
        handler = self.make_handler()
        handler.finalized = False

        class MyTransport(transport.BaseTransport):
            def handle_request(self):
                pass

            def finalize_request(self):
                handler.finalized = True

        tport = self.make_transport(handler, klass=MyTransport)

        tport.handle()

        self.assertTrue(handler.finalized)

    def test_finalise_request_with_error(self):
        """
        If ``handle_request`` dies with an exception, ``finalize_request`` must
        NOT be called.
        """
        handler = self.make_handler()
        handler.finalized = False

        class MyTransport(transport.BaseTransport):
            def handle_request(self):
                raise RuntimeError

            def finalize_request(self):
                handler.finalized = True

        tport = self.make_transport(handler, klass=MyTransport)

        self.assertRaises(RuntimeError, tport.handle)

        self.assertFalse(handler.finalized)
