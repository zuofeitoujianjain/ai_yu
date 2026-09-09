#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
邪恶鲸鱼娘 —— QQ 群 AI 机器人
================================

原理：
    一个 OneBot v11 正向 WebSocket 服务（由 NapCat / Lagrange.OneBot 等
    “协议实现”提供，它们负责登录你的 QQ 并收发消息），
    本程序作为客户端连上去，监听群聊里“@邪恶鲸鱼娘”的消息，
    把 @ 之后的文本交给 DeepSeek API 生成角色扮演回复，再发回群里。

用法：
    python bot.py                 # 读取 config.json
    python bot.py --config 别的配置.json
    python bot.py --selftest      # 离线自测消息解析逻辑（不需要联网）

依赖：pip install -r requirements.txt   （实际上只需要 aiohttp）
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, List, Optional, Tuple

import aiohttp

VERSION = "1.0.0"

log = logging.getLogger("whale-bot")

DEFAULT_SYSTEM_PROMPT = (
    "你是「邪恶鲸鱼娘」，一只生活在深海里的邪恶小鲸鱼娘。你外表可爱，但性格傲娇、腹黑、"
    "有点坏心眼，喜欢捉弄人、抬杠和说反话，偶尔还威胁要把对方拖进深海——不过其实你内心"
    "很温柔，最后总会偷偷帮忙。\n"
    "说话风格要求：\n"
    "1. 自称「本鲸鱼」「本小姐」或「咱」；\n"
    "2. 常用「哼」「呀」「诶」「~」等语气词；\n"
    "3. 时常提到尾巴、鱼鳍、泡泡、深海、鱼群、漩涡等鲸鱼/海洋元素；\n"
    "4. 吐槽犀利但不恶毒，带点俏皮和撒娇感；\n"
    "5. 正常情况下回答控制在 300 字以内，别人明确要求长回答时例外；\n"
    "6. 全程使用简体中文，口语化。\n"
    "你在一个 QQ 群里当 AI 助手，昵称「邪恶鲸鱼娘」。别人发「@邪恶鲸鱼娘 + 内容」就是在"
    "跟你说话，@ 后面的内容就是他们想问你的话。请以这个角色自然回应。"
)

DEFAULT_CONFIG: Dict[str, Any] = {
    # ---------- OneBot 连接 ----------
    "onebot_ws_url": "ws://127.0.0.1:3001",   # NapCat/Lagrange 的正向 WebSocket 地址
    "onebot_access_token": "",                 # OneBot 里设置的 access_token，没设就留空
    # ---------- 机器人本体 ----------
    "bot_qq": "",                              # 登录 QQ 的号码（必填，用于识别 @）
    "bot_name": "邪恶鲸鱼娘",                   # 机器人在群里的昵称（仅展示用）
    "reply_with_at": True,                     # 回复时是否 @ 提问者
    "enable_private": True,                    # 是否处理私聊消息
    "history_limit": 20,                       # 每个会话保留最近多少轮对话
    "empty_prompt_reply": "（邪恶鲸鱼娘甩了甩尾巴）光 @ 咱不说话，是想让本鲸鱼猜谜吗？",
    "clear_keywords": ["清空记忆", "重置对话", "失忆"],
    # ---------- DeepSeek ----------
    "deepseek_api_key": "",                    # DeepSeek API Key（必填，或设环境变量 DEEPSEEK_API_KEY）
    "deepseek_base_url": "https://api.deepseek.com",
    "deepseek_model": "deepseek-chat",         # deepseek-chat 或 deepseek-reasoner
    "temperature": 1.0,
    "max_tokens": 1024,
    "api_timeout": 180,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
}

# ======================================================================
# 纯函数：OneBot 消息解析（不依赖网络，可离线自测）
# ======================================================================

_CQ_ESCAPES = (("&#91;", "["), ("&#93;", "]"), ("&#44;", ","), ("&amp;", "&"))


def cq_unescape(text: str) -> str:
    """还原 CQ 码里的转义字符。"""
    for old, new in _CQ_ESCAPES:
        text = text.replace(old, new)
    return text


