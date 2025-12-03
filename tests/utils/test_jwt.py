"""Tests for the paymcp.utils.jwt module."""

import pytest
import base64
import json
from paymcp.utils.jwt import parse_jwt_paylod


class TestParseJWTPayload:
    """Test the parse_jwt_paylod function."""

    def _create_jwt(self, payload: dict) -> str:
        """Create a simple JWT-like string for testing."""
        header = base64.urlsafe_b64encode(json.dumps({"alg": "HS256"}).encode()).decode().rstrip("=")
        payload_b64 = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
        signature = "fake_signature"
        return f"{header}.{payload_b64}.{signature}"

    def test_parse_valid_jwt_with_sub(self):
        """Test parsing a valid JWT with 'sub' claim."""
        payload = {"sub": "user123", "email": "user@example.com"}
        token = self._create_jwt(payload)

        result = parse_jwt_paylod(token)

        assert result is not None
        assert result["sub"] == "user123"
        assert result["email"] == "user@example.com"

    def test_parse_valid_jwt_with_username(self):
        """Test parsing a valid JWT with 'username' claim."""
        payload = {"sub": "user456", "username": "john_doe"}
        token = self._create_jwt(payload)

        result = parse_jwt_paylod(token)

        assert result is not None
        assert result["sub"] == "user456"
        assert result["username"] == "john_doe"

    def test_parse_empty_token(self):
        """Test parsing an empty token returns None."""
        assert parse_jwt_paylod("") is None
        assert parse_jwt_paylod(None) is None

    def test_parse_invalid_token_format(self):
        """Test parsing an invalid token format returns None."""
        assert parse_jwt_paylod("not.a.valid.token.too.many.parts") is None
        assert parse_jwt_paylod("only_one_part") is None
        assert parse_jwt_paylod("two.parts") is None

    def test_parse_non_string_token(self):
        """Test parsing a non-string token returns None."""
        assert parse_jwt_paylod(123) is None
        assert parse_jwt_paylod(["token"]) is None
        assert parse_jwt_paylod({"token": "value"}) is None

    def test_parse_jwt_with_padding(self):
        """Test parsing a JWT that requires base64 padding."""
        # Create a payload that will require padding when decoded
        payload = {"sub": "a", "email": "x@y.z"}
        token = self._create_jwt(payload)

        result = parse_jwt_paylod(token)

        assert result is not None
        assert result["sub"] == "a"

    def test_parse_jwt_with_additional_claims(self):
        """Test parsing a JWT with additional claims."""
        payload = {
            "sub": "user789",
            "email": "user@example.com",
            "iat": 1234567890,
            "exp": 1234567890 + 3600,
            "custom_claim": "custom_value"
        }
        token = self._create_jwt(payload)

        result = parse_jwt_paylod(token)

        assert result is not None
        assert result["sub"] == "user789"
        assert result["custom_claim"] == "custom_value"

    def test_parse_jwt_with_invalid_base64_payload(self):
        """Test parsing a JWT with invalid base64 in payload returns None."""
        token = "header.!!!invalid_base64!!!.signature"

        result = parse_jwt_paylod(token)

        assert result is None

    def test_parse_jwt_with_invalid_json_payload(self):
        """Test parsing a JWT with invalid JSON in payload returns None."""
        # Create a token with valid base64 but invalid JSON
        header = "header"
        payload_b64 = base64.urlsafe_b64encode(b"not valid json").decode().rstrip("=")
        token = f"{header}.{payload_b64}.signature"

        result = parse_jwt_paylod(token)

        assert result is None
