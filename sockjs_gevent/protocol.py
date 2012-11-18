# try and use the fastest json implementation
try:
    import ujson as json

    def dumps(obj, *args, **kwargs):
        """
        ujson.dumps does not accept the separators arg
        """
        return json.dumps(obj)
except ImportError:
    try:
        import simplejson as json
    except ImportError:
        import json

    def dumps(obj, *args, **kwargs):
        return json.dumps(obj, separators=(',', ':'), indent=0)


OPEN      = "o"
CLOSE     = "c"
MESSAGE   = "a"
HEARTBEAT = "h\n"

# known error code/message
CONN_INTERRUPTED = (1002, "Connection interrupted")
CONN_ALREADY_OPEN = (2010, "Another connection still open")
CONN_CLOSED = (3000, "Go away!")


class InvalidJSON(Exception):
    """
    Raised if an invalid JSON payload is
    """


def encode(message):
    """
    Python to JSON
    """
    return json.dumps(message)


def decode(data):
    """
    JSON to Python
    """
    if isinstance(data, unicode):
        data = data.encode('utf-8')

    # quick check to make sure we're going to decode a list
    if data[0] != '[':
        raise InvalidJSON(data)

    try:
        return json.loads(data)
    except ValueError:
        raise InvalidJSON(data)


def close_frame(code, reason):
    if not isinstance(reason, basestring):
        reason = unicode(reason)

    return '%s[%d,"%s"]' % (CLOSE, code, reason)


def message_frame(*chunks):
    return MESSAGE + encode(chunks)
