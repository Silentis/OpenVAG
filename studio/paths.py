import sys
from pathlib import Path

IS_FROZEN = getattr(sys, "frozen", False)
BUNDLE_DIR = Path(sys._MEIPASS) if IS_FROZEN else Path(__file__).resolve().parent.parent
APP_DIR = Path(sys.executable).parent if IS_FROZEN else Path(__file__).resolve().parent.parent

BACKUP_DIR = APP_DIR / "backups"
LOG_DIR = APP_DIR / "logs"

BACKUP_DIR.mkdir(parents=True, exist_ok=True)
LOG_DIR.mkdir(parents=True, exist_ok=True)