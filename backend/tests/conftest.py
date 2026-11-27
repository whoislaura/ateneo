import pytest

from app import auth


@pytest.fixture(autouse=True)
def fresh_ai_limiter():
    """Los ids de usuario se repiten entre tests (BD nueva); la cuota no debe arrastrarse."""
    auth.ai_limiter.hits.clear()
