"""Canonical API route constants.

Routers define sub-paths relative to their prefix; this module provides the
full paths that clients and tests use.  One source of truth — update here
when a path changes.
"""

V1 = "/v1"

# Auth
AUTH_LOGIN = f"{V1}/auth/login"
AUTH_LOGOUT = f"{V1}/auth/logout"
AUTH_ME = f"{V1}/auth/me"
AUTH_PASSWORD = f"{V1}/auth/password"
AUTH_REFRESH = f"{V1}/auth/refresh"
AUTH_REGISTER = f"{V1}/auth/register"

# Admin
ADMIN_STATS = f"{V1}/admin/stats"
ADMIN_ERRORS = f"{V1}/admin/errors"
ADMIN_EDIT_JOBS = f"{V1}/admin/edit-jobs"
ADMIN_USERS = f"{V1}/admin/users"
ADMIN_IMPORTS = f"{V1}/admin/imports"


def admin_user_path(user_id: str) -> str:
    return f"{ADMIN_USERS}/{user_id}"


# Library
LIBRARY = f"{V1}/library"
LIBRARY_BULK = f"{LIBRARY}/bulk"
LIBRARY_OFFLINE = f"{LIBRARY}/offline"
LIBRARY_PUBLISH = f"{LIBRARY}/publish"


def library_song_path(song_id: str) -> str:
    return f"{LIBRARY}/{song_id}"


def library_position_path(song_id: str) -> str:
    return f"{LIBRARY}/{song_id}/position"


def library_offline_path(song_id: str) -> str:
    return f"{LIBRARY}/offline/{song_id}"


def library_restore_path(song_id: str) -> str:
    return f"{LIBRARY}/{song_id}/restore"


# Songs
SONGS = f"{V1}/songs/"
SONGS_LIBRARY = f"{V1}/songs/library"


def song_path(song_id: str) -> str:
    return f"{V1}/songs/{song_id}"


def song_play_path(song_id: str) -> str:
    return f"{V1}/songs/{song_id}/play"


def song_artwork_path(song_id: str, size: str | int = "") -> str:
    base = f"{V1}/songs/{song_id}/artwork"
    return f"{base}/{size}" if size else base


def songs_explore_path(window: str) -> str:
    return f"{V1}/songs/explore?window={window}"


# Download
DOWNLOAD = f"{V1}/download"


def download_path(song_id: str) -> str:
    return f"{DOWNLOAD}/{song_id}"


# Properties
PROPERTIES = f"{V1}/properties"
PROPERTIES_ITUNES = f"{V1}/properties/itunes"


def properties_path(song_id: str) -> str:
    return f"{PROPERTIES}/{song_id}"


# Player
PLAYER_STATE = f"{V1}/player/state"
PLAYER_QUEUE = f"{V1}/player/queue"
PLAYER_QUEUE_REORDER = f"{V1}/player/queue/reorder"


def player_queue_song_path(song_id: str) -> str:
    return f"{PLAYER_QUEUE}/{song_id}"


# Playlists
PLAYLISTS = f"{V1}/playlists"


def playlist_path(playlist_id: str) -> str:
    return f"{PLAYLISTS}/{playlist_id}"


def playlist_songs_path(playlist_id: str) -> str:
    return f"{PLAYLISTS}/{playlist_id}/songs"


def playlist_song_path(playlist_id: str, song_id: str) -> str:
    return f"{PLAYLISTS}/{playlist_id}/songs/{song_id}"


def playlist_songs_bulk_path(playlist_id: str) -> str:
    return f"{PLAYLISTS}/{playlist_id}/songs/bulk"


# Import
IMPORT = f"{V1}/import"


def import_job_path(job_id: str) -> str:
    return f"{IMPORT}/{job_id}"


# Edit
def edit_song_path(song_id: str) -> str:
    return f"{V1}/edit/songs/{song_id}"


def edit_draft_path(song_id: str) -> str:
    return f"{V1}/edit/songs/{song_id}/draft"


EDIT_DRAFTS = f"{V1}/edit/drafts"


def edit_job_path(job_id: str) -> str:
    return f"{V1}/edit/jobs/{job_id}"


# Share
def share_song_path(song_id: str) -> str:
    return f"{V1}/share/songs/{song_id}"


def share_info_path(token: str) -> str:
    return f"{V1}/share/{token}/info"


def share_download_path(token: str) -> str:
    return f"{V1}/share/{token}/download"


# Health / Version
HEALTH = f"{V1}/health"
VERSION = f"{V1}/version"