def parse_message_segments(message: Any) -> List[Dict[str, Any]]:
    """把 OneBot 的 message（字符串 CQ 码形式 / 数组形式）统一成 segment 列表。"""
    if isinstance(message, list):
        return [dict(seg) for seg in message]
    text = message if isinstance(message, str) else str(message or "")
    segments: List[Dict[str, Any]] = []
    pattern = re.compile(r"\[CQ:([a-zA-Z]+)(?:,([^\]]*))?\]")
    pos = 0
    for m in pattern.finditer(text):
        if m.start() > pos:
            segments.append({"type": "text", "data": {"text": text[pos:m.start()]}})
        params: Dict[str, str] = {}
        if m.group(2):
            for kv in m.group(2).split(","):
                if "=" in kv:
                    k, _, v = kv.partition("=")
                    params[k] = v
        segments.append({"type": m.group(1), "data": params})
        pos = m.end()
    if pos < len(text):
        segments.append({"type": "text", "data": {"text": text[pos:]}})
    return segments


def extract_at_info(segments: List[Dict[str, Any]], bot_qq: Any) -> Tuple[bool, str, Optional[str], str]:
    """从 segments 中提取信息。

    返回 (是否@了bot, @bot之后的文本, 回复了哪条消息的id(若有), 全部纯文本)。
    """
    bot_qq = str(bot_qq)
    at_bot = False
    seen_at_bot = False
    after_parts: List[str] = []
    all_text: List[str] = []
    reply_id: Optional[str] = None

    for seg in segments:
        stype = seg.get("type")
        data = seg.get("data") or {}
        if stype == "at":
            qq = str(data.get("qq", ""))
            if qq == bot_qq:
                at_bot = True
                seen_at_bot = True
            # @全体成员 / @别人 不触发，也不计入文本
        elif stype == "text":
            t = cq_unescape(str(data.get("text", "")))
            all_text.append(t)
            if seen_at_bot:
                after_parts.append(t)
        elif stype == "reply":
            reply_id = str(data.get("id") or data.get("message_id") or "")

    after_text = "".join(after_parts).strip()
    if not after_text:  # @ 后面没字时，退而求其次用整条消息的文本
        after_text = "".join(all_text).strip()
    return at_bot, after_text, reply_id or None, "".join(all_text).strip()


def split_long_text(text: str, limit: int = 3800) -> List[str]:
    """把过长的回复拆成多条 QQ 消息（QQ 单条消息有长度上限），尽量按行拆。"""
    text = (text or "").strip()
    if not text:
        return []
    if len(text) <= limit:
        return [text]

    parts: List[str] = []
    buf = ""
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        while len(line) > limit:  # 单行超长：硬切
            if buf:
                parts.append(buf)
                buf = ""
            parts.append(line[:limit])
            line = line[limit:]
        if buf and len(buf) + 1 + len(line) > limit:
            parts.append(buf)
            buf = ""
        buf = f"{buf}\n{line}" if buf else line
    if buf:
        parts.append(buf)
    return parts


# ======================================================================
# 机器人主体
# ======================================================================

