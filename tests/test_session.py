try:
    import unittest2 as unittest
except ImportError:
    import unittest

import mock

from sockjs_gevent import session


class PoolTestCase(unittest.TestCase):
    """
    Tests for `session.Pool`
    """

    def make_pool(self, *args, **kwargs):
        return session.Pool(*args, **kwargs)

    def make_session(self, session_id):
        return session.MemorySession(session_id)

    def test_add_session(self):
        """
        Ensure that adding a session works correctly.
        """
        pool = self.make_pool()
        foo = self.make_session('a')

        pool.add(foo)

        self.assertEqual(pool.sessions, {'a': foo})
        self.assertEqual(pool.pool, [foo])
        self.assertEqual(pool.cycles, {foo: None})

    def test_already_added(self):
        """
        Ensure that the pool will only accept unique sessions.
        """
        pool = self.make_pool()

        # note the same session id
        foo = self.make_session('a')
        bar = self.make_session('a')

        pool.add(foo)
        self.assertRaises(RuntimeError, pool.add, bar)

    def test_add_closed(self):
        """
        A non-new session must be rejected.
        """
        pool = self.make_pool()
        foo = self.make_session('a')

        self.assertTrue(foo.new)
        foo.close()
        self.assertFalse(foo.new)

        self.assertRaises(RuntimeError, pool.add, foo)

    def test_remove_missing(self):
        """
        Attempting to remove a session from a pool that does not contain it
        should fail gracefully.
        """
        pool = self.make_pool()
        foo = self.make_session('a')

        self.assertNotIn(foo, pool.pool)

        self.assertFalse(pool.remove('a'))

    def test_remove(self):
        """
        Removing a session from a pool must clean up correctly.
        """
        pool = self.make_pool()
        foo = self.make_session('a')

        pool.add(foo)

        self.assertTrue(pool.remove('a'))

        self.assertEqual(pool.pool, [])
        self.assertEqual(pool.sessions, {})
        self.assertEqual(pool.cycles, {})

    def test_remove_open_session(self):
        """
        If the pool removes an open session, ensure it is interrupted.
        """
        session = mock.Mock()
        session.open = True
        session.session_id = 'foo'

        pool = self.make_pool()

        pool.add(session)

        pool.remove('foo')

        self.assertTrue(session.interrupt.called)

