# Two-Factor Authentication API Reference

Two-factor authentication (2FA) is **mandatory** for every account, current and future. There are two
supported protocols:

- **Email 2FA** — a 6-digit code is emailed to you at login time; you enter it to finish signing in.
- **Authenticator app 2FA (TOTP)** — you scan a QR code (or enter a key manually) into an app like
  Google Authenticator or Microsoft Authenticator once; from then on the app generates a fresh 6-digit
  code every 30 seconds that you enter at login.

You can switch between the two at any time. There is no way to disable 2FA entirely.

Base URL prefix for everything below: `/auth`.

## Conventions

- **Response envelope**: `ApiResponse<T>` — `{ "success": true, "message": "...", "data": {...} }`.
- **Null stripping**: absent/null fields are stripped from JSON responses.
- **Codes**: always exactly 6 digits, expire after `two_factor_challenge_expire_minutes` (10 minutes
  by default), and are single-use.

---

## 1. The mental model

`POST /auth/signup` and `POST /auth/login` **no longer return a token pair directly**. Instead they
return a `status` describing what has to happen next:

| `status`                             | Meaning                                                             |
|---------------------------------------|-----------------------------------------------------------------------|
| `two_factor_setup_required`           | The account has no 2FA method configured yet. Must complete setup.    |
| `two_factor_verification_required`    | 2FA is already configured. Must submit a code to finish logging in.   |
| `success`                             | (Reserved; not currently returned — every account now requires 2FA.) |

Both non-`success` responses include a `challenge` object with a short-lived `challenge_token`
(10-minute expiry). That token — **not** a normal access token — is what you pass to every endpoint
below to prove which account you're completing setup/verification for.

Once setup or verification succeeds, the response is a normal `AuthSessionDTO` — `{ user, tokens }`
— exactly like the old `/auth/login` response used to be.

---

## 2. Signing up

**POST /auth/signup**

Same request body as before. The response is now always a setup challenge:

```json
{
  "success": true,
  "message": "Account created. Set up two-factor authentication to continue.",
  "data": {
    "status": "two_factor_setup_required",
    "challenge": { "challenge_token": "eyJhbGciOi..." }
  }
}
```

Proceed to §4 (Forced setup) using this `challenge_token`.

---

## 3. Logging in

**POST /auth/login**

Same request body as before (`identifier`, `password`, `keep_logged_in`). Two possible outcomes:

**Account has no 2FA method yet** (e.g. an existing account from before this feature shipped):

```json
{
  "data": {
    "status": "two_factor_setup_required",
    "challenge": { "challenge_token": "eyJhbGciOi..." }
  }
}
```

Proceed to §4.

**Account already has 2FA configured:**

```json
{
  "data": {
    "status": "two_factor_verification_required",
    "challenge": { "challenge_token": "eyJhbGciOi...", "method": "EMAIL" }
  }
}
```

`method` is `EMAIL` or `TOTP`. If it's `EMAIL`, a code has already been sent to the account's email
as part of this call — proceed to §5. If it's `TOTP`, open your authenticator app and proceed to §5
directly (nothing is sent).

`keep_logged_in` is remembered across the challenge — the token pair you eventually receive from
`/auth/2fa/login/verify` will already reflect it.

---

## 4. Forced setup (new signup, or an existing account with no 2FA yet)

All of these take the `challenge_token` from §2/§3 in the body — no `Authorization` header.

### Authenticator app (TOTP)

**POST /auth/2fa/setup/totp/start** — `{ "challenge_token": "..." }`

```json
{
  "data": {
    "secret": "6TYOVT4C7EKEB7VHP5LCUNKGBMUI2MTC",
    "otpauth_url": "otpauth://totp/Social%20Workers:jane%40example.com?secret=...&issuer=Social%20Workers",
    "qr_code_data_uri": "data:image/png;base64,iVBORw0KGgo..."
  }
}
```

Render `qr_code_data_uri` directly in an `<img src="...">` for the user to scan, and show `secret` as
the "can't scan? enter this key manually" fallback. Calling `start` again before `confirm` replaces
the pending secret (e.g. if the user backs out and retries).

**POST /auth/2fa/setup/totp/confirm** — `{ "challenge_token": "...", "code": "123456" }`

Enter the 6-digit code the app is currently showing. On success this both enables TOTP 2FA **and**
completes the signup/login, returning a full `AuthSessionDTO` (`{ user, tokens }`).

### Email

**POST /auth/2fa/setup/email/start** — `{ "challenge_token": "..." }` — sends a code to the account's
email.

**POST /auth/2fa/setup/email/confirm** — `{ "challenge_token": "...", "code": "123456" }` — on
success, enables email 2FA and completes the signup/login, returning `AuthSessionDTO`.

---

## 5. Verifying at login (account already has 2FA configured)

**POST /auth/2fa/login/verify** — `{ "challenge_token": "...", "code": "123456" }`

Works for either method (email code or TOTP app code, whichever `challenge.method` said). On success,
returns `AuthSessionDTO`.

**POST /auth/2fa/login/resend** — `{ "challenge_token": "..." }` — email method only; issues a new
code and invalidates the previous one.

---

## 6. Your security protocol (profile + switching)

**GET /users/me** (existing endpoint, `Authorization: Bearer <access_token>`) now includes:

```json
{
  "two_factor_enabled": true,
  "two_factor_method": "TOTP"
}
```

**GET /auth/2fa/status** — the same two fields on their own, if you don't need the rest of the
profile.

To switch protocol while already logged in, use the mirror of the §4 setup endpoints, but
authenticated instead of challenge-token-based:

- **POST /auth/2fa/totp/start** → same shape as §4's TOTP start.
- **POST /auth/2fa/totp/confirm** — `{ "code": "123456" }` → `{ "two_factor_enabled": true, "two_factor_method": "TOTP" }`.
- **POST /auth/2fa/email/start** → sends a code to your email.
- **POST /auth/2fa/email/confirm** — `{ "code": "123456" }` → `{ "two_factor_enabled": true, "two_factor_method": "EMAIL" }`.

Switching methods takes effect immediately (no re-login required) and does not need the old method's
code — only your existing access token and a successful confirmation of the new method. Switching
away from TOTP clears the stored authenticator secret.

---

## 7. Error cases

| Situation                                              | Response                                      |
|----------------------------------------------------------|------------------------------------------------|
| Wrong/expired 6-digit code                                | `400` "Invalid or expired code" / "Invalid authentication code" |
| Expired or malformed `challenge_token`                    | `401` "Invalid or expired verification session" |
| `/auth/2fa/login/resend` called for a TOTP account         | `400` "Resend is only available for email verification" |
| TOTP `confirm` called before `start`                       | `400` "Start TOTP setup first"                |
