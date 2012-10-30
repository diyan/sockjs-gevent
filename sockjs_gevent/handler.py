import Cookie
import datetime
import hashlib
import random
import re
import sys
import time
import traceback
import uuid

from gevent import pywsgi, socket

from . import protocol, transports


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


class Headers(object):
    """
    A basic HTTP headers container that supports the SockJS protocol.
    """

    charset = 'UTF-8'
    content_type = 'text/plain'

    def __init__(self):
        self._headers = {}

    def __iter__(self):
        return self.get_headers()

    def __getitem__(self, key):
        return self._headers.__getitem__(key.lower())

    def __setitem__(self, key, value):
        return self._headers.__setitem__(key.lower(), value)

    def __delitem__(self, key):
        try:
            return self._headers.__delitem__(key.lower())
        except KeyError:
            pass

    def get_headers(self):
        """
        Generate a list of tuples for the associated HTTP headers
        """
        headers = []

        if self.content_type:
            headers.append(('Content-Type', '%s; charset=%s' % (
                self.content_type, self.charset)))

        for key, value in self._headers.iteritems():
            header = '-'.join([x.capitalize() for x in key.split('-')]), value

            headers.append(header)

        return headers


class Handler(pywsgi.WSGIHandler):
    """
    The basic handler for all things SockJS. Does all path handling and
    validation.

    For urls that support it, delegates all responsibility of the response to a
    transport class.
    """

    endpoint = None

    def enable_cors(self):
        """
        Ensure the response is Cross Domain compatible.
        """
        origin = self.environ.get('HTTP_ORIGIN', '*')

        if origin == 'null':
            origin = '*'

        request_headers = self.environ.get('HTTP_ACCESS_CONTROL_REQUEST_HEADERS', None)

        if request_headers:
            self.headers['Access-Control-Allow-Headers'] = request_headers

        self.headers['Access-Control-Allow-Origin'] = origin
        self.headers['Access-Control-Allow-Credentials'] = 'true'

    def disable_cache(self):
        """
        Ensure the response is not cached.
        """
        self.headers['Cache-Control'] = ('no-store, no-cache, must-revalidate, '
                                         'max-age=0')

        del self.headers['Expires']
        del self.headers['Access-Control-Max-Age']

    def enable_cache(self, delta=None):
        """
        Ensure the response is cached.

        :param delta: A timedelta instance. Will default to 1 year if not
            specified.
        """
        delta = delta or datetime.timedelta(days=365)
        s = delta.total_seconds()

        d = datetime.datetime.utcnow() + delta

        self.headers['Cache-Control'] = 'max-age=%d, public' % (s,)
        self.headers['Expires'] = pywsgi.format_date_time(time.mktime(d.timetuple()))
        self.headers['Access-Control-Max-Age'] = str(int(s))

    def enable_cookie(self):
        """
        Ensure the response requires a cookie, set one.
        """
        if not self.endpoint:
            return

        if not self.endpoint.use_cookie:
            return

        cookies = Cookie.SimpleCookie(self.environ.get('HTTP_COOKIE'))

        c = cookies.get('JSESSIONID')

        if not c:
            cookies['JSESSIONID'] = 'dummy'

            c = cookies.get('JSESSIONID')

        c['path'] = '/'

        self.headers['Set-Cookie'] = cookies.output(header='').strip()

    def start_streaming(self):
        self.result = None

        if self.request_version == 'HTTP/1.1':
            self.headers['Connection'] = 'keep-alive'
            self.response_use_chunked = True
        else:
            self.headers['Connection'] = 'close'

    def do404(self, message=None):
        """
        Do a 404 NOT FOUND response.
        """
        self.headers.content_type = 'text/plain'

        self.enable_cookie()
        self.start_response("404 Not Found")

        self.result = [message or '404 Error: Page not found']
        self.process_result()

    def format_exception(self, exc_type, exc_value, exc_tb):
        stack_trace = traceback.format_exception(exc_type, exc_value, exc_tb)

        return str('\n'.join(stack_trace))

    def do500(self, message=None, exc_info=None):
        result = message

        if not result:
            if self.server.trace:
                if not exc_info:
                    exc_info = sys.exc_info()

                if exc_info:
                    result = self.format_exception(*exc_info)

        self.start_response("500 Internal Server Error", [
            ('Content-Type', 'text/plain'),
            ('Connection', 'close'),
        ])
        self.result = [result or '500: Internal Server Error']
        self.process_result()

    def raw_headers(self):
        return self.headers.get_headers()

    def start_response(self, status, headers=None, exc_info=None):
        if not headers:
            headers = self.raw_headers()

        return super(Handler, self).start_response(status, headers, exc_info)

    def run_application(self):
        # first get the endpoint name from the path
        path_info = self.environ['PATH_INFO'].split('/')[1:]

        # yes, we're overwriting self.headers, no I don't mind because we have
        # self.environ
        self.headers = Headers()

        try:
            endpoint = path_info.pop(0)
        except IndexError:
            # PATH_INFO == /
            # undefined behaviour in the protocol spec
            self.do_greeting()

            return

        if not endpoint:
            # /
            self.do_greeting()

            return

        self.endpoint = self.server.get_endpoint(endpoint)

        if not self.endpoint:
            self.do404('Unknown endpoint %r' % (endpoint,))

            return

        # next level of path can be a greeting, info, iframe, raw websocket or
        # sockjs transport uri
        try:
            path = path_info.pop(0)
        except IndexError:
            # /echo
            self.do_greeting()

            return

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

            return

        if path.startswith('iframe'):
            if not IFRAME_PATH_RE.match(path):
                self.do404()

                return

            self.do_iframe()

            return

        if path == 'websocket':
            session_id = uuid.uuid4()

            self.do_transport(None, session_id, 'rawwebsocket')

            return

        # from here on in the only valid url is a transport url of the form
        # /<server_id>/<session_id>/<transport
        server_id = path

        # server_id values cannot contain '.'
        if not server_id or '.' in server_id:
            self.do404()

            return

        try:
            session_id = path_info.pop(0)
        except IndexError:
            self.do404()

            return

        if not session_id or '.' in session_id:
            self.do404()

            return

        try:
            transport = path_info.pop(0)
        except IndexError:
            self.do404()

            return

        if path_info:
            self.do404()

            return

        self.do_transport(server_id, session_id, transport)

    def handle_options(self, *allowed_methods):
        method = self.environ['REQUEST_METHOD'].upper()
        allowed_methods = ['OPTIONS'] + list(allowed_methods)

        if method != 'OPTIONS':
            if method in allowed_methods:
                return False

            self.not_allowed(allowed_methods)

            return True

        self.headers['Access-Control-Allow-Methods'] = ', '.join(allowed_methods)

        self.enable_cache()
        self.enable_cookie()
        self.enable_cors()
        self.write_nothing()

        return True

    def write_text(self, content):
        self.headers.content_type = 'text/plain'

        self.start_response('200 OK')
        self.result = [content]
        self.process_result()

    def write_html(self, content):
        self.headers.content_type = 'text/html'

        self.start_response('200 OK')
        self.result = [content]
        self.process_result()

    def write_js(self, content):
        self.headers.content_type = 'application/json'

        self.start_response('200 OK')

        if not isinstance(content, basestring):
            content = protocol.encode(content)

        self.result = [content]
        self.process_result()

    def write_nothing(self):
        self.start_response('204 No Content')

        self.result = []
        self.process_result()

    def not_allowed(self, valid_methods):
        self.start_response('405 Not Allowed', [
            ('Allow', ', '.join(valid_methods)),
            ('Connection', 'close'),
            ])

        self.result = []
        self.process_result()

    def bad_request(self, msg=None):
        """
        Return a 400 Bad Request response
        """
        self.headers.content_type = None

        self.start_response('400 Bad Request')

        self.result = []

        if msg:
            self.result.append(msg)

        self.process_result()

    def not_modified(self):
        """
        Return a 304 Not Modified response
        """
        self.headers.content_type = None

        self.start_response('304 Not Modified')

        self.result = []
        self.process_result()

    def do_greeting(self):
        if self.handle_options('GET'):
            return

        self.enable_cache()

        self.write_text('Welcome to SockJS!\n')

    def do_iframe(self):
        if self.handle_options('GET'):
            return

        self.enable_cache()

        content = IFRAME_HTML % (self.endpoint.sockjs_url,)
        our_etag = hashlib.md5(content).hexdigest()

        cached = self.environ.get('HTTP_IF_NONE_MATCH', None)

        if cached and cached == our_etag:
            self.not_modified()

            return

        self.headers['ETag'] = our_etag

        self.write_html(content)

    def do_info(self):
        """
        Used to check server capabilities (websocket support, cookies) and to
        get the value of "origin" setting (currently not used).
        """
        if self.handle_options('GET'):
            return

        self.enable_cors()
        self.disable_cache()

        entropy = random.randint(1, 2**32)

        self.write_js({
            'cookie_needed': self.endpoint.use_cookie,
            'websocket': self.endpoint.transport_allowed('websocket'),
            'origins': ['*:*'],
            'entropy': entropy,
            'server_heartbeat_interval': self.server.heartbeat_interval
        })

    def do_transport(self, server_id, session_id, transport):
        """
        """
        # validate the transport value
        transport_cls = transports.get_transport_class(transport)

        if not transport_cls:
            self.do404()

            return

        # check if the transport is disabled for this endpoint
        if not self.endpoint.transport_allowed(transport):
            self.do404()

            return

        self.headers.content_type = transport_cls.content_type

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

                raise
