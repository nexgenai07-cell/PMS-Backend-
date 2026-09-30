"""
Signed token generator for email verification.

Reuses Django's battle-tested PasswordResetTokenGenerator, which provides:
- Salted HMAC signed with SECRET_KEY (unforgeable)
- Timestamp encoded in base36 (expires after PASSWORD_RESET_TIMEOUT)
- Automatic invalidation when the user's password or last_login changes
- Single-use (same mechanism Django uses for password resets)

We only need a distinct `key_salt` so email-verification tokens cannot be
reused as password-reset tokens (and vice versa).
"""
from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "pms_app.tokens.EmailVerificationTokenGenerator"


email_verification_token = EmailVerificationTokenGenerator()