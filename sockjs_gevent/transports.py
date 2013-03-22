import urlparse
from socket import error as sock_err

import gevent
from gevent import socket, select
from geventwebsocket import WebSocketError, WebSocketHandler

from . import protocol, session


class TransportError(Exception):
    """
    Base class for all transport related errors.
    """


class BaseTransport(object):
    """
    :ivar readable: Whether this transport supports reading messages from the
        session.
    :ivar writable: Whether this transport supports writing messages to the
        session.
    :ivar streaming: Whether this is a streaming transport
    """

    # the direction of the transport. Used in session locking
    readable = False
    writable = False

    # whether this is a streaming transport
    streaming = False

    # whether to cache the http response
    cache = False
    # whether to add 'sticky' cookies to the http response
    cookie = False
    # whether to support a CORS http response
    cors = False
    # basic response type
    content_type = "text/plain"
    # a list of supported http methods.
    http_options = []

    # for transports that support it, the time to wait for messages from the
    # session
    timeout = 5.0

    def __init__(self, session, handler):
        """
        Constructor for the transport.

        :param session: The Session object for this connection.
        """
        self.session = session
        self.handler = handler

    @property
    def is_socket(self):
        return self.streaming and self.readable and self.writable

    def handle_request(self, handler, raw_request_data):
        raise NotImplementedError

    def do_open(self, handler):
        """
        Encode and write the 'open' frame to the handler.
        """
        raise NotImplementedError

    def write_close_frame(self, handler, code, reason):
        """
        Write a close frame to the handler.
        """
        frame = protocol.close_frame(code, reason)
        handler.write(self.encode_frame(frame))

    def write_message_frame(self, handler, messages):
        if not messages:
            return

        frame = self.encode_frame(protocol.message_frame(*messages))

        handler.write(frame)

    def encode_frame(self, data):
        """
        Write the data in a frame specifically for this transport. Deals with
        the edge cases of formatting the messages for the transports. Things
        like \n characters and Javascript callback frames.
        """
        return data

    def prep_response(self, handler):
        if self.cache:
            handler.enable_cache()
        else:
            handler.disable_cache()

        if self.cors:
            handler.enable_cors()

        if self.cookie:
            handler.enable_cookie()

        if self.streaming:
            handler.start_streaming()

    def finalize_request(self, handler):
        pass

    def __call__(self, handler, raw_request_data):
        # ensure that the request has approached us with a valid REQUEST_METHOD
        if handler.handle_options(*self.http_options):
            return

        self.prep_response(handler)

        if handler.status and not handler.status.startswith('200 '):
            # prep_response set a custom status
            return

        try:
            self.session.lock(self, self.readable, self.writable)

            if self.session.new:
                self.session.start()

                if not self.streaming:
                    self.do_open(handler)

                    return

            if self.streaming:
                self.do_open(handler)

            self.handle_request(handler, raw_request_data)
        except session.SessionUnavailable, e:
            if not handler.status:
                handler.start_response('200 OK')

            self.write_close_frame(handler, e.code, e.reason)
        finally:
            self.session.unlock(self, self.readable, self.writable)

            self.finalize_request(handler)

    def send_heartbeat(self):
        raise NotImplementedError


class WritingOnlyTransport(BaseTransport):
    """
    Base functionality for a transport that only receives messages from the
    client.

    Decodes the received messages and adds them to the session.
    """

    writable = True
    readable = False

    streaming = False

    cache = False
    cookie = True

    def get_payload(self, handler, raw_request_data):
        return raw_request_data

    def handle_request(self, handler, raw_request_data):
        payload = self.get_payload(handler, raw_request_data)

        if not payload:
            handler.do500('Payload expected.')

            return

        try:
            messages = protocol.decode(payload)
        except protocol.InvalidJSON:
            handler.do500('Broken JSON encoding.')

            return

        self.session.dispatch(*messages)


class XHRSend(WritingOnlyTransport):
    cors = True
    http_options = ['POST']

    def finalize_request(self, handler):
        if self.session.open:
            handler.write_nothing()


class JSONPSend(WritingOnlyTransport):
    cors = False
    http_options = ['POST']

    def get_payload(self, handler, raw_request_data):
        content_type = handler.environ.get('CONTENT_TYPE', 'text/plain')

        if content_type == 'text/plain':
            return raw_request_data

        if content_type == 'application/x-www-form-urlencoded':
            # Do we have a Payload?
            qs = urlparse.parse_qs(raw_request_data)

            return qs.get('d', [None])[0]

    def finalize_request(self, handler):
        if self.session.open:
            handler.start_response('200 OK')
            handler.write('ok')


