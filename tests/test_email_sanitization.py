"""
Unit tests verifying strict email extraction sanitization (Section 2.1).
Ensures prose false-positives, asset filenames, rejected TLD words, and phone numbers are rejected.
"""

from agent.web_enricher import is_valid_email


def test_rejects_prose_words_as_tlds():
    assert not is_valid_email("me@ease.they")
    assert not is_valid_email("and@ease.the")
    assert not is_valid_email("feel@home.our")
    assert not is_valid_email("more@ease.book")
    assert not is_valid_email("info@ease.page")
    assert not is_valid_email("help@home.post")
    assert not is_valid_email("contact@site.work")


def test_rejects_asset_filenames_and_phone_domains():
    assert not is_valid_email("image@2x.png")
    assert not is_valid_email("logo@3x.webp")
    assert not is_valid_email("icon@2x.jpg")
    assert not is_valid_email("reached@708-633-9614.reach")
    assert not is_valid_email("call@123-456-7890.call")


def test_rejects_junk_and_placeholder_domains():
    assert not is_valid_email("user@sentry.io")
    assert not is_valid_email("test@wixpress.com")
    assert not is_valid_email("sample@example.com")
    assert not is_valid_email("youremail@domain.com")


def test_accepts_valid_business_emails():
    assert is_valid_email("service@pipeswires.com")
    assert is_valid_email("contact@mobiledieseltruckrepair.net")
    assert is_valid_email("info@psiplumbing.com")
    assert is_valid_email("drsmith@vikaradental.care")
    assert is_valid_email("support@agency.co")
    assert is_valid_email("admin@projectsplans.io")
    assert is_valid_email("hello@austindental.dental")
    assert is_valid_email("office@chicagoplumbing.us")

