"""
Signed token generators for email verification and password change.

Both reuse Django's battle-tested PasswordResetTokenGenerator, which provides:
- Salted HMAC signed with SECRET_KEY (unforgeable)
- Timestamp encoded in base36 (expires after PASSWORD_RESET_TIMEOUT)
- Automatic invalidation when the user's password or last_login changes
- Single-use (same mechanism Django uses for password resets)

We use distinct `key_salt` values so a verification token cannot be
replayed as a password-change token and vice versa.
"""
from django.contrib.auth.tokens import PasswordResetTokenGenerator


class EmailVerificationTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "pms_app.tokens.EmailVerificationTokenGenerator"


class PasswordChangeTokenGenerator(PasswordResetTokenGenerator):
    key_salt = "pms_app.tokens.PasswordChangeTokenGenerator"


email_verification_token = EmailVerificationTokenGenerator()
password_change_token = PasswordChangeTokenGenerator()