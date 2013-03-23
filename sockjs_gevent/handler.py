from gevent import pywsgi

from . import router


class HandlerStream(object):
    """
    A very basic file like object that pushes bytes around.

    Provides a simple wrapper API around the socket/handler combo.
    """

    __slots__ = (
        'handler',
        'read',
        'write'
    )

    def __init__(self, handler):
        self.handler = handler

        socket = handler.socket
        rfile = handler.rfile

        if not rfile:
            rfile = socket.makefile('rb', -1)

        self.read = rfile.read
        self.write = socket.sendall


class Handler(pywsgi.WSGIHandler, router.RequestHandler):
    """
    """

    stream = None

    def run_application(self):
        self.stream = self.make_stream()

        router.route_request(self.server, self.environ, self)

    def make_stream(self):
        return HandlerStream(self)
