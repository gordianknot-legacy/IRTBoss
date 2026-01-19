"""
Tests for API endpoints.
"""

import pytest
from fastapi.testclient import TestClient
from io import BytesIO

from app.main import app


@pytest.fixture
def client():
    """Create test client."""
    return TestClient(app)


class TestHealthCheck:
    """Tests for health check endpoint."""

    def test_health_check(self, client):
        """Health check should return healthy status."""
        response = client.get("/api/v1/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"
        assert "version" in data


class TestRootEndpoint:
    """Tests for root endpoint."""

    def test_root(self, client):
        """Root should return API info."""
        response = client.get("/")
        assert response.status_code == 200
        data = response.json()
        assert data["name"] == "IRTBoss"
        assert "version" in data


class TestProjectEndpoints:
    """Tests for project management endpoints."""

    def test_create_project(self, client):
        """Should create a new project."""
        response = client.post(
            "/api/v1/projects",
            json={
                "name": "Test Project",
                "description": "A test project",
                "stakes_level": "medium",
                "intended_use": "research",
            },
        )
        assert response.status_code == 201
        data = response.json()
        assert data["name"] == "Test Project"
        assert "id" in data

    def test_create_project_minimal(self, client):
        """Should create project with minimal data."""
        response = client.post(
            "/api/v1/projects",
            json={"name": "Minimal Project"},
        )
        assert response.status_code == 201

    def test_create_project_invalid(self, client):
        """Should reject invalid project data."""
        response = client.post(
            "/api/v1/projects",
            json={"name": ""},  # Empty name
        )
        assert response.status_code == 422

    def test_list_projects(self, client):
        """Should list projects."""
        response = client.get("/api/v1/projects")
        assert response.status_code == 200
        assert isinstance(response.json(), list)


class TestUploadEndpoint:
    """Tests for data upload endpoint."""

    def test_upload_csv(self, client, sample_dichotomous_data):
        """Should accept CSV upload."""
        # First create a project
        project_response = client.post(
            "/api/v1/projects",
            json={"name": "Upload Test"},
        )
        project_id = project_response.json()["id"]

        # Create CSV content
        csv_content = sample_dichotomous_data.to_csv(index=False).encode()

        response = client.post(
            f"/api/v1/projects/{project_id}/upload",
            files={"file": ("test.csv", BytesIO(csv_content), "text/csv")},
        )
        assert response.status_code == 200
        data = response.json()
        assert "is_valid" in data

    def test_upload_non_csv(self, client):
        """Should reject non-CSV files."""
        project_response = client.post(
            "/api/v1/projects",
            json={"name": "Upload Test"},
        )
        project_id = project_response.json()["id"]

        response = client.post(
            f"/api/v1/projects/{project_id}/upload",
            files={"file": ("test.txt", BytesIO(b"not csv"), "text/plain")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
        assert any(m["code"] == "INVALID_FILE_TYPE" for m in data["messages"])

    def test_upload_empty_file(self, client):
        """Should reject empty files."""
        project_response = client.post(
            "/api/v1/projects",
            json={"name": "Upload Test"},
        )
        project_id = project_response.json()["id"]

        response = client.post(
            f"/api/v1/projects/{project_id}/upload",
            files={"file": ("empty.csv", BytesIO(b""), "text/csv")},
        )
        assert response.status_code == 200
        data = response.json()
        assert data["is_valid"] is False
