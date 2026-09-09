from pathlib import Path
import os


BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("AIBI_DATA_DIR", BASE_DIR / "data")).resolve()
SAMPLE_DIR = (BASE_DIR / "samples").resolve()
DATABASE_URL = os.getenv(
    "AIBI_DATABASE_URL", f"sqlite+aiosqlite:///{(DATA_DIR / 'aibi-v2.db').as_posix()}"
)
MAX_UPLOAD_BYTES = int(os.getenv("AIBI_MAX_UPLOAD_BYTES", 50 * 1024 * 1024))
ALLOWED_EXTENSIONS = {".csv", ".xlsx", ".xls"}

# Generated code is deliberately unavailable unless a real sandbox is configured.
SANDBOX_ENABLED = os.getenv("AIBI_SANDBOX_ENABLED", "false").lower() == "true"
SANDBOX_IMAGE = os.getenv("AIBI_SANDBOX_IMAGE", "")
SUPERSET_URL = os.getenv("AIBI_SUPERSET_URL", "")
SUPERSET_USERNAME = os.getenv("AIBI_SUPERSET_USERNAME", "")
SUPERSET_PASSWORD = os.getenv("AIBI_SUPERSET_PASSWORD", "")
SUPERSET_DASHBOARD_ID = os.getenv("AIBI_SUPERSET_DASHBOARD_ID", "")
CURATED_DATABASE_URL = os.getenv("AIBI_CURATED_DATABASE_URL", "")
SUPERSET_CURATED_DATABASE_URI = os.getenv("AIBI_SUPERSET_CURATED_DATABASE_URI", "")
CUBE_API_URL = os.getenv("AIBI_CUBE_API_URL", "")
CUBE_API_TOKEN = os.getenv("AIBI_CUBE_API_TOKEN", "")
DAILY_LLM_BUDGET_CNY = float(os.getenv("AIBI_DAILY_LLM_BUDGET_CNY", "5"))
MAX_LLM_OUTPUT_TOKENS = int(os.getenv("AIBI_MAX_LLM_OUTPUT_TOKENS", "4000"))
