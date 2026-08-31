"""MFA/TOTP end to end (SECURITY.md §12).

Each test pins a security property, not just the happy path — the interesting
failures here are a wrong code succeeding, a challenge token being replayable,
or a stolen access token alone being enough to strip a user's second factor.
"""

import pyotp

from tests.integration.conftest import PASSWORD, register_and_login


async def _enable_mfa(client, headers):
    setup = await client.post("/api/v1/auth/mfa/setup", headers=headers)
    assert setup.status_code == 200, setup.text
    secret = setup.json()["secret"]
    code = pyotp.TOTP(secret).now()
    enabled = await client.post("/api/v1/auth/mfa/enable", headers=headers, json={"code": code})
    assert enabled.status_code == 200, enabled.text
    return secret, enabled.json()["recovery_codes"]


class TestSetupAndEnable:
    async def test_setup_returns_a_pending_secret_that_does_not_yet_gate_login(
        self, client, email
    ) -> None:
        headers, _ = await register_and_login(client, email)
        setup = await client.post("/api/v1/auth/mfa/setup", headers=headers)
        assert setup.status_code == 200
        body = setup.json()
        assert len(body["secret"]) >= 16
        assert body["otpauth_uri"].startswith("otpauth://totp/")

        # A secret nobody has proven they can produce a code for must not gate
        # login — otherwise a setup call alone (no `enable`) would lock out the
        # real user, or an attacker's stray setup call could do it to someone
        # else's session-adjacent state.
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200
        assert "access_token" in login.json()

    async def test_enable_rejects_an_incorrect_code(self, client, email) -> None:
        headers, _ = await register_and_login(client, email)
        await client.post("/api/v1/auth/mfa/setup", headers=headers)
        response = await client.post(
            "/api/v1/auth/mfa/enable", headers=headers, json={"code": "000000"}
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "MFA_CODE_INVALID"

    async def test_enable_without_setup_is_rejected(self, client, email) -> None:
        headers, _ = await register_and_login(client, email)
        response = await client.post(
            "/api/v1/auth/mfa/enable", headers=headers, json={"code": "123456"}
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "MFA_SETUP_REQUIRED"

    async def test_enable_with_the_right_code_mints_recovery_codes(self, client, email) -> None:
        headers, _ = await register_and_login(client, email)
        _, recovery_codes = await _enable_mfa(client, headers)
        assert len(recovery_codes) == 10
        assert len(set(recovery_codes)) == 10  # All distinct.


class TestLoginChallenge:
    async def test_login_after_enabling_returns_a_challenge_not_a_session(
        self, client, email
    ) -> None:
        headers, _ = await register_and_login(client, email)
        await _enable_mfa(client, headers)
        # `register_and_login` above already opened one real session and left
        # its cookie in the jar — the property under test is that *this* call
        # does not touch it, not that no cookie has ever existed.
        cookie_before = client.cookies.get("nexora_rt")

        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200
        body = login.json()
        assert body["mfa_required"] is True
        assert "challenge_token" in body
        assert "access_token" not in body
        assert client.cookies.get("nexora_rt") == cookie_before

    async def test_correct_totp_code_completes_the_login(self, client, email) -> None:
        headers, _ = await register_and_login(client, email)
        secret, _ = await _enable_mfa(client, headers)
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        challenge_token = login.json()["challenge_token"]

        response = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={"challenge_token": challenge_token, "code": pyotp.TOTP(secret).now()},
        )
        assert response.status_code == 200, response.text
        assert "access_token" in response.json()
        assert client.cookies.get("nexora_rt")

    async def test_wrong_code_does_not_open_a_session(self, client, email) -> None:
        headers, _ = await register_and_login(client, email)
        await _enable_mfa(client, headers)
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        challenge_token = login.json()["challenge_token"]
        cookie_before = client.cookies.get("nexora_rt")

        response = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={"challenge_token": challenge_token, "code": "000000"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "MFA_CODE_INVALID"
        assert client.cookies.get("nexora_rt") == cookie_before

    async def test_a_challenge_token_cannot_be_replayed(self, client, email) -> None:
        """The property that makes theft of a used challenge token worthless —
        it must already be dead by the time anyone could reuse it."""
        headers, _ = await register_and_login(client, email)
        secret, _ = await _enable_mfa(client, headers)
        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        challenge_token = login.json()["challenge_token"]
        code = pyotp.TOTP(secret).now()

        first = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={"challenge_token": challenge_token, "code": code},
        )
        assert first.status_code == 200

        replay = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={"challenge_token": challenge_token, "code": code},
        )
        assert replay.status_code == 401
        assert replay.json()["error"]["code"] == "MFA_CHALLENGE_INVALID"

    async def test_an_unknown_challenge_token_is_rejected(self, client) -> None:
        response = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={"challenge_token": "x" * 32, "code": "123456"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "MFA_CHALLENGE_INVALID"

    async def test_a_recovery_code_completes_the_challenge_exactly_once(
        self, client, email
    ) -> None:
        headers, _ = await register_and_login(client, email)
        _, recovery_codes = await _enable_mfa(client, headers)
        recovery_code = recovery_codes[0]

        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        response = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={
                "challenge_token": login.json()["challenge_token"],
                "code": recovery_code,
            },
        )
        assert response.status_code == 200, response.text

        # The same code must not work again from a fresh challenge.
        second_login = await client.post(
            "/api/v1/auth/login", json={"email": email, "password": PASSWORD}
        )
        replay = await client.post(
            "/api/v1/auth/mfa/challenge",
            json={
                "challenge_token": second_login.json()["challenge_token"],
                "code": recovery_code,
            },
        )
        assert replay.status_code == 401


class TestDisable:
    async def test_disable_requires_the_correct_password(self, client, email) -> None:
        headers, _ = await register_and_login(client, email)
        secret, _ = await _enable_mfa(client, headers)
        response = await client.post(
            "/api/v1/auth/mfa/disable",
            headers=headers,
            json={"password": "definitely-the-wrong-password", "code": pyotp.TOTP(secret).now()},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "INVALID_CREDENTIALS"

    async def test_disable_requires_a_valid_code_not_just_the_password(self, client, email) -> None:
        """A stolen access token plus a known password must still not be
        enough — the code proves possession of the second factor itself."""
        headers, _ = await register_and_login(client, email)
        await _enable_mfa(client, headers)
        response = await client.post(
            "/api/v1/auth/mfa/disable",
            headers=headers,
            json={"password": PASSWORD, "code": "000000"},
        )
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "MFA_CODE_INVALID"

    async def test_disabling_removes_the_login_challenge(self, client, email) -> None:
        headers, _ = await register_and_login(client, email)
        secret, _ = await _enable_mfa(client, headers)
        disabled = await client.post(
            "/api/v1/auth/mfa/disable",
            headers=headers,
            json={"password": PASSWORD, "code": pyotp.TOTP(secret).now()},
        )
        assert disabled.status_code == 204

        login = await client.post("/api/v1/auth/login", json={"email": email, "password": PASSWORD})
        assert login.status_code == 200
        assert "access_token" in login.json()
