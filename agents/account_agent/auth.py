"""Login, OTP and JWT.   Owner: M3

    login(msisdn, password) -> bool          bcrypt.checkpw; same error for bad number / bad password
    create_otp(msisdn) -> str                 6 digits via `secrets`; hash stored in data/db/auth.db,
                                              5-minute expiry, 3 attempts
    verify_otp(msisdn, otp) -> str | None     returns subscriber_id on success
    then shared.security.issue_jwt(subscriber_id)
"""
