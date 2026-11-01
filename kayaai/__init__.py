"""kayaAI - yerel, çok-ajanlı kişisel yapay zeka sistemi."""

import logging as _logging

__version__ = "0.14.3"
APP_NAME = "kayaAI"

# Kütüphane olarak kullanıldığında log yapılandırılmamışsa konsola gürültü basma.
_logging.getLogger("kayaai").addHandler(_logging.NullHandler())
