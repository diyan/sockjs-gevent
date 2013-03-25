import warnings
import random

from gevent import pywsgi

from . import session, transport, handler

# this url is used by SockJS-node, maintained by the creator of SockJS
DEFAULT_CLIENT_URL = 'https://d1fxtkz8shb9d2.cloudfront.net/sockjs-0.3.min.js'
HEARTBEAT_INTERVAL = 25.0  # seconds
MAX_ENTROPY = 2 ** 32


DEFAULT_OPTIONS = {
    'use_cookie': False,
    'trace': False,
    'client_url': DEFAULT_CLIENT_URL,
    'disabled_transports': None,
    'heartbeat_interval': HEARTBEAT_INTERVAL
}


class Application(object):
    """
    The root application object. Maintains a group of ``Endpoint`` instances.

    :ivar endpoints: A mapping of name -> Endpoint instances. The name is used
        as part of the SockJS url routing.
    :ivar default_options: A key -> value mapping of default options for the
        application. Can be overridden by the Endpoint.
    """

    def __init__(self, endpoints=None, **options):
        """
        Builds a SockJS Application object.

        :param endpoints: A dict of name -> Endpoint instances. The key of the
            dict will be used in the path of the SockJS url.
        """
        self.endpoints = {}

        self.default_options = DEFAULT_OPTIONS.copy()
        self.default_options.update(options)

        if endpoints:
            for name, endpoint in endpoints.iteritems():
                self.add_endpoint(name, endpoint)

    def __del__(self):
        """
        MAY be called when this object is garbage collected.
        """
        try:
            self.stop()
        except:
            pass

    def start(self):
        """
        Start the server.
        """
        for endpoint in self.endpoints.values():
            endpoint.start()

    def stop(self):
        """
        Shutdown the application, block to inform the endpoints that they are
        closing.
        """
        for endpoint in self.endpoints.values():
            endpoint.stop()

    def add_endpoint(self, name, endpoint):
        """
        Add a SockJS Endpoint to this application.

        :param name: The name of the endpoint. This will be used as part of the
            SockJS URL routing.
        :param endpoint: The ``Endpoint`` instance
        """
        if name in self.endpoints:
            raise NameError('%r endpoint already exists' % (name,))

        self.endpoints[name] = endpoint

        endpoint.bind_to_application(self)

    def remove_endpoint(self, name):
        endpoint = self.endpoints.pop(name, None)

        if not endpoint:
            raise NameError('%r is not a valid endpoint' % (name,))

        endpoint.stop()

        return endpoint

    def get_endpoint(self, name):
        return self.endpoints.get(name, None)


class Connection(object):
    """
    A connection object is created for each session. A full SockJS session has
    an incoming and an outgoing transport. For fully duplex connections, they
    are the same.
    """

    __slots__ = (
        'endpoint',
        'session',
    )

    def __init__(self, endpoint, session):
        """
        Build
        """
        self.endpoint = endpoint
        self.session = session

    def __del__(self):
        """
        MAY be called when this object is garbage collected.
        """
        try:
            self.close()
        except:
            pass

    def on_open(self):
        """
        Called when the SockJS session is first opened.
        """

    def on_message(self, message):
        """
        Called when a message has been decoded from the SockJS session.

        The message is what was sent from the SockJS client, this could be a
        simple string or a dict etc. It is up to subclasses to handle
        validation of the message.
        """

    def on_close(self):
        """
        Called when the SockJS session is closed.
        """

    def send(self, message):
        """
        Send a message to the endpoint.

        The message must be JSON encodable.
        """
        if not self.session:
            return

        self.session.add_messages(message)

    def close(self):
        """
        Close this session
        """
        if not self.session:
            return

        # prevent a circular reference issue
        s = self.session
        self.session = None

        s.close()

        try:
            self.endpoint.connection_closed(self)
        finally:
            self.endpoint = None


