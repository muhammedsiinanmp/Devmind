import pytest

from apps.accounts.url_safety import UnsafeURLError, validate_public_https_url


@pytest.mark.parametrize(
    "url",
    [
        "https://93.184.216.34:99999/v1",  # port out of range
        "https://93.184.216.34:abc/v1",  # non-numeric port
        "https://[::1/v1",  # unterminated IPv6 literal
    ],
)
def test_malformed_url_is_rejected(url):
    with pytest.raises(UnsafeURLError, match="not a valid URL"):
        validate_public_https_url(url)


@pytest.mark.parametrize("url", ["https://", "https:///v1"])
def test_url_without_host_is_rejected(url):
    with pytest.raises(UnsafeURLError, match="must include a host"):
        validate_public_https_url(url)


def test_public_https_ip_is_accepted():
    validate_public_https_url("https://93.184.216.34/v1")