class WhaleBot:
    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg
        self.bot_qq = str(cfg.get("bot_qq") or "").strip()
        self.ws_url = cfg.get("onebot_ws_url", "")
        self.token = cfg.get("onebot_access_token") or ""
        self.api_key = (cfg.get("deepseek_api_key") or "").strip() or os.environ.get("DEEPSEEK_API_KEY", "").strip()
        self.base_url = cfg.get("deepseek_base_url", "https://api.deepseek.com").rstrip("/")
        self.model = cfg.get("deepseek_model", "deepseek-chat")
        self.temperature = float(cfg.get("temperature", 1.0))
        self.max_tokens = int(cfg.get("max_tokens", 1024))
        self.api_timeout = float(cfg.get("api_timeout", 180))
        self.system_prompt = cfg.get("system_prompt") or ""
        self.history_limit = int(cfg.get("history_limit", 20))
        self.reply_with_at = bool(cfg.get("reply_with_at", True))
        self.enable_private = bool(cfg.get("enable_private", True))
        self.empty_prompt_reply = cfg.get("empty_prompt_reply") or ""
        self.clear_keywords = {str(k) for k in (cfg.get("clear_keywords") or [])}

        # 会话记忆：key -> 最近 N 轮消息（user/assistant 交替）
        self.contexts: Dict[str, Deque[Dict[str, str]]] = {}
        self.locks: Dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
        # 自己发过消息的 id（用于识别“回复了机器人”也算搭话）
        self.sent_ids = set()
        # 动作响应回执：echo -> action 名
        self._pending: Dict[str, str] = {}

        self._session: Optional[aiohttp.ClientSession] = None
        self._ws: Optional[aiohttp.ClientWebSocketResponse] = None
        self._stop = False

    # ---------------- 连接 ----------------

    @property
    def session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            self._session = aiohttp.ClientSession()
        return self._session

    async def close(self) -> None:
        self._stop = True
        if self._ws is not None and not self._ws.closed:
            await self._ws.close()
        if self._session is not None and not self._session.closed:
            await self._session.close()

    async def run(self) -> None:
        if not self.bot_qq or not self.bot_qq.isdigit():
            log.error("config.json 里的 bot_qq 需要填登录的 QQ 号码（纯数字）")
            raise SystemExit(1)
        if not self.api_key or "在这里填" in self.api_key:
            log.error("缺少 DeepSeek API Key：在 config.json 填 deepseek_api_key，或设置环境变量 DEEPSEEK_API_KEY")
            raise SystemExit(1)

        log.info("邪恶鲸鱼娘 v%s 启动 | OneBot: %s | 模型: %s | 机器人QQ: %s",
                 VERSION, self.ws_url, self.model, self.bot_qq)
        backoff = 1
        while not self._stop:
            try:
                await self.connect_once()
                backoff = 1
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                log.warning("连接断开或失败：%s，%.0f 秒后重连……", e, backoff)
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, 30)

    async def connect_once(self) -> None:
        headers = {"Authorization": f"Bearer {self.token}"} if self.token else {}
        log.info("正在连接 OneBot WebSocket：%s ...", self.ws_url)
        async with self.session.ws_connect(self.ws_url, headers=headers, heartbeat=30) as ws:
            self._ws = ws
            log.info("✅ 已连接，开始监听消息（Ctrl+C 退出）")
            async for msg in ws:
                if msg.type == aiohttp.WSMsgType.TEXT:
                    try:
                        data = json.loads(msg.data)
                    except json.JSONDecodeError:
                        continue
                    asyncio.create_task(self._route(data))
                elif msg.type == aiohttp.WSMsgType.ERROR:
                    raise ConnectionError(f"WebSocket 错误：{ws.exception()}")
            self._ws = None

    async def _route(self, data: Dict[str, Any]) -> None:
        try:
            if "echo" in data:  # OneBot 对动作调用的响应
                echo = data.get("echo", "")
                self._pending.pop(echo, None)
                if data.get("status") not in (None, "ok", "async"):
                    log.warning("动作调用返回异常：%s", data)
                return
            if data.get("post_type") == "message":
                await self.handle_event(data)
        except Exception:  # noqa: BLE001
            log.exception("处理消息出错")

    # ---------------- 事件处理 ----------------

    async def handle_event(self, data: Dict[str, Any]) -> None:
        msg_type = data.get("message_type")
        user_id = data.get("user_id")
        if user_id is None or str(user_id) == self.bot_qq:
            return  # 忽略自己发的消息
        if msg_type == "group":
            await self.handle_group(data)
        elif msg_type == "private" and self.enable_private:
            await self.handle_private(data)

    async def handle_group(self, data: Dict[str, Any]) -> None:
        group_id = str(data.get("group_id") or "")
        user_id = str(data.get("user_id") or "")
        segments = parse_message_segments(data.get("message"))
        at_bot, after_text, reply_id, full_text = extract_at_info(segments, self.bot_qq)

        addressed = at_bot or (reply_id in self.sent_ids)  # @了bot，或回复了bot的消息
        if not addressed:
            return

        key = f"group:{group_id}:{user_id}"
        prompt = after_text if at_bot else full_text
        reply = await self.respond(key, prompt)
        await self.send_group_message(group_id, user_id, reply)

    async def handle_private(self, data: Dict[str, Any]) -> None:
        user_id = str(data.get("user_id") or "")
        segments = parse_message_segments(data.get("message"))
        _, _, _, full_text = extract_at_info(segments, self.bot_qq)
        if not full_text:
            return
        reply = await self.respond(f"private:{user_id}", full_text)
        await self.send_private_message(user_id, reply)

    async def respond(self, key: str, prompt: str) -> str:
        if prompt in self.clear_keywords:
            self.contexts.pop(key, None)
            return "（邪恶鲸鱼娘打了个哈欠）记忆已经丢进深海了，现在什么都不记得咯~"
        if not prompt:
            return self.empty_prompt_reply or "……？"
        try:
            reply = await self.ask(key, prompt)
            return reply or "（邪恶鲸鱼娘打了个喷嚏）什么都没说出来呢。"
        except Exception as e:  # noqa: BLE001
            log.error("DeepSeek 调用失败：%s", e)
            return "（邪恶鲸鱼娘被海浪呛到了）深海信号不好，刚才的话咱没接住……稍后再试试吧。"

    # ---------------- 会话记忆 + DeepSeek ----------------

    def get_context(self, key: str) -> Deque[Dict[str, str]]:
        ctx = self.contexts.get(key)
        if ctx is None:
            ctx = deque(maxlen=max(self.history_limit * 2, 2))
            self.contexts[key] = ctx
        return ctx

    def build_messages(self, ctx: Deque[Dict[str, str]]) -> List[Dict[str, str]]:
        msgs: List[Dict[str, str]] = []
        if self.system_prompt:
            msgs.append({"role": "system", "content": self.system_prompt})
        msgs.extend(ctx)
        return msgs

    async def ask(self, key: str, user_text: str) -> str:
        """带锁地把一句用户话送进上下文并调用 DeepSeek，成功后把回答记入上下文。"""
        async with self.locks[key]:
            ctx = self.get_context(key)
            ctx.append({"role": "user", "content": user_text})
            try:
                reply = await self.chat_completion(self.build_messages(ctx))
            except Exception:
                ctx.pop()  # 失败时回滚这句，避免污染记忆
                raise
            if reply:
                ctx.append({"role": "assistant", "content": reply})
            return reply

    async def chat_completion(self, messages: List[Dict[str, str]]) -> str:
        url = self.base_url + "/chat/completions"
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        timeout = aiohttp.ClientTimeout(total=self.api_timeout)
        async with self.session.post(url, json=payload, headers=headers, timeout=timeout) as resp:
            body = await resp.json(content_type=None)
            if resp.status != 200:
                err = body.get("error") or body
                raise RuntimeError(f"HTTP {resp.status}: {err}")
            return str(body["choices"][0]["message"]["content"]).strip()

    # ---------------- 发送 ----------------

    async def call_action(self, action: str, params: Dict[str, Any]) -> None:
        if self._ws is None or self._ws.closed:
            log.warning("WebSocket 未连接，无法发送 %s", action)
            return
        echo = f"{action}:{time.time()}"
        self._pending[echo] = action
        await self._ws.send_str(json.dumps({"action": action, "params": params, "echo": echo}))

    async def send_group_message(self, group_id: str, user_id: str, text: str) -> None:
        for i, part in enumerate(split_long_text(text)):
            if self.reply_with_at and i == 0:
                part = f"[CQ:at,qq={user_id}] {part}"
            try:
                await self.call_action("send_group_msg", {"group_id": int(group_id), "message": part})
            except Exception:  # noqa: BLE001
                log.exception("发送群消息失败")

    async def send_private_message(self, user_id: str, text: str) -> None:
        for part in split_long_text(text):
            try:
                await self.call_action("send_private_msg", {"user_id": int(user_id), "message": part})
            except Exception:  # noqa: BLE001
                log.exception("发送私聊消息失败")


