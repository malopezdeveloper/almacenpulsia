from __future__ import annotations

import shutil

from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings
from PySide6.QtWebEngineWidgets import QWebEngineView

from app_config import WEB_PROFILE_PATH


class PulsiaWebPage(QWebEnginePage):
    """Normal HTTPS validation is used; the portable client installs the server CA."""
    pass


def purge_persistent_profile() -> None:
    if WEB_PROFILE_PATH.exists():
        shutil.rmtree(WEB_PROFILE_PATH, ignore_errors=True)


def create_web_view(keep_session: bool, parent=None) -> QWebEngineView:
    if keep_session:
        WEB_PROFILE_PATH.mkdir(parents=True, exist_ok=True)
        profile = QWebEngineProfile("PulsiaPersistent", parent)
        profile.setPersistentStoragePath(str(WEB_PROFILE_PATH))
        profile.setCachePath(str(WEB_PROFILE_PATH / "cache"))
        profile.setPersistentCookiesPolicy(
            QWebEngineProfile.PersistentCookiesPolicy.ForcePersistentCookies
        )
    else:
        profile = QWebEngineProfile(parent)

    settings = profile.settings()
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.LocalStorageEnabled, True)
    settings.setAttribute(QWebEngineSettings.WebAttribute.JavascriptCanOpenWindows, True)

    page = PulsiaWebPage(profile, parent)
    view = QWebEngineView(parent)
    view.setPage(page)
    return view
