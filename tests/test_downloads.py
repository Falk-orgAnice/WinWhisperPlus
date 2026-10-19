"""Real TLS handshakes: verified HTTPS, redirects, native Windows + in-memory CAs."""
import contextlib
from datetime import datetime, timezone
import http.server
from pathlib import Path
import ssl
import sys
import threading
import urllib.error

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID, ExtendedKeyUsageOID
import pytest

from utils import downloads


@pytest.fixture
def https_server(tmp_path, monkeypatch):
    monkeypatch.setenv("no_proxy", "localhost,127.0.0.1")
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca_name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "WinWhisperPlus test CA")])
    ca = (x509.CertificateBuilder().subject_name(ca_name).issuer_name(ca_name)
          .public_key(ca_key.public_key()).serial_number(x509.random_serial_number())
          .not_valid_before(datetime(2020, 1, 1, tzinfo=timezone.utc))
          .not_valid_after(datetime(2060, 1, 1, tzinfo=timezone.utc))
          .add_extension(x509.BasicConstraints(ca=True, path_length=1), critical=True)
          .add_extension(x509.KeyUsage(digital_signature=True, content_commitment=False, key_encipherment=False,
              data_encipherment=False, key_agreement=False, key_cert_sign=True, crl_sign=True,
              encipher_only=False, decipher_only=False), critical=True)
          .add_extension(x509.SubjectKeyIdentifier.from_public_key(ca_key.public_key()), critical=False)
          .sign(ca_key, hashes.SHA256()))
    ca_path = tmp_path / "ca.pem"
    ca_path.write_bytes(ca.public_bytes(serialization.Encoding.PEM))

    @contextlib.contextmanager
    def serve(*, expired=False):
        key = ec.generate_private_key(ec.SECP256R1())
        leaf = (x509.CertificateBuilder()
                .subject_name(x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "localhost")]))
                .issuer_name(ca.subject).public_key(key.public_key()).serial_number(x509.random_serial_number())
                .not_valid_before(datetime(2020, 1, 1, tzinfo=timezone.utc))
                .not_valid_after(datetime(2021 if expired else 2045, 1, 1, tzinfo=timezone.utc))
                .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
                .add_extension(x509.SubjectAlternativeName([x509.DNSName("localhost")]), critical=False)
                .add_extension(x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False)
                .add_extension(x509.AuthorityKeyIdentifier.from_issuer_public_key(ca_key.public_key()), critical=False)
                .sign(ca_key, hashes.SHA256()))
        certificate = tmp_path / "server.pem"
        private_key = tmp_path / "server-key.pem"
        certificate.write_bytes(leaf.public_bytes(serialization.Encoding.PEM) + ca.public_bytes(serialization.Encoding.PEM))
        private_key.write_bytes(key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()))
        class Handler(http.server.BaseHTTPRequestHandler):
            def do_GET(self):
                if self.path in {"/redirect", "/downgrade"}:
                    self.send_response(302)
                    scheme = "http" if self.path == "/downgrade" else "https"
                    self.send_header("Location", f"{scheme}://localhost:{self.server.server_port}/model")
                    self.end_headers()
                else:
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(b"verified model")
            def log_message(self, *_args):
                pass
        server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(certificate, private_key)
        server.socket = context.wrap_socket(server.socket, server_side=True)
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            yield f"https://localhost:{server.server_port}", ca_path
        finally:
            server.shutdown()
            server.server_close()
            worker.join(timeout=3)
    return serve


def trusted_context(ca, monkeypatch):
    context = downloads.create_download_context()
    context.load_verify_locations(cafile=str(ca))
    monkeypatch.setattr(downloads, "create_download_context", lambda: context)
    return context


def test_factory_requires_valid_certificate_and_hostname():
    context = downloads.create_download_context()
    assert context.verify_mode == ssl.CERT_REQUIRED
    assert context.check_hostname
    assert context.minimum_version >= ssl.TLSVersion.TLSv1_2


def test_verified_https_and_redirect(https_server, monkeypatch):
    with https_server() as (url, ca):
        trusted_context(ca, monkeypatch)
        with downloads.open_https(url + "/redirect", timeout=3) as response:
            assert response.read() == b"verified model"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows CryptoAPI chain building")
def test_memory_ca_fallback_when_windows_roots_are_missing(https_server, monkeypatch):
    from truststore import _windows
    verify = _windows._get_and_verify_cert_chain
    attempts = []
    def empty_windows_store(*args, **kwargs):
        attempts.append(args[1] is None)
        if args[1] is None:
            raise ssl.SSLCertVerificationError("simulated empty Windows root store")
        return verify(*args, **kwargs)
    monkeypatch.setattr(_windows, "_get_and_verify_cert_chain", empty_windows_store)
    with https_server() as (url, ca):
        trusted_context(ca, monkeypatch)
        with downloads.open_https(url + "/model", timeout=3) as response:
            assert response.read() == b"verified model"
    assert True in attempts and False in attempts


def test_untrusted_certificate_is_rejected(https_server):
    with https_server() as (url, _):
        with pytest.raises(downloads.DownloadCertificateError) as error:
            downloads.open_https(url, timeout=3)
        assert error.value.host == "localhost"


@pytest.mark.parametrize("invalid", ["hostname", "expired"])
def test_invalid_certificate_is_rejected_with_trusted_ca(invalid, https_server, monkeypatch):
    with https_server(expired=invalid == "expired") as (url, ca):
        trusted_context(ca, monkeypatch)
        if invalid == "hostname":
            url = url.replace("localhost", "127.0.0.1")
        with pytest.raises(downloads.DownloadCertificateError):
            downloads.open_https(url, timeout=3)


def test_http_downgrade_is_rejected(https_server, monkeypatch):
    with https_server() as (url, ca):
        trusted_context(ca, monkeypatch)
        with pytest.raises(urllib.error.URLError, match="requires HTTPS"):
            downloads.open_https(url + "/downgrade", timeout=3)


def test_plain_http_is_rejected_before_network():
    with pytest.raises(ValueError, match="require HTTPS"):
        downloads.open_https("http://localhost/model")


def test_non_certificate_failure_is_preserved(monkeypatch):
    class Offline:
        def open(self, *_args, **_kwargs):
            raise urllib.error.URLError("offline")
    monkeypatch.setattr(downloads.urllib.request, "build_opener", lambda *_args: Offline())
    with pytest.raises(urllib.error.URLError, match="offline"):
        downloads.open_https("https://example.test/model")
