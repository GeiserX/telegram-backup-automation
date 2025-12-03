"""
Tests for web viewer authentication.
"""
import os
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def auth_env(monkeypatch):
    """Set up authentication environment variables."""
    monkeypatch.setenv("VIEWER_USERNAME", "testuser")
    monkeypatch.setenv("VIEWER_PASSWORD", "testpass123")


@pytest.fixture
def client_with_auth(auth_env):
    """Create a test client with authentication enabled."""
    # Import after setting env vars
    from src.web.main import app
    return TestClient(app)


@pytest.fixture
def client_no_auth(monkeypatch):
    """Create a test client with authentication disabled."""
    monkeypatch.delenv("VIEWER_USERNAME", raising=False)
    monkeypatch.delenv("VIEWER_PASSWORD", raising=False)
    from src.web.main import app
    return TestClient(app)


def test_auth_status_when_disabled(client_no_auth):
    """Test that auth status returns correct values when auth is disabled."""
    response = client_no_auth.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["auth_required"] is False
    assert data["authenticated"] is True


def test_auth_status_when_enabled_no_cookie(client_with_auth):
    """Test that auth status shows unauthenticated when no cookie is present."""
    response = client_with_auth.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["auth_required"] is True
    assert data["authenticated"] is False


def test_login_with_correct_credentials(client_with_auth):
    """Test login with correct credentials sets the cookie."""
    response = client_with_auth.post(
        "/api/login",
        json={"username": "testuser", "password": "testpass123"}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True
    
    # Verify cookie was set with correct name
    assert "viewer_auth" in response.cookies
    cookie_value = response.cookies["viewer_auth"]
    assert cookie_value  # Should be a non-empty hash


def test_login_with_wrong_credentials(client_with_auth):
    """Test login with wrong credentials returns 401."""
    response = client_with_auth.post(
        "/api/login",
        json={"username": "testuser", "password": "wrongpassword"}
    )
    assert response.status_code == 401


def test_login_with_whitespace_credentials(client_with_auth):
    """Test login handles whitespace in credentials correctly."""
    response = client_with_auth.post(
        "/api/login",
        json={"username": " testuser ", "password": " testpass123 "}
    )
    assert response.status_code == 200
    data = response.json()
    assert data["success"] is True


def test_protected_endpoint_with_cookie(client_with_auth):
    """Test accessing protected endpoint with valid cookie."""
    # First login to get the cookie
    login_response = client_with_auth.post(
        "/api/login",
        json={"username": "testuser", "password": "testpass123"}
    )
    assert login_response.status_code == 200
    
    # Now check auth status with the cookie
    response = client_with_auth.get("/api/auth/status")
    assert response.status_code == 200
    data = response.json()
    assert data["authenticated"] is True


def test_cookie_name_consistency(client_with_auth):
    """Test that cookie name matches AUTH_COOKIE_NAME constant."""
    from src.web.main import AUTH_COOKIE_NAME
    
    response = client_with_auth.post(
        "/api/login",
        json={"username": "testuser", "password": "testpass123"}
    )
    
    # Cookie name in response should match the constant
    assert AUTH_COOKIE_NAME in response.cookies
    assert AUTH_COOKIE_NAME == "viewer_auth"