class SendingOnlyTransport(BaseTransport):
    readable = True

    cookie = True
    cache = False

    def send_heartbeat(self):
        self.handler.write(self.encode_frame(protocol.HEARTBEAT))

    def produce_messages(self, handler):
        raise NotImplementedError

    def handle_request(self, handler, raw_request_data):
        # in a sending only transport, no more data is expected from the client
        # but we need to be notified immediately if the connection has been
        # aborted by the client.

        fd = handler.socket.fileno()

        # start 2 greenlets, one that checks for an aborted connection
        # and the other that produces the messages
        producer = gevent.Greenlet(self.produce_messages, handler)
        conn_check = gevent.Greenlet(select.select, [fd], [], [fd])

        threads = [
            producer,
            conn_check
        ]

        # start both threads
        for thread in threads:
            thread.start()

        # wait for one to return
        ret = waitany(threads)

        if ret == producer:
            # the producer thread returned first, all good here.
            conn_check.kill()

            return

        # looks like the connection was aborted
        producer.kill()

        raise socket.error(socket.EBADF)


class PollingTransport(SendingOnlyTransport):
    """
    Long polling derivative transports, used for XHRPolling and JSONPolling.
    """

    content_type = 'application/javascript'

    def prep_response(self, handler):
        super(PollingTransport, self).prep_response(handler)

        handler.start_response('200 OK')

    def do_open(self, handler):
        handler.write(self.encode_frame(protocol.OPEN))

    def produce_messages(self, handler):
        """
        Spin lock the thread until we have a message on the queue.
        """
        messages = self.session.get_messages(timeout=self.timeout)

        self.write_message_frame(handler, messages)


class XHRPolling(PollingTransport):
    http_options = ['POST']
    cors = True

    def encode_frame(self, data):
        return data + '\n'


class JSONPolling(PollingTransport):
    http_options = ['GET']
    cors = False

    def encode_frame(self, data):
        frame = protocol.encode(data)

        return "%s(%s);\r\n" % (self.callback, frame)

    def prep_response(self, handler):
        qs = urlparse.parse_qs(handler.environ.get("QUERY_STRING", ''))

        self.callback = qs.get('c', qs.get('callback', [None]))[0]

        if not self.callback:
            handler.do500('"callback" parameter required')

            return

        return super(JSONPolling, self).prep_response(handler)


class StreamingTransport(SendingOnlyTransport):
    streaming = True

    # the minimum amount of text to produce before closing the response
    # according to sockjs-protocol, the response limit should be 128KiB
    response_limit = 128 * 1024

    def produce_messages(self, handler):
        bytes_to_write = self.response_limit + handler.response_length

        while handler.response_length < bytes_to_write:
            if not self.session.open:
                break

            messages = self.session.get_messages(timeout=self.timeout)

            if not messages:
                continue

            try:
                self.write_message_frame(handler, messages)
            except sock_err:
                self.session.interrupt()

                break

    def handle_request(self, handler, raw_request_data):
        super(StreamingTransport, self).handle_request(handler, raw_request_data)

        if self.session.closed:
            self.write_close_frame(handler, *protocol.CONN_CLOSED)


class XHRStreaming(StreamingTransport):
    cors = True
    http_options = ['POST']

    prelude = 'h' *  2049
    content_type = "application/javascript"

    def encode_frame(self, data):
        return data + '\n'

    def prep_response(self, handler):
        super(XHRStreaming, self).prep_response(handler)

        handler.start_response('200 OK')

        handler.write(self.encode_frame(self.prelude))

    def do_open(self, handler):
        handler.write(self.encode_frame(protocol.OPEN))


class HTMLFile(StreamingTransport):
    content_type = 'text/html'
    http_options = ['GET']

    IFRAME_HTML = r"""
<!doctype html>
<html><head>
  <meta http-equiv="X-UA-Compatible" content="IE=edge" />
  <meta http-equiv="Content-Type" content="text/html; charset=UTF-8" />
</head><body><h2>Don't panic!</h2>
  <script>
    document.domain = document.domain;
    var c = parent.%s;
    c.start();
    function p(d) {c.message(d);};
    window.onload = function() {c.stop();};
  </script>
""".strip()

    def encode_frame(self, frame):
        return '<script>\np("%s");\n</script>\r\n' % frame.replace('"', '\\"')

    def do_open(self, handler):
        open_frame = self.encode_frame(protocol.OPEN)
        handler.write(open_frame)

    def prep_response(self, handler):
        super(HTMLFile, self).prep_response(handler)

        # Start writing
        handler.start_response("200 OK")

        html = self.IFRAME_HTML % self.callback
        html = html.rjust(1025)

        handler.write(html)

    def __call__(self, handler, raw_request_data):
        qs = urlparse.parse_qs(handler.environ.get("QUERY_STRING", ''))
        self.callback = qs.get('c', [None])[0]

        if not self.callback:
            handler.do500(message='"callback" parameter required')

            return

        super(HTMLFile, self).__call__(handler, raw_request_data)


