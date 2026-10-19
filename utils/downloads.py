"""Verified HTTPS for model downloads, independent of a pre-populated VM store."""
from __future__ import annotations

import ssl
import urllib.error
import urllib.parse
import urllib.request

import certifi
import truststore


class DownloadCertificateError(RuntimeError):
    def __init__(self, host: str):
        self.host = host
        super().__init__(
            f"Das HTTPS-Zertifikat für {host} konnte nicht geprüft werden. "
            "Bitte Datum/Uhrzeit der VM und gegebenenfalls den Firmenproxy prüfen. "
            "Die Zertifikatsprüfung bleibt aktiviert."
        )


class _HttpsOnlyRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, fp, code, message, headers, newurl):
        if urllib.parse.urlsplit(newurl).scheme != "https":
            raise urllib.error.URLError("Model download redirect requires HTTPS")
        return super().redirect_request(request, fp, code, message, headers, newurl)


def create_download_context():
    # CryptoAPI on Windows builds chains using the current user's Windows trust
    # settings and can retrieve missing intermediates. Mozilla roots are added
    # in memory so a fresh/offline-provisioned Windows image can also verify
    # public HTTPS servers. Nothing is installed into a Windows certificate store.
    context = truststore.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = ssl.TLSVersion.TLSv1_2
    context.load_verify_locations(cafile=certifi.where())
    context.verify_mode = ssl.CERT_REQUIRED
    context.check_hostname = True
    return context


def open_https(url: str, *, timeout: float = 30):
    host = urllib.parse.urlsplit(url).hostname or "?"
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ValueError("Model downloads require HTTPS")
    try:
        opener = urllib.request.build_opener(
            urllib.request.HTTPSHandler(context=create_download_context()), _HttpsOnlyRedirect()
        )
        return opener.open(url, timeout=timeout)
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise DownloadCertificateError(host) from exc
        raise
    except ssl.SSLCertVerificationError as exc:
        raise DownloadCertificateError(host) from exc
