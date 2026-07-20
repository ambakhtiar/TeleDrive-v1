"""Assemble the concrete UploaderService from its feature mixins.

Each feature lives in its own module so it's easy to find:
  auth.py         — phone/OTP/2FA login, logout
  groups.py       — groups & topics
  scanning.py     — folder scan, routing, enqueue
  uploading.py    — upload workers, per-file upload, queue controls
  downloading.py  — download / restore
  reports.py      — daily/manual reports
  base.py         — shared state, events, client lifecycle, start/stop
"""
from app.services.base import UploaderBase
from app.services.auth import AuthMixin
from app.services.groups import GroupsMixin
from app.services.scanning import ScanMixin
from app.services.uploading import UploadMixin
from app.services.downloading import DownloadMixin
from app.services.reports import ReportMixin
from app.services.maintenance import MaintenanceMixin


class UploaderService(
    AuthMixin,
    GroupsMixin,
    ScanMixin,
    UploadMixin,
    DownloadMixin,
    ReportMixin,
    MaintenanceMixin,
    UploaderBase,
):
    """Single-user uploader. Started once from the FastAPI lifespan."""


__all__ = ["UploaderService"]