class EventSource(StreamingTransport):
    content_type = 'text/event-stream'

    http_options = ['GET']

    def encode_frame(self, data):
        return "data: %s\r\n\r\n" % data

    def do_open(self, handler):
        handler.write(self.encode_frame(protocol.OPEN))

    def prep_response(self, handler):
        super(EventSource, self).prep_response(handler)

        handler.start_response("200 OK")

        handler.write('\r\n')


# Socket Transports
# ==================
#
# Provides a bidirectional connection to and from the client.
# Sending and receiving are split in two different threads.


class WSHandler(WebSocketHandler):
    def log_request(self):
        pass


class RawWebSocket(BaseTransport):
    readable = True
    writable = True
    streaming = True

    http_options = ['GET']

    websocket = None

    def do_open(self, handler):
        pass

    def send_messages(self, messages):
        for message in messages:
            self.websocket.send(message)

    def dispatch_message(self, message):
        self.session.dispatch(message)

    def poll(self):
        """
        Get messages from the session and send them down the socket.
        """
        while self.session.open:
            messages = self.session.get_messages(self.timeout)

            if not messages:
                continue

            try:
                self.send_messages(messages)
            except WebSocketError:
                return

    def recv_message(self):
        return self.websocket.receive()

    def put(self):
        while self.session.open:
            try:
                message = self.recv_message()
            except WebSocketError:
                return

            if message is None:
                break

            self.dispatch_message(message)

    def handle_websocket(self, handler):
        threads = [
            gevent.spawn(self.poll),
            gevent.spawn(self.put),
        ]

        ret = waitany(threads)
        threads.remove(ret)
        gevent.killall(threads)

        if not ret.successful():
            raise ret.exception

    def finalize_request(self, handler):
        if self.session.open:
            self.session.close()

        if self.websocket:
            self.websocket.close()

    def handle_request(self, handler, raw_request_data):
        self.websocket = None

        ws_handler = WSHandler(
            handler.socket,
            handler.client_address,
            handler.server,
            handler.rfile
        )

        def app(environ, start_response):
            del ws_handler.application

            handler.__dict__.update(ws_handler.__dict__)

            self.websocket = getattr(ws_handler, 'websocket', None)

            if not self.websocket:
                handler.bad_request('Can "Upgrade" only to "WebSocket".')

                return []

            try:
                self.handle_websocket(handler)
            except WebSocketError:
                pass

        # TODO find a better way to do this.
        ws_handler.__dict__.update(handler.__dict__)
        ws_handler.application = app

        try:
            ws_handler.run_application()
        except (sock_err, WebSocketError):
            pass

    def send_heartbeat(self):
        self.websocket.send(self.encode_frame(protocol.HEARTBEAT))


class WebSocket(RawWebSocket):
    def write_close_frame(self, handler, code, reason):
        if self.websocket:
            frame = protocol.close_frame(code, reason)

            try:
                self.websocket.send(self.encode_frame(frame))
            except WebSocketError:
                pass

            self.websocket.close()

            return

        super(WebSocket, self).write_close_frame(handler, code, reason)

    def recv_message(self):
        while self.session.open:
            try:
                return self.websocket.receive()
            except WebSocketError, e:
                # specifically have to check for a close frame
                if 'frame_type=255' in str(e):
                    return None

                raise
            except (TypeError, ValueError):
                continue
            except (socket.error, AttributeError):
                return None

    def send_messages(self, messages):
        if not messages:
            return

        frame = self.encode_frame(protocol.message_frame(*messages))

        self.websocket.send(frame)

    def dispatch_message(self, message):
        if not message:
            return

        try:
            messages = protocol.decode(message)
        except protocol.InvalidJSON:
            self.websocket.close()

            return

        if not isinstance(messages, list):
            messages = [messages]

        self.session.dispatch(*messages)

    def handle_websocket(self, handler):
        self.websocket.send(protocol.OPEN)

        super(WebSocket, self).handle_websocket(handler)

        self.write_close_frame(handler, *protocol.CONN_CLOSED)


transport_types = {

    # Ajax Tranports
    # ==============
    'xhr'           : XHRPolling,
    'xhr_send'      : XHRSend,
    'xhr_streaming' : XHRStreaming,
    'jsonp'         : JSONPolling,
    'jsonp_send'    : JSONPSend,

    # WebSockets
    # ===============
    'websocket'     : WebSocket,
    'rawwebsocket'  : RawWebSocket,

    # File Transports
    # ===============
    'eventsource'   : EventSource,
    'htmlfile'      : HTMLFile,
}


def get_transport_class(transport):
    return transport_types.get(transport, None)


def waitany(events, timeout=None):
    from gevent.event import AsyncResult

    result = AsyncResult()
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


def get_transports(**kwargs):
    pass
