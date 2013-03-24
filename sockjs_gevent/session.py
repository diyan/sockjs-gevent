from heapq import heappush, heappop
from datetime import datetime
import time
import weakref

from gevent import queue
import gevent

from . import protocol


# the default number of seconds before a session expires
DEFAULT_EXPIRY = 5
# default heartbeat interval
HEARTBEAT_INTERVAL = 25.0


class SessionError(Exception):
    """
    Base exception class for session related errors
    """


class SessionUnavailable(Exception):
    """
    Raised when an attempt to bind a session to a transport fails because the
    session is in an unusable state.

    :ivar code: Code for error, see ``protocol``.
    :ivar reason: Reason for error, see ``protocol``.
    """

    def __init__(self, code, reason):
        self.code = code
        self.reason = reason


class Session(object):
    """
    Base class for SockJS sessions. Provides a transport independent way to
    queue messages from/to the client.

    Subclasses are expected to overload the add_message and get_messages to
    reflect their storage system.

    :ivar session_id: The unique id of the session.
    :ivar state: What state this session is currently in. Valid values:
        - new: session is new and has not been ``opened`` yet.
        - open: session has been opened and is in a usable state.
        - interrupted: an interaction with the session was not completed
          successfully and is now in an undefined state - messages may have
          been lost.
        - closed: a session has been closed successfully and is now ready for
          garbage collection.
    :ivar expires_at: The timestamp at which this session will expire.
    :ivar ttl_interval: The value to set ``expires_at`` to as a delta to the
        current time.
    :ivar conn: Connection object to which this session is bound. See ``bind``.
        All events will be dispatched to this object.
    :ivar reader: A `weakref.ref` to the transport handler that currently
        holds the lock for reading messages from this session.
    :ivar writer: A `weakref.ref` to the transport handler that currently
        holds the lock for writing messages to this session.
    """

    __slots__ = (
        'session_id',
        'state',
        'ttl_interval',
        'expires_at',
        '_reader',
        '_writer',
        'conn',
        'heartbeat_interval',
    )

    def __init__(self, session_id, ttl_interval=DEFAULT_EXPIRY):
        self.state = 'new'
        self.session_id = session_id

        self.ttl_interval = ttl_interval
        self.set_expiry(ttl_interval)

        self._reader = None
        self._writer = None

        self.conn = None

    def __del__(self):
        try:
            if self.opened:
                self.interrupt()
        except:
            # interrupt() may fail if __init__ didn't complete
            pass

    def bind(self, conn):
        """
        Bind this session to the connection object.
        """
        self.conn = conn

    @property
    def new(self):
        return self.state == 'new'

    @property
    def opened(self):
        return self.state == 'open'

    @property
    def interrupted(self):
        return self.state == 'interrupted'

    @property
    def closed(self):
        return self.state == 'closed'

    def add_messages(self, *msgs):
        """
        Add a list of messages to this session. Order is important, FIFO queue.
        """
        raise NotImplementedError

    def get_messages(self, timeout=None):
        """
        Return a list of messages in the order they were added.

        :param timeout: The number of seconds to wait until giving up. If
            ``None``, this method should block until it can return a message.
        """
        raise NotImplementedError

    def interrupt(self):
        """
        Mark this session as interrupted.
        """
        self.close('interrupted')

    def open(self):
        """
        Ready this session for accepting/dispatching messages.
        """
        if not self.new:
            raise RuntimeError('Session cannot be opened (state=%s' % (
                self.state,))

        self.state = 'open'
        assert self.conn

        self.conn.session_opened()

    def close(self, reason='closed'):
        """
        Close this session.

        :param reason: The final state of this session. See ``state`` for valid
            values.
        """
        self.state = reason

        if self.conn:
            # only dispatch the close event if we were previously opened
            try:
                self.conn.session_closed()
            finally:
                self.conn = None

    def dispatch(self, *msgs):
        """
        Dispatch a message to the bound connection object

        :param msg: The message. This can be of any type/value. It is up to the
            conn object to validate its content.
        """
        if not self.conn:
            return

        for msg in msgs:
            self.conn.on_message(msg)

    def touch(self):
        """
        Bump the TTL of the session.
        """
        self.expires_at = time.time() + self.ttl_interval

    def set_expiry(self, expires):
        """
        Possible values for expires and its effects:
         - None/0: session will never expire
         - int/long: seconds until the session expires
         - datetime: absolute date/time that the session will expire.
        """
        if not expires:
            self.expires_at = 0

            return

        if isinstance(expires, datetime):
            expires = time.mktime(expires.timetuple())

        if expires < 1e9:
            # delta
            expires += time.time()

        self.expires_at = expires

    def has_expired(self, now=None):
        """
        Whether this session has expired.
        """
        if self.closed or self.interrupted:
            return True

        if not self.expires_at:
            return False

        return self.expires_at <= (now or time.time())

    @property
    def read_owner(self):
        if not self._reader:
            return

        return self._reader()

    @read_owner.setter
    def read_owner(self, reader):
        if reader:
            reader = weakref.ref(reader)

        self._reader = reader

    @property
    def write_owner(self):
        if not self._writer:
            return

        return self._writer()

    @write_owner.setter
    def write_owner(self, writer):
        if writer:
            writer = weakref.ref(writer)

        self._writer = writer

    def _make_owner(self, owner, read, write, orig=None):
        orig_read_owner = self.read_owner
        orig_write_owner = self.write_owner
        orig_owner = orig or owner

        try:
            if read:
                read_owner = orig_read_owner

                if read_owner and read_owner is orig_owner:
                    read_owner = None

                if read_owner:
                    raise SessionUnavailable(*protocol.CONN_ALREADY_OPEN)

                self.read_owner = owner

            if write:
                write_owner = orig_write_owner

                if write_owner and write_owner is orig_owner:
                    write_owner = None

                if write_owner:
                    raise SessionUnavailable(*protocol.CONN_ALREADY_OPEN)

                self.write_owner = owner
        except Exception, e:
            self.read_owner = orig_read_owner
            self.write_owner = orig_write_owner

            if isinstance(e, SessionUnavailable):
                return False

            raise

        return True

    def lock(self, owner, read, write):
        """
        Forces the lock on the channel.

        :param owner: The new owner on the lock, if there is already an owner
            then ``SessionUnavailable`` will be raised.
        :param read: Whether the read channel is to be locked.
        :param write: Whether the write channel is to be locked.
        """
        if self.interrupted:
            raise SessionUnavailable(*protocol.CONN_INTERRUPTED)

        if self.closed:
            raise SessionUnavailable(*protocol.CONN_CLOSED)

        if not self._make_owner(owner, read, write):
            raise SessionUnavailable(*protocol.CONN_ALREADY_OPEN)

    def unlock(self, owner, read, write):
        """
        Unlock the respective channels.
        """
        self._make_owner(None, read, write, owner)

    def run_heartbeat(self):
        while True:
            gevent.sleep(self.heartbeat_interval)

            reader = self.read_owner

            if not reader or not self.open:
                break

            try:
                reader.send_heartbeat()
            except Exception:
                break

    def start_heartbeat(self):
        return gevent.spawn(self.run_heartbeat)

    def __repr__(self):
        locks = ''

        if self.read_owner:
            locks += 'r'

        if self.write_owner:
            locks += 'w'

        return '<%s %s(%s) %s at 0x%x>' % (
            self.__class__.__name__,
            self.state,
            locks,
            self.session_id,
            id(self)
        )


