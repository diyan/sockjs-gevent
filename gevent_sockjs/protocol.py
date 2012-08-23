import hashlib
from errors import *



# try and use the fastest json implementation
try:
    import ujson as json
except ImportError:
    try:
        import simplejson as json
    except ImportError:
        import json


# Frames
# ------

OPEN      = "o\n"
CLOSE     = "c"
MESSAGE   = "a"
HEARTBEAT = "h\n"

# ------------------

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

IFRAME_MD5 = hashlib.md5(IFRAME_HTML).hexdigest()

HTMLFILE_IFRAME_HTML = r"""
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



def encode(message):
    """
    Python to JSON
    """
    if isinstance(message, basestring):
        message = [message]

    return json.dumps(message, separators=(',',':'))



def decode(data):
    """
    JSON to Python
    """
    messages = []
    data = data.decode('utf-8')

    # "a['123', 'abc']" -> [123, 'abc']
    try:
        messages = json.loads(data)
    except JSONDecodeError:
        raise InvalidJSON()

    return messages

def close_frame(code, reason, newline=True):
    if newline:
        return '%s[%d,"%s"]\n' % (CLOSE, code, reason)
    else:
        return '%s[%d,"%s"]' % (CLOSE, code, reason)


def message_frame(data):
    assert isinstance(data, basestring)
    assert '[' in data
    assert ']' in data

    return ''.join([MESSAGE, data])