class Endpoint(object):
    """
    Represents a SockJS application bound to an endpoint e.g. /echo

    Provides configurable options and builds connection objects which are bound
    to each Session.

    Builds and receives events from ``Connection`` objects.
    """

    pool_class = session.Pool
    session_class = session.MemorySession

    def __init__(self, connection_class=Connection, **options):
        """
        Builds an endpoint.

        :param connection_class: Creates a new Connection instance per socket.
        :param options: Specific options to this endpoint. All options are
            inherited from the application object.
        """
        self.connection_class = connection_class
        self.app = None
        self.started = False
        self.session_pool = None

        self.init_options()

        self.apply_options(options, _init=True)

    def bind_to_application(self, app):
        """
        Bind this endpoint to a SockJS Application object.
        """
        self.app = app

        self.apply_options(app.default_options)

    def init_options(self):
        self.disabled_transports = []
        self.apply_options(DEFAULT_OPTIONS, _init=True)

    def apply_options(self, orig_options, _init=False):
        # copied so checks can be made for unused options
        options = orig_options.copy()
        sentinel = object()

        def get_option(key):
            value = options.pop(key, sentinel)

            if not _init and hasattr(self, key):
                return

            if value is sentinel:
                return

            setattr(self, key, value)

        get_option('use_cookie')
        get_option('client_url')
        get_option('trace')
        get_option('heartbeat_interval')

        # disabled transports is a special case in that values are additive
        disabled_transports = options.pop('disabled_transports', None)

        if disabled_transports:
            if not self.disabled_transports:
                self.disabled_transports = []

            for transport_type in disabled_transports:
                if transport_type not in self.disabled_transports:
                    self.disabled_transports.append(transport_type)

        if options:
            raise ValueError('Unknown config %r' % (options,))

    def finalise_options(self):
        self.disabled_transports = list(set(self.disabled_transports or []))

        if not self.client_url:
            message = 'client_url not supplied, disabling CORS transports'
            warnings.warn(message, RuntimeWarning)

            for label in transport.get_transports(cors=True):
                self.disabled_transports.append(label)

    def make_connection(self, session):
        return self.connection_class(self, session)

    def transport_allowed(self, transport):
        return transport not in self.disabled_transports

    def start(self):
        """
        Called when this endpoint is first activated.

        Used to do application level set up.
        """
        if self.started:
            return

        if not self.session_pool:
            self.session_pool = self.pool_class()

        self.session_pool.start()
        self.started = True

    def stop(self, timeout=None):
        """
        Called when this endpoint is stopping serving requests.
        """
        if not self.started:
            return

        self.session_pool.stop()
        self.session_pool = None

        self.started = False

    def make_session(self, session_id):
        return self.session_class(session_id)

    def get_session(self, session_id):
        if not self.session_pool:
            raise RuntimeError(
                'Tried to get a session when the endppoint was not started')

        return self.session_pool.get(session_id)

    def add_session(self, session_id, session):
        """
        Add a session to this endpoints session pool
        """
        self.session_pool.add(session_id, session)

    def remove_session(self, session_id):
        if not self.session_pool:
            raise RuntimeError(
                'Tried to get a session when the endppoint was not started')

        self.session_pool.remove(session_id)

    def get_session_for_transport(self, session_id, transport):
        """
        Return a session based on the supplied session_id and transport.

        There is some nuance to this, SockJS allows multiple socket connections
        to reuse the same session_id concurrently. They are all handled as
        valid sessions.

        :param session_id: The identifier of the session.
        :param transport: A transport interface.
        :returns: A session object to be used for this transport. If ``None``
            is returned, the connection must be aborted.
        """
        if transport.socket:
            # socket transport sessions do not get added to the session pool
            return self.make_session(session_id)

        session = self.get_session(session_id)

        if session:
            return session

        if transport.writable:
            # A writable transport is being requested but there is no existing
            # session. A session can only be set up by a readable transport.
            return

        session = self.make_session(session_id)
        self.add_session(session_id, session)

        return session

    def get_info(self, randint=random.randint):
        """
        :returns: The data necessary to fulfill an info request
        """
        entropy = randint(1, MAX_ENTROPY)

        return {
            'cookie_needed': self.use_cookie,
            'websocket': self.transport_allowed('websocket'),
            'origins': ['*:*'],
            'entropy': entropy,
            'server_heartbeat_interval': self.heartbeat_interval
        }


class Server(pywsgi.WSGIServer, Application):
    """
    """

    def __init__(self, listener, endpoints=None, options=None, **kwargs):
        kwargs.setdefault('handler_class', handler.Handler)

        pywsgi.WSGIServer.__init__(self, listener, **kwargs)
        Application.__init__(self, endpoints, **(options or {}))

    def add_endpoint(self, name, endpoint):
        super(Server, self).add_endpoint(name, endpoint)

        if self.started:
            endpoint.start()
