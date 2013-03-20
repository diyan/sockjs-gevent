import hashlib
import re
import socket
import uuid

from . import transports, util, server


IFRAME_PATH_RE = re.compile(r'iframe([0-9-.a-z_]*)\.html')

IFRAME_HTML = """
<!DOCTYPE html>
<html>
<head>
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
  <script>
    document.domain = document.domain;
    _sockjs_onload = function(){SockJS.bootstrap_iframe();};
  </script>
  <script src="%s"></script>
</head>
<body>
  <h2>Don't panic!</h2>
  <p>This is a SockJS hidden iframe. It's used for cross domain magic.</p>
</body>
</html>
""".strip()


class RequestHandler(util.BaseHandler):

    def __init__(self, app, environ, start_response):
        super(RequestHandler, self).__init__(environ, start_response)

        self.app = app

    def do_greeting(self):
        """
        """
        if self.handle_options('GET'):
            return

        self.write_text('Welcome to SockJS!\n', cache=True)

    def do_iframe(self, endpoint):
        if self.handle_options('GET'):
            return

        content = IFRAME_HTML % (endpoint.client_url,)
        our_etag = hashlib.md5(content).hexdigest()

        cached = self.environ.get('HTTP_IF_NONE_MATCH', None)

        if cached and cached == our_etag:
            self.not_modified()

            return

        self.write_html(content, cache=True, cors=True, headers=[
            ('ETag', our_etag)
        ])

    def do_info(self, endpoint):
        """
        Used to check server capabilities (websocket support, cookies) and to
        get the value of "origin" setting (currently not used).
        """
        if self.handle_options('GET'):
            return

        info = endpoint.get_info()

        self.write_js(info, cors=True, cache=False)

    def do_transport(self, server_id, session_id, transport):
        # validate the transport value
        transport_cls = transports.get_transport_class(transport)

        if not transport_cls:
            self.not_found()

            return

        # check if the transport is disabled for this endpoint
        if not self.app.transport_allowed(transport):
            self.not_found()

            return

        # only create sessions if the transport being used is readable
        create = transport_cls.readable
        # basic transport validation is out the way (the quick stuff)
        # lets set up the session
        session = self.server.get_session(session_id, create)

        if not session:
            # on a writable transport and there is no session
            self.not_found()

            return

        if session.new:
            conn = self.endpoint.make_connection(self, session)

            session.bind(conn)

        transport_handler = transport_cls(session, self)
        e = None

        try:
            raw_request_data = self.wsgi_input.readline()

            transport_handler(self, raw_request_data)
        except Exception, e:
            session.interrupt()

            if not isinstance(e, socket.error):
                raise
        finally:
            if transport_handler.is_socket:
                if e:
                    raise

                self.server.remove_session(session.session_id)


class SockJSWSGIApplication(server.SockJSApplication):
    """
    The SockJS WSGI application
    """

    def __call__(self, environ, start_response):
        handler = RequestHandler(self, environ, start_response)

        self.handle_request(handler, environ, start_response)

        return []

    def handle_request(self, handler, environ, start_response):
        # first get the endpoint name from the path
        path_info = environ['PATH_INFO'].split('/')[1:]

        try:
            endpoint_path = path_info.pop(0)
        except IndexError:
            # PATH_INFO == /
            # undefined behaviour in the protocol spec
            handler.do_greeting()

            return

        if not endpoint_path:
            # /
            handler.do_greeting()

            return

        endpoint = self.get_endpoint(endpoint_path)

        if not endpoint:
            handler.not_found('Unknown endpoint %r' % (endpoint_path,))

            return

        handler.set_endpoint(endpoint)

        # next level of path can be a greeting, info, iframe, raw websocket or
        # sockjs transport uri
        try:
            path = path_info.pop(0)
        except IndexError:
            # /echo
            handler.do_greeting()

            return

        if not path:
            # /echo/
            if not path_info:
                handler.do_greeting()

                return

            # /echo//
            handler.not_found()

            return

        if path == 'info':
            try:
                path = path_info.pop(0)
            except IndexError:
                handler.do_info()

                return

            if not path_info:
                handler.do_info()

                return

            handler.not_found()

            return

        if path.startswith('iframe'):
            if not IFRAME_PATH_RE.match(path):
                handler.not_found()

                return

            return handler.do_iframe()

        if path == 'websocket':
            session_id = uuid.uuid4()

            handler.do_transport(None, session_id, 'rawwebsocket')

            return

        # from here on in the only valid url is a transport url of the form
        # /<server_id>/<session_id>/<transport
        server_id = path

        # server_id values cannot contain '.'
        if not server_id or '.' in server_id:
            handler.not_found()

            return

        try:
            session_id = path_info.pop(0)
        except IndexError:
            handler.not_found()

            return

        if not session_id or '.' in session_id:
            handler.not_found()

            return

        try:
            transport = path_info.pop(0)
        except IndexError:
            handler.not_found()

            return

        if not transport:
            handler.not_found()

            return

        if path_info:
            handler.not_found()

            return

        handler.do_transport(server_id, session_id, transport)
