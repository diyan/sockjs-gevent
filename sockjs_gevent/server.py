import warnings
import random

from gevent import pywsgi

from . import session, transports

# this url is used by SockJS-node, maintained by the creator of SockJS
DEFAULT_CLIENT_URL = 'https://d1fxtkz8shb9d2.cloudfront.net/sockjs-0.3.min.js'
HEARTBEAT_INTERVAL = 25.0  # seconds


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
    :ivar started: Whether this application has started.
    :ivar default_options: A key -> value mapping of default options for the
        application. Can be overridden by the Endpoint.
    """

    session_class = session.MemorySession

    def __init__(self, endpoints=None, **options):
        """
        Builds a SockJS Application object.

        :param endpoints: A dict of name -> Endpoint instances. The key of the
            dict will be used in the path of the SockJS url.
        """
        self.endpoints = {}
        self.started = False

        self.default_options = DEFAULT_OPTIONS.copy()
        self.default_options.update(options)

        if endpoints:
            for name, endpoint in endpoints.iteritems():
                self.add_endpoint(name, endpoint)

    def __del__(self):
        """
        MAY be called when this object is garbage collected.
        """
        super(Application, self).__del__()

        try:
            self.stop()
        except:
            pass

    def start(self):
        """
        Start the server.
        """
        if self.started:
            return

        self.started = True

        for endpoint in self.endpoints.values():
            endpoint.start()

    def stop(self, timeout=None):
        """
        Shutdown the application, block to inform the endpoints that they are
        closing.
        """
        for endpoint in self.endpoints.values():
            endpoint.stop()

        self.endpoints = {}

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

        if self.started:
            endpoint.start()

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

        self.apply_options(options)

    def bind_to_application(self, app):
        """
        Bind this endpoint to a SockJS Application object.
        """
        self.app = app

        self.apply_options(app.default_options)

    def init_options(self):
        self.apply_options(DEFAULT_OPTIONS)

    def apply_options(self, orig_options):
        # copied so checks can be made for unused options
        options = orig_options.copy()

        self.use_cookie = options.pop('use_cookie')
        self.client_url = options.pop('client_url')
        self.trace = options.pop('trace')
        self.heartbeat_interval = options.pop('heartbeat_interval')

        # disabled transports is a special case in that values are additive
        disabled_transports = options.pop('disabled_transports')

        if disabled_transports:
            if not self.disabled_transports:
                self.disabled_transports = []

            self.disabled_transports.extend(disabled_transports)

    def finalise_options(self):
        if not self.client_url:
            warnings.warning(RuntimeWarning, 'client_url not supplied, '
                             'disabling CORS transports')
            for label in transports.get_transports(cors=True):
                self.disabled_transports.apppend(label)

        self.disabled_transports = list(set(self.disabled_transports or []))

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

    def stop(self, timeout=None):
        """
        Called when this endpoint is stopping serving requests.
        """
        self.session_pool.stop()
        self.session_pool = None

        self.started = False

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


class WSGIHandler(pywsgi.WSGIHandler, wsgi.RequestHandler):
    @property
    def stream(self):
        return 
    def run_application(self):
        wsgi.route_request(self.server, self.environ, self)




class Server(pywsgi.WSGIServer, Application):
    """
    """


    def __init__(self, listener, endpoints=None, options=None, **kwargs):
        super(pywsgi.WSGIServer, self).__init__(listener, **kwargs)

        super(Application, self).__init__(endpoints, **(options or {}))