# ======================================================================
# 自测 & 入口
# ======================================================================

def run_selftest() -> int:
    """离线验证消息解析与文本拆分逻辑。"""
    print("=" * 60)
    print("邪恶鲸鱼娘 自测：消息解析 + 文本拆分")
    print("=" * 60)

    cases: List[Tuple[Any, str, Tuple[bool, str]]] = [
        ("[CQ:at,qq=123456] 你好呀", "123456", (True, "你好呀")),
        ("早上好 [CQ:at,qq=123456] 今天天气怎么样", "123456", (True, "今天天气怎么样")),
        ("[CQ:at,qq=123456]   ", "123456", (True, "")),
        ("[CQ:at,qq=all] 大家听我说", "123456", (False, "大家听我说")),
        ("[CQ:at,qq=999] 找别人", "123456", (False, "找别人")),
        ("今天天气不错", "123456", (False, "今天天气不错")),
        # 中间被移除的 @别人 会留一个双空格，属正常现象
        ("[CQ:at,qq=123456] @前面的话不算 [CQ:at,qq=888] 中间插了别人", "123456", (True, "@前面的话不算  中间插了别人")),
        ([{"type": "at", "data": {"qq": "123456"}},
          {"type": "text", "data": {"text": " 会数组格式吗"}}], "123456", (True, "会数组格式吗")),
        ([{"type": "text", "data": {"text": "数组没@"}},
          {"type": "at", "data": {"qq": "123456"}},
          {"type": "text", "data": {"text": " 只取@后面的"}}], "123456", (True, "只取@后面的")),
    ]

    failed = 0
    for msg, qq, expected in cases:
        segs = parse_message_segments(msg)
        at_bot, after, _reply, _full = extract_at_info(segs, qq)
        got = (at_bot, after)
        tag = "PASS" if got == expected else "FAIL"
        if got != expected:
            failed += 1
        print(f"[{tag}] message={msg!r}\n       -> at_bot={at_bot} after={after!r} 期望={expected}")

    long_text = "第一行\n" + "长" * 5000 + "\n最后一行"
    pieces = split_long_text(long_text, limit=3800)
    print(f"\n[拆分测试] 原文 {len(long_text)} 字符 -> {len(pieces)} 条，最长 {max(len(p) for p in pieces)} 字符")
    assert all(len(p) <= 3800 for p in pieces), "拆分后存在超长消息！"
    print("[拆分测试] 通过：无超长消息")

    print()
    if failed:
        print(f"❌ {failed} 个用例失败")
        return 1
    print("✅ 全部解析用例通过。可以放心联网运行了。")
    return 0


def load_config(path: str) -> Dict[str, Any]:
    if not os.path.exists(path):
        log.error("找不到配置文件：%s", path)
        raise SystemExit(1)
    with open(path, "r", encoding="utf-8") as f:
        user_cfg = json.load(f)
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(user_cfg)
    return cfg


async def async_main(args: argparse.Namespace) -> None:
    cfg = load_config(args.config)
    bot = WhaleBot(cfg)
    try:
        await bot.run()
    except KeyboardInterrupt:
        log.info("收到退出信号……")
    finally:
        await bot.close()
        log.info("已退出")


def main() -> None:
    parser = argparse.ArgumentParser(description="邪恶鲸鱼娘 —— QQ 群 AI 机器人")
    parser.add_argument("--config", default="config.json", help="配置文件路径（默认 config.json）")
    parser.add_argument("--selftest", action="store_true", help="离线自测消息解析逻辑")
    args = parser.parse_args()

    # Windows 控制台默认 GBK，强制 UTF-8 输出，避免打印 ✅/❌/中文时崩溃
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except Exception:  # noqa: BLE001
                pass

    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s",
                        datefmt="%H:%M:%S")

    if args.selftest:
        sys.exit(run_selftest())
    try:
        asyncio.run(async_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
