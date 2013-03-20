import warnings
import random

from . import session, transports


HEARTBEAT_INTERVAL = 25.0  # seconds


class SockJSApplication(object):
    """
    Base logic for doing all things at the application layer
    """

    session_class = session.MemorySession

    def __init__(self, endpoints=None):
        """
        Builds a SockJS Application object.

        :param endpoints: A dict of name -> Endpoint instances. The key of the
            dict will be used in the path of the SockJS url.
        """
        self.endpoints = {}
        self.started = False

        if endpoints:
            for name, endpoint in endpoints.iteritems():
                self.add_endpoint(name, endpoint)

    def start(self):
        """
        Start the server.
        """
        if self.started:
            return

        self.started = True

        self.session_pool.start()

        for endpoint in self.endpoints.values():
            endpoint.start()

    def stop(self, timeout=None):
        """
        Shutdown the application, block to inform the sessions that they are
        closing.
        """
        self.session_pool.stop()

        for endpoint in self.endpoints.values():
            endpoint.stop()

    def add_endpoint(self, name, endpoint):
        name = name.encode('punycode')

        if name in self.endpoints:
            raise NameError('%r endpoint already exists' % (name,))

        self.endpoints[name] = endpoint

        endpoint.bind(self)

        if self.started:
            endpoint.start()

    def remove_endpoint(self, name):
        name = name.encode('punycode')
        endpoint = self.endpoints.pop(name, None)

        if not endpoint:
            raise NameError('%r is not a valid endpoint' % (name,))

        endpoint.stop()

        return endpoint

    def get_endpoint(self, name):
        name = name.encode('punycode')

        return self.endpoints.get(name, None)

    def get_session(self, session_id, create):
        session = self.session_pool.get(session_id)

        if not session and create:
            session = self.session_backend(
                session_id,
                heartbeat_interval=self.heartbeat_interval)
            self.session_pool.add(session)

        return session

    def remove_session(self, session_id):
        self.session_pool.remove(session_id)


class Connection(object):
    """
    Binds a SockJS session to an endpoint
    """

    __slots__ = (
        'endpoint',
        'session',
    )

    def __init__(self, endpoint, session):
        self.endpoint = endpoint
        self.session = session

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


class Endpoint(object):
    """
    Represents a SockJS application bound to an endpoint e.g. /echo

    Provides configurable options and builds connection objects which are bound
    to each Session.
    """

    def __init__(self, connection_class=Connection, use_cookie=False,
                 client_url=None, heartbeat_interval=HEARTBEAT_INTERVAL,
                 trace=False, disabled_transports=None):
        """
        Builds an endpoint.

        :param connection_class: Creates a new Connection instance per socket.
        :param disabled_transports: A list of transports that are disabled for
            this endpoint. See transport.transport_types for a list of valid
            values.
        :param use_cookie: Whether to use the cookie to support sticky sessions
            when behind load balancers like HAProxy.
        :param client_url: The url of the SockJS client, used when a transport
            does not support CORS (cross domain communication).
        """
        self.connection_class = connection_class
        self.use_cookie = use_cookie
        self.disabled_transports = list(disabled_transports or ())
        self.heartbeat_interval = heartbeat_interval
        self.client_url = client_url
        self.trace = trace

        if not self.client_url:
            warnings.warning(RuntimeWarning, 'client_url not supplied, '
                             'disabling CORS transports')
            for label in transports.get_transports(cors=True):
                self.disabled_transports.apppend(label)

    def bind(self, app):
        """
        Bind this endpoint to a SockJS Application object.
        """
        self.app = app

    def make_connection(self, session):
        return self.connection_class(self, session)

    def transport_allowed(self, transport):
        return transport not in self.disabled_transports

    def start(self):
        """
        Called when this endpoint is first activated.

        Used to do application level set up.
        """

    def stop(self):
        """
        Called when this endpoint is stopping serving requests.
        """
        self.app = None

    def get_info(self):
        """
        :returns: The data necessary to fulfill an info request
        """
        entropy = random.randint(1, 2 ** 32)

        return {
            'cookie_needed': self.use_cookie,
            'websocket': self.transport_allowed('websocket'),
            'origins': ['*:*'],
            'entropy': entropy,
            'server_heartbeat_interval': self.heartbeat_interval
        }
