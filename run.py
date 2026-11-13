"""JSON Imager baslaticisi.

Calistirma:  .\\.venv\\Scripts\\python.exe run.py

Paketlenmis exe'de `src/` klasoru bulunmaz; paket zaten gomulu oldugu icin
yol eklemesi yalnizca gelistirme kurulumunda yapilir.
"""

import sys
from pathlib import Path

_SRC = Path(__file__).resolve().parent / "src"
if _SRC.is_dir() and str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from jsonimager.app import main  # noqa: E402

if __name__ == "__main__":
    main()
