"""SCF entry point: index.main_handler (package the contents of backend/)."""
import os

from profiles.coze import CozeAssessor, CozeVariableWriter, LegacyAuth
from profiles.service import ProfileApplication
from profiles.storage import production_store


def main_handler(event, context):
    required = ("PROFILE_BUCKET", "PROFILE_REGION", "IDENTITY_SECRET", "ADMIN_KEY",
                "LEGACY_AUTH_URL")
    if any(not os.environ.get(key) for key in required):
        return ProfileApplication.response(503, {"error": {"code": "NOT_CONFIGURED", "message": "课堂后台尚未配置完成"}},
                                           {"Content-Type": "application/json", "Cache-Control": "no-store"})
    try:
        legacy_auth = LegacyAuth(os.environ["LEGACY_AUTH_URL"])
        assessor = (CozeAssessor(os.environ["COZE_ASSESSMENT_TOKEN"])
                    if os.environ.get("COZE_ASSESSMENT_TOKEN")
                    else CozeAssessor(token_provider=legacy_auth))
        app = ProfileApplication(
            production_store(os.environ["PROFILE_BUCKET"], os.environ["PROFILE_REGION"]),
            assessor, legacy_auth,
            os.environ["IDENTITY_SECRET"], os.environ["ADMIN_KEY"], os.environ.get("COZE_PLUGIN_KEY"),
            origin=os.environ.get("ALLOWED_ORIGIN", "https://test.homura.cn"),
            variable_writer=CozeVariableWriter() if os.environ.get('COZE_PROFILE_MODE', 'variables') == 'variables' else None,
        )
    except Exception:
        return ProfileApplication.response(503, {"error": {"code": "NOT_CONFIGURED", "message": "课堂后台配置需检查"}},
                                           {"Content-Type": "application/json", "Cache-Control": "no-store"})
    return app.handle(event)