class MemorySession(Session):
    """
    In memory session with a ``gevent.pool.Queue`` as the message store.
    """

    __slots__ = ('queue',)

    def __init__(self, *args, **kwargs):
        super(MemorySession, self).__init__(*args, **kwargs)

        self.queue = queue.Queue()

    def add_messages(self, *msgs):
        if not msgs:
            return

        for msg in msgs:
            self.queue.put_nowait(msg)

        self.touch()

    def get_messages(self, timeout=None):
        self.touch()

        messages = []

        # get all messages immediately pending in the queue
        while not self.queue.empty():
            try:
                msg = self.queue.get_nowait()
            except queue.Empty:
                break

            messages.append(msg)

        # there were no messages pending in the queue, let's wait
        if not messages:
            try:
                messages.append(self.queue.get(timeout=timeout))
            except queue.Empty:
                pass

        return messages


class Pool(object):
    """
    A garbage collected Session Pool.
    """

    def __init__(self, gc_cycle=10.0):
        self.sessions = {}
        self.cycles = {}

        self.pool = []
        self.gcthread = gevent.Greenlet(self._gc_sessions)

        self.gc_cycle = gc_cycle
        self.stopping = False

    def __str__(self):
        return str(self.sessions)

    def __del__(self):
        try:
            self.stop()
        except:
            pass

    def start(self):
        """
        Start the session pool garbage collector. This is broken out into a
        separate function to give you more granular control on the context this
        thread is spawned in.
        """
        if not self.gcthread.started:
            self.gcthread.start()

    def stop(self):
        """
        Manually expire all sessions in the pool.
        """
        if self.stopping:
            return

        self.stopping = True

        self.gcthread.kill()
        self.drain()

    def drain(self):
        while self.pool:
            last_checked, session = heappop(self.pool)

            if session.open:
                session.interrupt()

    def _gc_sessions(self):
        while True:
            gevent.sleep(self.gc_cycle)
            self.gc()

    def add(self, session, time_func=time.time):
        if self.stopping:
            raise RuntimeError('SessionPool is stopping')

        if session.session_id in self.sessions:
            raise RuntimeError('Adding already existing session %r' % (
                session.session_id,))

        if not session.new:
            raise RuntimeError('Session has already expired')

        current_time = self.cycles[session] = time_func()
        self.sessions[session.session_id] = session

        heappush(self.pool, (current_time, session))

    def get(self, session_id):
        """
        Get active sessions by their session id.
        """
        return self.sessions.get(session_id, None)

    def remove(self, session_id):
        session = self.sessions.pop(session_id, None)

        if not session:
            return False

        current_time = self.cycles.pop(session, None)

        if current_time:
            try:
                self.pool.remove((current_time, session))
            except ValueError:
                pass

        if session.open:
            try:
                session.interrupt()
            except Exception:
                pass

        return True

    def gc(self, time_func=time.time):
        """
        Rearrange the heap flagging active sessions with the id of this
        collection iteration. This data-structure is time-independent so we
        sessions can be added to and from without the need to lock the pool.
        """
        if not self.pool:
            return

        current_time = time_func()

        while self.pool:
            session = self.pool[0][1]
            cycle = self.cycles[session]

            if cycle >= current_time:
                # we've looped through all sessions
                break

            last_checked, session = heappop(self.pool)

            if session.has_expired(current_time):
                # Session is to be GC'd immediately
                self.remove(session.session_id)

                continue

            # Flag the session with the id of this GC cycle
            self.cycles[session] = current_time
            heappush(self.pool, (current_time, session))
