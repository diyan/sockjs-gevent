from gevent import pywsgi


class Handler(pywsgi.WSGIHandler):
    """
    The basic handler for all things SockJS. Does all path handling and
    validation.

    For urls that support it, delegates all responsibility of the response to a
    transport class.
    """

    def start_streaming(self):
        self.result = None

        if self.request_version == 'HTTP/1.1':
            self.headers['Connection'] = 'keep-alive'
            self.response_use_chunked = True
        else:
            self.headers['Connection'] = 'close'
