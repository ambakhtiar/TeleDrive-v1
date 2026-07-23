"""Telegram web login: phone → OTP → 2FA, plus logout / whoami."""


class AuthMixin:
    async def send_login_code(self, phone: str):
        """Step 1: request an OTP be sent to the phone number."""
        if self.client is None:
            await self._fresh_client()
        elif not self.client.is_connected():
            try:
                await self.client.connect()
            except Exception:
                await self._fresh_client()
        try:
            sent = await self.client.send_code_request(phone)
        except Exception as e:
            # A client that was logged out cannot be reused — rebuild once.
            if "reused" in str(e).lower() or "logged out" in str(e).lower():
                await self._fresh_client()
                sent = await self.client.send_code_request(phone)
            else:
                raise
        self._login_phone = phone
        self._login_hash = sent.phone_code_hash
        self.log(f"📲 OTP requested for {phone}")
        return {"status": "code_sent"}

    async def verify_login_code(self, code: str):
        """Step 2: sign in with the OTP. May require a 2FA password."""
        from telethon.errors import SessionPasswordNeededError

        if not getattr(self, "_login_hash", None):
            raise ValueError("Request an OTP first.")
        try:
            await self.client.sign_in(
                phone=self._login_phone, code=code, phone_code_hash=self._login_hash
            )
        except SessionPasswordNeededError:
            self.log("🔐 2FA password required.")
            return {"status": "password_needed"}
        return self._after_login()

    async def verify_login_password(self, password: str):
        """Step 3 (optional): complete sign-in with the 2FA password."""
        await self.client.sign_in(password=password)
        return self._after_login()

    def _after_login(self):
        self.auth_state = "authorized"
        self._login_hash = None
        self._persist_session()  # save the new login as an encrypted blob
        self.log("✅ Logged in to Telegram successfully.")
        self.emit("auth", {"auth_state": self.auth_state})
        return {"status": "authorized"}

    async def logout(self):
        try:
            await self.client.log_out()
        except Exception:
            pass
        # Drop the encrypted session blob so a logged-out state leaves nothing behind.
        try:
            import os
            from app import config
            if os.path.exists(config.SESSION_ENC):
                os.remove(config.SESSION_ENC)
        except Exception:
            pass
        # Telethon can't reuse a logged-out client, so stand up a fresh one
        # immediately — a new phone/OTP login then works without a restart.
        try:
            await self._fresh_client()
        except Exception as e:
            self.log(f"⚠️ Could not reset client after logout: {e}")
        self.auth_state = "unauthorized"
        self.emit("auth", {"auth_state": self.auth_state})
        self.log("👋 Logged out of Telegram.")
        return {"status": "unauthorized"}

    async def me(self):
        if self.auth_state != "authorized":
            return None
        try:
            u = await self.client.get_me()
            return {"id": u.id, "first_name": u.first_name,
                    "username": u.username, "phone": u.phone}
        except Exception:
            return None
