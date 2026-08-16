import logging
import os
from urllib.parse import urlencode

from dotenv import load_dotenv
import requests
from requests_oauthlib import OAuth1Session

load_dotenv()

logger = logging.getLogger(__name__)

ZOTERO_CLIENT_KEY = os.getenv("ZOTERO_CLIENT_KEY")
ZOTERO_CLIENT_SECRET = os.getenv("ZOTERO_CLIENT_SECRET")
ZOTERO_REDIRECT_URI = os.getenv("ZOTERO_REDIRECT_URI")

REQUEST_TOKEN_URL = "https://www.zotero.org/oauth/request"
AUTHORIZE_URL = "https://www.zotero.org/oauth/authorize"
ACCESS_TOKEN_URL = "https://www.zotero.org/oauth/access"
OAUTH_TIMEOUT = (5, 15)

DEFAULT_PERMISSIONS: dict[str, str] = {
    "library_access": "1",
    "notes_access": "1",
    "write_access": "0",
    "name": "Scholens",
    "all_groups": "none",
}


class ZoteroAccessTokenResult:
    def __init__(self, zotero_user_id: str, api_key: str):
        self.zotero_user_id = zotero_user_id
        self.api_key = api_key


class ZoteroRequestTokenResult:
    def __init__(self, oauth_token: str, oauth_token_secret: str):
        self.oauth_token = oauth_token
        self.oauth_token_secret = oauth_token_secret


def _close_oauth_response(
    response: requests.Response,
    *args: object,
    **kwargs: object,
) -> requests.Response:
    """Cache the small token body, then release its connection immediately."""
    del args, kwargs
    response.content
    response.close()
    return response


class ZoteroAuthClient:
    """Zotero OAuth 1.0a client for API key exchange."""

    def __init__(self) -> None:
        self.client_key = ZOTERO_CLIENT_KEY
        self.client_secret = ZOTERO_CLIENT_SECRET
        self.redirect_uri = ZOTERO_REDIRECT_URI

    def _oauth_session(
        self,
        *,
        resource_owner_key: str | None = None,
        resource_owner_secret: str | None = None,
        verifier: str | None = None,
    ) -> OAuth1Session:
        session = OAuth1Session(
            self.client_key,
            client_secret=self.client_secret,
            callback_uri=self.redirect_uri,
            resource_owner_key=resource_owner_key,
            resource_owner_secret=resource_owner_secret,
            verifier=verifier,
        )
        session.trust_env = False
        return session

    def get_request_token(self) -> ZoteroRequestTokenResult | None:
        if not self.client_key or not self.client_secret or not self.redirect_uri:
            logger.error("zotero.oauth.credentials_missing")
            return None

        oauth = self._oauth_session()
        try:
            token_data = oauth.fetch_request_token(
                REQUEST_TOKEN_URL,
                timeout=OAUTH_TIMEOUT,
                allow_redirects=False,
                hooks={"response": _close_oauth_response},
            )
            oauth_token = token_data.get("oauth_token")
            oauth_token_secret = token_data.get("oauth_token_secret")
            if not oauth_token or not oauth_token_secret:
                logger.error("zotero.oauth.request_token_invalid")
                return None
            return ZoteroRequestTokenResult(
                oauth_token=oauth_token,
                oauth_token_secret=oauth_token_secret,
            )
        except Exception as exc:
            logger.error(
                "zotero.oauth.request_token.failed",
                extra={"exception_type": type(exc).__name__},
            )
            return None
        finally:
            oauth.close()

    def get_authorize_url(
        self,
        oauth_token: str,
        permissions: dict[str, str] | None = None,
    ) -> str:
        params = {"oauth_token": oauth_token}
        params.update(permissions or DEFAULT_PERMISSIONS)
        return f"{AUTHORIZE_URL}?{urlencode(params)}"

    def get_access_token(
        self,
        request_token: str,
        request_token_secret: str,
        verifier: str,
    ) -> ZoteroAccessTokenResult | None:
        if not self.client_key or not self.client_secret:
            logger.error("zotero.oauth.credentials_missing")
            return None

        oauth = self._oauth_session(
            resource_owner_key=request_token,
            resource_owner_secret=request_token_secret,
            verifier=verifier,
        )
        try:
            token_data = oauth.fetch_access_token(
                ACCESS_TOKEN_URL,
                timeout=OAUTH_TIMEOUT,
                allow_redirects=False,
                hooks={"response": _close_oauth_response},
            )
            zotero_user_id = token_data.get("userID")
            api_key = token_data.get("oauth_token_secret")
            if not zotero_user_id or not api_key:
                logger.error("zotero.oauth.access_token_invalid")
                return None
            return ZoteroAccessTokenResult(
                zotero_user_id=str(zotero_user_id),
                api_key=str(api_key),
            )
        except Exception as exc:
            logger.error(
                "zotero.oauth.access_token.failed",
                extra={"exception_type": type(exc).__name__},
            )
            return None
        finally:
            oauth.close()


zotero_auth_client = ZoteroAuthClient()
