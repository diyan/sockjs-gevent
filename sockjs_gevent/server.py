from gevent import pywsgi

from . import session, handler


class Server(pywsgi.WSGIServer):
    """
    The base SockJS server.
    """

    session_backend = session.MemorySession
    handler_class = handler.Handler

    heartbeat_interval = 25.0

    # required to support pywsgi WSGI interface
    application = None

    def __init__(self, listener, endpoints, **kwargs):
        """
        Initialize the SockJS server
        """
        self.trace = kwargs.pop('trace', False)
        self.endpoints = {}
        self.session_pool = session.Pool()
        self.heartbeat_interval = kwargs.pop('heartbeat_interval',
            self.heartbeat_interval)

        super(Server, self).__init__(listener, application=None, **kwargs)

        for name, endpoint in endpoints.iteritems():
            self.add_endpoint(name, endpoint)

    def add_endpoint(self, name, endpoint):
        if name in self.endpoints:
            raise NameError('%r endpoint already exists' % (name,))

        self.endpoints[name] = endpoint

        endpoint.server = self

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

    def start(self):
        """
        Start the server.
        """
        self.session_pool.start()

        for endpoint in self.endpoints.values():
            endpoint.start()

        return super(Server, self).start()

    def stop(self, timeout=None):
        """
        Shutdown the server, block to inform the sessions that they are closing.
        """
        super(Server, self).stop(timeout=timeout)

        for endpoint in self.endpoints.values():
            endpoint.stop()

        self.session_pool.stop()

    def get_session(self, session_id, create):
        session = self.session_pool.get(session_id)

        if not session and create:
            session = self.session_backend(session_id,
                heartbeat_interval=self.heartbeat_interval)
            self.session_pool.add(session)

        return session

    def remove_session(self, session_id):
        self.session_pool.remove(session_id)


class Connection(object):
    """
    Binds a SockJS session to an endpoint
    """

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
        simple string or a dict etc. It is up to subclasses to handle validation
        of the message.
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

        self.session.close()
        self.session = None


class Endpoint(object):
    """
    Represents a SockJS application bound to an endpoint e.g. /echo

    Provides configurable options and builds connection objects which are bound
    to each Session.
    """

    def __init__(self, connection_class=Connection, disabled_transports=None,
                 use_cookie=False, sockjs_url='http'):
        """
        Builds an endpoint.

        :param connection_class: Creates a new Connection instance per socket.
        :param disabled_transports: A list of transports that are disabled for
            this endpoint. See transport.transport_types for a list of valid
            values.
        :param use_cookie: Whether to use the cookie to support sticky sessions
            when behind load balancers like HAProxy.
        :param sockjs_url: The url of the SockJS client, used when a transport
            does not support CORS (cross domain communication).
        """
        self.connection_class = connection_class
        self.disabled_transports = tuple(disabled_transports or ())
        self.use_cookie = use_cookie
        self.sockjs_url = sockjs_url

    def make_connection(self, handler, session):
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
