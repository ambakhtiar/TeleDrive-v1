"""Daily automatic + manual upload reports posted to the Telegram group."""
import asyncio
from datetime import datetime, timedelta

from app import config


class ReportMixin:
    async def _daily_report_loop(self):
        while True:
            try:
                now = datetime.now()
                target = datetime(now.year, now.month, now.day, 23, 59, 0)
                if now >= target:
                    target += timedelta(days=1)
                await asyncio.sleep((target - now).total_seconds())
                cfg = config.read_config()
                if cfg.get("daily_report", True) and self.auth_state == "authorized":
                    await self.send_report(manual=False)
                await asyncio.sleep(120)
            except asyncio.CancelledError:
                break
            except Exception:
                await asyncio.sleep(300)

    async def send_report(self, manual=True):
        group_id = config.active_group_id()
        if not group_id or self.auth_state != "authorized":
            return False
        count = self.db.count_on()
        today = datetime.now().strftime("%d %B %Y")
        kind = "Manual" if manual else "Daily"
        if count > 0:
            body = f"📊 **{kind} Upload Report**\n\n📅 {today}\n✅ Uploaded: **{count}** files."
        else:
            body = f"📊 **{kind} Upload Report**\n\n📅 {today}\n💤 No files uploaded."
        await self.client.send_message(group_id, body)
        self.log(f"📈 {kind} report sent.")
        return True
