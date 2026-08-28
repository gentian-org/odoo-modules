from . import log_redaction
from . import controllers
from . import models

# Installed at import, before any request is served: the leak this closes is
# written by werkzeug when it logs the request line, so the filter has to be in
# place from the first request rather than at registry load.
log_redaction.install()
