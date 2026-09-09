import os

SECRET_KEY = os.environ["SUPERSET_SECRET_KEY"]
GUEST_TOKEN_JWT_SECRET = os.environ["SUPERSET_GUEST_TOKEN_JWT_SECRET"]
GUEST_TOKEN_JWT_AUDIENCE = "superset"
FEATURE_FLAGS = {"EMBEDDED_SUPERSET": True}
# Superset ships a Simplified Chinese translation. Keep English available as a fallback.
BABEL_DEFAULT_LOCALE = "zh"
LANGUAGES = {
    "zh": {"flag": "cn", "name": "Chinese"},
    "en": {"flag": "us", "name": "English"},
}
# Local single-machine MCP identity. Do not use this development shortcut on a
# public deployment; production must authenticate MCP callers with user tokens.
MCP_DEV_USERNAME = "admin"
# Insight Studio discovers and allow-lists tools itself, so expose the concrete
# Superset tool catalog instead of the optional search/call proxy pair.
MCP_TOOL_SEARCH_CONFIG = {"enabled": False}
TALISMAN_ENABLED = False
ENABLE_CORS = True
CORS_OPTIONS = {
    "supports_credentials": True,
    "allow_headers": ["*"],
    "resources": ["*"],
    "origins": [f"http://localhost:{port}" for port in range(5173, 5191)],
}
WTF_CSRF_ENABLED = True
WTF_CSRF_EXEMPT_LIST = ["superset.views.core.log"]
SESSION_COOKIE_SAMESITE = "Lax"
