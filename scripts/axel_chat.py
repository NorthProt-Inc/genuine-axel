#!/usr/bin/env python3
"""
Axel CLI Chat — 터미널에서 Axel과 대화하는 인터페이스
Usage: python3 scripts/axel_chat.py [--url URL] [--key KEY]
"""

import argparse
import json
import os
import signal
import sys
from pathlib import Path

# ── dotenv 로드 ──────────────────────────────────────────────
sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent.parent / ".env")

import requests
from rich.console import Console
from rich.live import Live
from rich.markdown import Markdown
from rich.panel import Panel
from rich.text import Text

# ─────────────────────────────────────────────────────────────
# Constants
# ─────────────────────────────────────────────────────────────

DEFAULT_URL = "http://localhost:8000"
DEFAULT_MODEL = "axel"
VERSION = "1.0"

COMMANDS = {
    "/help": "명령어 목록 표시",
    "/exit": "채팅 종료",
    "/quit": "채팅 종료",
    "/clear": "대화 히스토리 초기화",
    "/cls": "화면 클리어",
}

console = Console()


# ─────────────────────────────────────────────────────────────
# AxelAPIClient
# ─────────────────────────────────────────────────────────────

class AxelAPIClient:
    """Axel 백엔드와 통신하는 HTTP 클라이언트."""

    def __init__(self, base_url: str, api_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def health_check(self) -> bool:
        """GET /health/quick — 서버 생존 확인."""
        try:
            resp = requests.get(
                f"{self.base_url}/health/quick",
                headers=self._headers(),
                timeout=5,
            )
            return resp.status_code == 200
        except requests.ConnectionError:
            return False
        except Exception:
            return False

    def stream_chat(self, messages: list[dict]) -> requests.Response:
        """POST /v1/chat/completions (stream=true) — SSE 스트리밍 응답 반환."""
        payload = {
            "model": DEFAULT_MODEL,
            "messages": messages,
            "stream": True,
        }
        resp = requests.post(
            f"{self.base_url}/v1/chat/completions",
            headers=self._headers(),
            json=payload,
            stream=True,
            timeout=120,
        )
        resp.raise_for_status()
        return resp


# ─────────────────────────────────────────────────────────────
# ChatSession
# ─────────────────────────────────────────────────────────────

class ChatSession:
    """대화 히스토리를 관리하는 세션."""

    def __init__(self):
        self.messages: list[dict] = []

    def add_user(self, content: str):
        self.messages.append({"role": "user", "content": content})

    def add_assistant(self, content: str):
        self.messages.append({"role": "assistant", "content": content})

    def clear(self):
        self.messages.clear()

    @property
    def turn_count(self) -> int:
        return sum(1 for m in self.messages if m["role"] == "user")


# ─────────────────────────────────────────────────────────────
# TerminalUI
# ─────────────────────────────────────────────────────────────

class TerminalUI:
    """Rich 기반 터미널 렌더링."""

    @staticmethod
    def print_welcome(base_url: str, connected: bool):
        title = Text.assemble(
            ("Axel CLI", "bold cyan"),
            (f" v{VERSION}", "dim"),
        )
        subtitle = Text("/help 명령어 목록 · /exit 종료", style="dim")
        panel = Panel(
            Text.assemble(title, "\n", subtitle),
            border_style="cyan",
            padding=(0, 2),
        )
        console.print(panel)

        if connected:
            console.print(f"  [green]✓[/green] Connected to [bold]{base_url}[/bold]")
        else:
            console.print(
                f"  [yellow]⚠[/yellow] 서버 연결 실패 ([bold]{base_url}[/bold]) — "
                "요청 시 재시도합니다",
            )
        console.print()

    @staticmethod
    def print_help():
        console.print()
        console.print("[bold cyan]사용 가능한 명령어[/bold cyan]")
        for cmd, desc in COMMANDS.items():
            console.print(f"  [bold]{cmd:10s}[/bold] {desc}")
        console.print()

    @staticmethod
    def print_error(msg: str):
        console.print(f"  [red]✗[/red] {msg}")

    @staticmethod
    def print_info(msg: str):
        console.print(f"  [dim]{msg}[/dim]")

    @staticmethod
    def prompt_input() -> str | None:
        """사용자 입력 받기. Ctrl+D → None, Ctrl+C → 빈 문자열."""
        try:
            text = console.input("[bold green] You ► [/bold green]")
            return text
        except EOFError:
            return None
        except KeyboardInterrupt:
            console.print()
            return ""

    @staticmethod
    def stream_response(client: AxelAPIClient, messages: list[dict]) -> str:
        """SSE 스트리밍을 읽으며 Rich Live로 실시간 렌더링. 누적 텍스트 반환."""
        accumulated = ""
        interrupted = False

        try:
            resp = client.stream_chat(messages)
        except requests.ConnectionError:
            TerminalUI.print_error("서버에 연결할 수 없습니다. 백엔드가 실행 중인지 확인하세요.")
            return ""
        except requests.HTTPError as e:
            if e.response is not None and e.response.status_code == 401:
                TerminalUI.print_error("인증 실패 (401). API 키를 확인하세요 (--key 또는 AXNMIHN_API_KEY)")
            else:
                TerminalUI.print_error(f"HTTP 오류: {e}")
            return ""
        except Exception as e:
            TerminalUI.print_error(f"요청 실패: {e}")
            return ""

        header = Text(" Axel ", style="bold cyan")
        divider = Text("─" * 40, style="dim cyan")

        console.print()
        console.print(Text.assemble((" ", ""), header, divider))

        try:
            with Live(
                Markdown("▍"),
                console=console,
                refresh_per_second=8,
                vertical_overflow="visible",
            ) as live:
                for raw_line in resp.iter_lines(decode_unicode=True):
                    if not raw_line:
                        continue

                    # SSE 형식: "data: ..." 접두사 제거
                    if not raw_line.startswith("data: "):
                        continue
                    payload = raw_line[6:]

                    # 스트림 종료
                    if payload == "[DONE]":
                        break

                    try:
                        chunk = json.loads(payload)
                    except json.JSONDecodeError:
                        continue

                    choices = chunk.get("choices", [])
                    if not choices:
                        continue

                    delta = choices[0].get("delta", {})
                    finish_reason = choices[0].get("finish_reason")

                    if finish_reason == "stop":
                        break

                    content = delta.get("content", "")
                    if content:
                        accumulated += content
                        live.update(Markdown(accumulated + " ▍"))

                # 최종 렌더링 (커서 제거)
                if accumulated:
                    live.update(Markdown(accumulated))

        except KeyboardInterrupt:
            interrupted = True

        console.print(Text("─" * 42, style="dim cyan"))

        if interrupted:
            TerminalUI.print_info("(스트리밍 중단됨)")

        console.print()
        return accumulated


# ─────────────────────────────────────────────────────────────
# CommandHandler
# ─────────────────────────────────────────────────────────────

class CommandHandler:
    """슬래시 명령어 처리."""

    @staticmethod
    def is_command(text: str) -> bool:
        return text.startswith("/")

    @staticmethod
    def handle(text: str, session: ChatSession) -> bool:
        """명령어 실행. True 반환 시 프로그램 종료."""
        cmd = text.strip().lower()

        if cmd in ("/exit", "/quit"):
            console.print("\n  [dim] 다음에 또 봐![/dim]\n")
            return True

        if cmd == "/help":
            TerminalUI.print_help()
            return False

        if cmd == "/clear":
            session.clear()
            TerminalUI.print_info("대화 히스토리가 초기화되었습니다.")
            console.print()
            return False

        if cmd == "/cls":
            console.clear()
            return False

        TerminalUI.print_error(f"알 수 없는 명령어: {cmd}  (/help 참고)")
        console.print()
        return False


# ─────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Axel CLI Chat — 터미널에서 Axel과 대화",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("AXNMIHN_URL", DEFAULT_URL),
        help=f"Axel 백엔드 URL (기본: {DEFAULT_URL})",
    )
    parser.add_argument(
        "--key",
        default=os.getenv("AXNMIHN_API_KEY"),
        help="API 인증 키 (기본: .env의 AXNMIHN_API_KEY)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    client = AxelAPIClient(args.url, args.key)
    session = ChatSession()

    # SIGINT 기본 핸들러 복원 (KeyboardInterrupt로 잡을 수 있게)
    signal.signal(signal.SIGINT, signal.default_int_handler)

    # 시작
    connected = client.health_check()
    TerminalUI.print_welcome(args.url, connected)

    # ── 메인 루프 ────────────────────────────────────────────
    while True:
        user_input = TerminalUI.prompt_input()

        # Ctrl+D → 종료
        if user_input is None:
            console.print("\n  [dim] 다음에 또 봐![/dim]\n")
            break

        # Ctrl+C / 빈 입력 → 무시
        if not user_input.strip():
            continue

        text = user_input.strip()

        # 명령어 처리
        if CommandHandler.is_command(text):
            if CommandHandler.handle(text, session):
                break
            continue

        # 대화 처리
        session.add_user(text)
        reply = TerminalUI.stream_response(client, session.messages)

        if reply:
            session.add_assistant(reply)
        else:
            # 빈 응답이면 히스토리에서 마지막 유저 메시지 롤백
            if session.messages and session.messages[-1]["role"] == "user":
                session.messages.pop()


if __name__ == "__main__":
    main()
