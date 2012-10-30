"""
This module is most like what a user would define in their
application, namely the

    - Routes
    - Connection Handlers

The one's sketched here are the Echo, Disabled Websockets, and
the Close connection handlers which are used by the protocol test
suite.
"""

import gevent.monkey

# Monkey patching stdlib is not a necessity for all use cases
gevent.monkey.patch_all()

from sockjs_gevent.server import Server, Connection, Endpoint

# Need to monkey patch the threading module to use greenlets
import werkzeug.serving


class Echo(Connection):
    def on_message(self, message):
        self.send(message)


class Close(Connection):
    def on_open(self):
        self.close()


@werkzeug.serving.run_with_reloader
def devel_server():
    """
    A local server with code reload. Should only be used for development.
    """
    from sockjs_gevent.transports import StreamingTransport

    # set the response limit according to sockjs-protocol for the test server
    StreamingTransport.response_limit = 4224

    endpoints = {
        'echo': Endpoint(Echo),
        'close': Endpoint(Close),
        'disabled_websocket_echo': Endpoint(Echo,
            disabled_transports=['websocket']
        ),
        'cookie_needed_echo': Endpoint(Echo,
            use_cookie=True
        )
    }

    server = Server(('localhost', 8081), endpoints)
    server.serve_forever()
