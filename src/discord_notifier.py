"""
Discord Notification System for Trading Bot
Uses discord.py SyncWebhook for non-blocking notifications.
"""
import os
import re
import time
from datetime import timedelta
from threading import Thread, Lock
from queue import Queue, Empty
from typing import Dict

import discord
from dotenv import load_dotenv

# Load environment variables from .env file in current working directory
load_dotenv()


class DiscordNotifier:
    """
    Non-blocking Discord notification sender with rate limiting.
    """

    def __init__(self, webhook_url: str = None, rate_limit: float = 2.0, event_callback=None):
        self.webhook_url = webhook_url or os.getenv("DISCORD_WEBHOOK_URL", "")
        self.event_callback = event_callback

        self.rate_limit = rate_limit
        self.min_interval = 1.0 / rate_limit
        self.last_send_time = 0.0

        self.queue = Queue(maxsize=30)
        self.running = True
        self.enabled = bool(self.webhook_url)
        self.webhook = None

        self.dropped_count = 0
        self.sent_count = 0
        self.error_count = 0
        self.last_error_time = 0.0
        self.session_start_time = time.time()

        self._messages = {}
        self._next_message_id = 1

        if self.enabled:
            try:
                self.webhook = discord.SyncWebhook.from_url(self.webhook_url)
            except Exception:
                self.enabled = False

        if self.enabled:
            self.thread = Thread(target=self._worker, daemon=True, name="DiscordNotifier")
            self.thread.start()
            if self.event_callback:
                self.event_callback("Notifier started", 'discord')
        else:
            if self.event_callback:
                self.event_callback("Discord disabled (no webhook)", 'info')

    def _to_discord_text(self, message: str) -> str:
        text = message
        text = text.replace("<b>", "**").replace("</b>", "**")
        text = text.replace("<i>", "*").replace("</i>", "*")
        text = text.replace("<code>", "`").replace("</code>", "`")
        text = text.replace("<br>", "\n").replace("<br/>", "\n")
        text = re.sub(r"<[^>]+>", "", text)
        return text

    def _worker(self):
        while self.running:
            try:
                msg = self.queue.get(timeout=1.0)
                if msg is None:
                    continue

                now = time.time()
                elapsed = now - self.last_send_time
                if elapsed < self.min_interval:
                    time.sleep(self.min_interval - elapsed)

                if self._send(msg):
                    self.sent_count += 1
                else:
                    self.error_count += 1

                self.last_send_time = time.time()
            except Empty:
                continue
            except Exception:
                self.error_count += 1

    def _send(self, message: str) -> bool:
        if not self.enabled or self.webhook is None:
            return False

        try:
            self.webhook.send(content=self._to_discord_text(message))
            return True
        except Exception as e:
            now = time.time()
            if now - self.last_error_time > 60:
                if self.event_callback:
                    self.event_callback(f"Send error: {str(e)[:40]}", 'error')
                self.last_error_time = now
            return False

    def notify(self, message: str):
        if not self.enabled:
            return
        try:
            self.queue.put_nowait(message)
        except Exception:
            self.dropped_count += 1

    def send_market_closed(self, coin: str, trade: Dict, session_stats: Dict, portfolio_stats: Dict = None):
        market_slug = trade.get('market_slug', 'unknown')
        pnl = trade.get('pnl', 0)
        roi_pct = trade.get('roi_pct', 0)
        winner = trade.get('winner', '?')

        if pnl > 0:
            result_emoji = "🟢"
            result_text = "WIN"
        else:
            result_emoji = "🔴"
            result_text = "LOSS"

        pnl_str = f"${pnl:+.2f}"
        roi_str = f"{roi_pct:+.1f}%"
        market_id = market_slug.split('-')[-1][:10] if '-' in market_slug else market_slug[-10:]

        message = f"""**{coin.upper()}** {result_emoji} {result_text}
━━━━━━━━━━━━━━━
Market: ...{market_id}
PnL: {pnl_str} ({roi_str})
Winner: {winner}"""

        total_pnl = session_stats.get('total_pnl', 0)
        win_rate = session_stats.get('win_rate', 0)
        message += f"\nTotal: ${total_pnl:+.2f} | WR: {win_rate:.0f}%"

        if portfolio_stats:
            message += "\n\n━━━━━━━━━━━━━━━\n**🏦 PORTFOLIO**"
            coins = ['btc', 'eth', 'sol', 'xrp']
            for c in coins:
                c_pnl = portfolio_stats.get(f'{c}_pnl', 0)
                c_wr = portfolio_stats.get(f'{c}_wr', 0)
                c_markets = portfolio_stats.get(f'{c}_markets_played', 0)
                pnl_emoji = "🟢" if c_pnl > 0 else "🔴" if c_pnl < 0 else "⚪"
                message += f"\n{c.upper()}: {pnl_emoji} ${c_pnl:+.2f} ({c_wr:.0f}% WR, {c_markets}m)"

            total_portfolio_pnl = portfolio_stats.get('total_pnl', 0)
            total_emoji = "🟢" if total_portfolio_pnl > 0 else "🔴" if total_portfolio_pnl < 0 else "⚪"
            uptime = portfolio_stats.get('uptime', 0)
            uptime_str = self._format_uptime(uptime)
            message += f"\n**Total: {total_emoji} ${total_portfolio_pnl:+.2f}** | {uptime_str}"

        self.notify(message)

    def send_market_skipped(self, coin: str, market_slug: str, skip_reason: str, session_stats: Dict, portfolio_stats: Dict = None):
        self.notify(f"**{coin.upper()}** ⏭️ SKIPPED")

    def send_photo(self, photo_path: str, caption: str = ""):
        if not self.enabled or self.webhook is None:
            return False

        try:
            with open(photo_path, 'rb') as photo:
                file = discord.File(photo, filename=os.path.basename(photo_path))
                self.webhook.send(content=self._to_discord_text(caption), file=file)
            self.sent_count += 1
            return True
        except Exception as e:
            self.error_count += 1
            if self.event_callback:
                self.event_callback(f"Photo error: {str(e)[:40]}", 'error')
            return False

    def _format_uptime(self, seconds: float) -> str:
        delta = timedelta(seconds=int(seconds))
        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60
        if delta.days > 0:
            return f"{delta.days}d {hours}h {minutes}m"
        if hours > 0:
            return f"{hours}h {minutes}m"
        return f"{minutes}m"

    def get_stats(self) -> Dict:
        return {
            'enabled': self.enabled,
            'sent_count': self.sent_count,
            'dropped_count': self.dropped_count,
            'error_count': self.error_count,
            'queue_size': self.queue.qsize()
        }

    def stop(self):
        self.running = False
        if self.enabled and self.event_callback:
            self.event_callback(
                f"Stopped (sent:{self.sent_count} drop:{self.dropped_count} err:{self.error_count})",
                'discord'
            )

    def start_command_listener(self, on_chart_command, on_balance_command=None,
                               on_positions_command=None, on_redeem_command=None, on_redeem_callbacks=None,
                               on_shutdown_command=None, on_shutdown_callbacks=None):
        if self.event_callback:
            self.event_callback("Discord command listener not configured (webhook mode)", 'info')
        return None

    def send_message_with_buttons(self, text: str, buttons: list) -> int:
        if not self.enabled or self.webhook is None:
            return None
        try:
            lines = [self._to_discord_text(text), "", "Actions:"]
            for row in buttons:
                for button in row:
                    label = button.get("text", "Action")
                    callback_data = button.get("callback_data", "")
                    lines.append(f"- {label} (`{callback_data}`)")
            msg = self.webhook.send(content="\n".join(lines), wait=True)
            message_id = self._next_message_id
            self._next_message_id += 1
            self._messages[message_id] = msg
            return message_id
        except Exception:
            return None

    def edit_message_text(self, message_id: int, text: str, buttons: list = None) -> bool:
        msg = self._messages.get(message_id)
        if msg is None:
            return self.send_message(text)
        content = self._to_discord_text(text)
        if buttons:
            lines = [content, "", "Actions:"]
            for row in buttons:
                for button in row:
                    lines.append(f"- {button.get('text', 'Action')} (`{button.get('callback_data', '')}`)")
            content = "\n".join(lines)
        try:
            msg.edit(content=content)
            return True
        except Exception:
            return False

    def answer_callback_query(self, callback_query_id: str, text: str = "", show_alert: bool = False) -> bool:
        return True

    def send_message(self, message: str):
        if not self.enabled or self.webhook is None:
            return False
        try:
            self.webhook.send(content=self._to_discord_text(message))
            self.sent_count += 1
            return True
        except Exception as e:
            self.error_count += 1
            if self.event_callback:
                self.event_callback(f"Send msg error: {str(e)[:40]}", 'error')
            return False


_notifier = None
_notifier_lock = Lock()


def get_notifier() -> DiscordNotifier:
    global _notifier
    if _notifier is None:
        with _notifier_lock:
            if _notifier is None:
                _notifier = DiscordNotifier()
    return _notifier
