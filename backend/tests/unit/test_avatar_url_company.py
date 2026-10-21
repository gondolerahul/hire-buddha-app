"""Avatar URLs saved before split mode get the company split mode needs (Phase 14 M2-4)."""
import uuid

from src.common.tenancy.files import _avatar_url_with_company

COMPANY = uuid.UUID("0b7ab269-0cb9-559f-b2d8-ff5607f8ef37")


def test_a_public_file_url_gets_its_company():
    artifact = uuid.uuid4()
    assert _avatar_url_with_company(f"/api/v1/files/{artifact}/public", COMPANY) == \
        f"/api/v1/files/{artifact}/public?company={COMPANY}"
    assert _avatar_url_with_company(f"https://gateway.example/api/v1/files/{artifact}/public", COMPANY) == \
        f"https://gateway.example/api/v1/files/{artifact}/public?company={COMPANY}"


def test_anything_else_is_left_as_it_is():
    artifact = uuid.uuid4()
    for url in (f"/api/v1/files/{artifact}/public?company={COMPANY}",  # already named
                f"/api/v1/files/{artifact}",                            # not a public file
                "/api/v1/files/not-a-uuid/public", "https://cdn.example/me.png", "", None, 42):
        assert _avatar_url_with_company(url, COMPANY) is None
