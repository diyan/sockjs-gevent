import Cookie
import datetime
import sys
import time
import traceback
from wsgiref.handlers import format_date_time
from gevent import event

from . import protocol


DEFAULT_DELTA = datetime.timedelta(days=365)


def enable_cors(environ, headers):
    """
    Return a list of HTTP headers that will support cross domain requests.

    :param environ: The WSGI environ dict.
    :param headers: List of current HTTP headers. Headers are passed in via
        reference rather than returning as an optimisation.
    """
    origin = environ.get('HTTP_ORIGIN', '*')

    if origin == 'null':
        origin = '*'

    request_headers = environ.get('HTTP_ACCESS_CONTROL_REQUEST_HEADERS', None)

    if request_headers:
        headers.append(('Access-Control-Allow-Headers', request_headers))

    headers.extend([
        ('Access-Control-Allow-Origin', origin),
        ('Access-Control-Allow-Credentials', 'true')
    ])


def disable_cache(headers):
    """
    Return a list of HTTP Headers that will ensure the response is not cached.

    :param headers: List of HTTP headers.
    """
    headers.append(
        ('Cache-Control', 'no-store, no-cache, must-revalidate, max-age=0')
    )


def enable_cache(headers, delta=None, now=datetime.datetime.utcnow):
    """
    Return a list of HTTP Headers that will ensure the response is cached.

    :param delta: A timedelta instance. Will default to 1 year if not
        specified.
    """
    delta = delta or DEFAULT_DELTA
    delta_seconds = delta.total_seconds()

    expires = now() + delta
    expires_timestamp = time.mktime(expires.timetuple())

    headers.extend([
        ('Cache-Control', 'max-age=%d, public' % (delta_seconds,)),
        ('Expires', format_date_time(expires_timestamp)),
        ('Access-Control-Max-Age', str(int(delta_seconds)))
    ])


def enable_cookie(environ, headers):
    """
    Return a list of HTTP Headers that will ensure a sticky cookie that load
    balancers can use to ensure that the request goes to the same backend
    server.
    """
    cookies = Cookie.SimpleCookie(environ.get('HTTP_COOKIE'))

    c = cookies.get('JSESSIONID')

    if not c:
        cookies['JSESSIONID'] = 'dummy'

        c = cookies.get('JSESSIONID')

    c['path'] = '/'

    headers.append(
        ('Set-Cookie', cookies.output(header='').strip())
    )


def get_headers(environ, content_type=None, cors=False, cache=None,
                cookie=False):
    headers = []

    if content_type:
        if ';' not in content_type:
            content_type += '; encoding=UTF-8'

        headers.append(
            ('Content-Type', content_type)
        )

    if cors:
        enable_cors(environ, headers)

    if cache is not None:
        if cache:
            enable_cache(headers)
        else:
            disable_cache(headers)

    if cookie:
        enable_cookie(environ, headers)

    return headers


class BaseHandler(object):
    """
    Wraps a WSGI environ dict and start_response combo with a nice api.
    """

    __slots__ = (
        'environ',
        'start_response',
    )

    def __init__(self, environ, start_response):
        self.environ = environ
        self.start_response = start_response

    def write_response(self, content, status='200 OK', headers=None,
                       **kwargs):
        headers = get_headers(self.environ, **kwargs) + (headers or [])

        writer = self.start_response(status, headers)

        writer(content or '')

        return writer

    def handle_options(self, *allowed_methods):
        method = self.environ['REQUEST_METHOD'].upper()
        allowed_methods = ['OPTIONS'] + list(allowed_methods)

        if method != 'OPTIONS':
            if method in allowed_methods:
                return False

            self.not_allowed(allowed_methods)

            return True

        self.write_nothing(cache=True, cookie=True, cors=True, headers=[
            ('Access-Control-Allow-Methods', ', '.join(allowed_methods))
        ])

        return True

    def write_text(self, content, **kwargs):
        return self.write_response(
            content,
            content_type='text/plain',
            **kwargs
        )

    def write_html(self, content, **kwargs):
        return self.write_response(
            content,
            content_type='text/html',
            **kwargs
        )

    def write_js(self, content, **kwargs):
        if not isinstance(content, basestring):
            content = protocol.encode(content)

        return self.write_response(
            content,
            content_type='application/json',
            **kwargs
        )

    def write_nothing(self, **kwargs):
        return self.write_response(None, status='204 No Content', **kwargs)

    def not_allowed(self, valid_methods, **kwargs):
        headers = kwargs.pop('headers', [])

        headers.extend([
            ('Allow', ', '.join(valid_methods)),
            ('Connection', 'close'),
        ])

        kwargs['headers'] = headers

        return self.write_response(None, status='405 Not Allowed', **kwargs)

    def bad_request(self, msg=None, **kwargs):
        """
        Return a 400 Bad Request response
        """
        return self.write_response(msg, status='400 Bad Request', **kwargs)

    def not_modified(self, **kwargs):
        """
        Return a 304 Not Modified response
        """
        return self.write_response(None, status='304 Not Modified', **kwargs)

    def not_found(self, message=None, status='404 Not Found', cookie=True,
                  content_type='text/plain'):
        """
        Do a 404 NOT FOUND response.
        """
        return self.write_response(
            message or '404 Error: Not Found',
            status=status,
            content_type=content_type,
            cookie=cookie
        )

    def format_exception(self, exc_type, exc_value, exc_tb):
        stack_trace = traceback.format_exception(exc_type, exc_value, exc_tb)

        return str('\n'.join(stack_trace))

    def internal_error(self, message=None, exc_info=None, trace=False,
                       **kwargs):
        """
        Return a 500 Internal Server Error response.
        """
        if not message:
            if trace:
                if not exc_info:
                    exc_info = sys.exc_info()

                if exc_info:
                    message = self.format_exception(*exc_info)

        return self.write_response(
            message,
            status='500 Internal Server Error',
            content_type='text/plain',
            **kwargs
        )


def waitany(events, timeout=None, result_class=event.AsyncResult):
    result = result_class()
    update = result.set

    try:
        for event in events:
            if not event.started:
                event.start()

            if event.ready():
                return event
            else:
                event.rawlink(update)

        return result.get(timeout=timeout)
    finally:
        for event in events:
            event.unlink(update)
