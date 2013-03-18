import hashlib
import random
import re
import sys
import traceback
import uuid

from gevent import pywsgi, socket

from . import protocol, transports, util


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


class Handler(pywsgi.WSGIHandler, util.BaseHandler):
    """
    The basic handler for all things SockJS. Does all path handling and
    validation.

    For urls that support it, delegates all responsibility of the response to a
    transport class.
    """

    endpoint = None

    allowed_methods = None

    def start_streaming(self):
        self.result = None

        if self.request_version == 'HTTP/1.1':
            self.headers['Connection'] = 'keep-alive'
            self.response_use_chunked = True
        else:
            self.headers['Connection'] = 'close'

    def application(self):
        # first get the endpoint name from the path
        path_info = self.environ['PATH_INFO'].split('/')[1:]

        try:
            endpoint = path_info.pop(0)
        except IndexError:
            # PATH_INFO == /
            # undefined behaviour in the protocol spec
            self.do_greeting()

            return []

        if not endpoint:
            # /
            self.do_greeting()

            return []

        self.endpoint = self.server.get_endpoint(endpoint)

        if not self.endpoint:
            self.do404('Unknown endpoint %r' % (endpoint,))

            return []

        # next level of path can be a greeting, info, iframe, raw websocket or
        # sockjs transport uri
        try:
            path = path_info.pop(0)
        except IndexError:
            # /echo
            self.do_greeting()

            return []

        if not path:
            # /echo/
            if not path_info:
                self.do_greeting()
            else:
                # /echo//
                self.do404()

            return

        if path == 'info':
            self.do_info()

            return []

        if path.startswith('iframe'):
            if not IFRAME_PATH_RE.match(path):
                self.do404()

                return []

            self.do_iframe()

            return []

        if path == 'websocket':
            session_id = uuid.uuid4()

            self.do_transport(None, session_id, 'rawwebsocket')

            return []

        # from here on in the only valid url is a transport url of the form
        # /<server_id>/<session_id>/<transport
        server_id = path

        # server_id values cannot contain '.'
        if not server_id or '.' in server_id:
            self.do404()

            return []

        try:
            session_id = path_info.pop(0)
        except IndexError:
            self.do404()

            return []

        if not session_id or '.' in session_id:
            self.do404()

            return []

        try:
            transport = path_info.pop(0)
        except IndexError:
            self.do404()

            return []

        if path_info:
            self.do404()

            return []

        self.do_transport(server_id, session_id, transport)

        return []

    def do_greeting(self):
        if self.handle_options('GET'):
            return

        self.write_text('Welcome to SockJS!\n', cache=True)

    def do_iframe(self):
        if self.handle_options('GET'):
            return

        content = IFRAME_HTML % (self.endpoint.sockjs_url,)
        our_etag = hashlib.md5(content).hexdigest()

        cached = self.environ.get('HTTP_IF_NONE_MATCH', None)

        if cached and cached == our_etag:
            self.not_modified()

            return

        self.write_html(content, cache=True, headers=[
            ('ETag', our_etag)
        ])

    def do_info(self):
        """
        Used to check server capabilities (websocket support, cookies) and to
        get the value of "origin" setting (currently not used).
        """
        if self.handle_options('GET'):
            return

        entropy = random.randint(1, 2 ** 32)
        info = {
            'cookie_needed': self.endpoint.use_cookie,
            'websocket': self.endpoint.transport_allowed('websocket'),
            'origins': ['*:*'],
            'entropy': entropy,
            'server_heartbeat_interval': self.server.heartbeat_interval
        }

        self.write_js(info, cors=True, cache=False)

    def do_transport(self, server_id, session_id, transport):
        # validate the transport value
        transport_cls = transports.get_transport_class(transport)

        if not transport_cls:
            self.do404()

            return

        # check if the transport is disabled for this endpoint
        if not self.endpoint.transport_allowed(transport):
            self.do404()

            return

        # only create sessions if the transport being used is readable
        create = transport_cls.readable
        # basic transport validation is out the way (the quick stuff)
        # lets set up the session
        session = self.server.get_session(session_id, create)

        if not session:
            # on a writable transport and there is no session
            self.do404()

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

                return

            try:
                if not self.result:
                    self.result = []

                self.process_result()
            except Exception:
                session.interrupt()

                if not isinstance(e, socket.error):
                    raise
