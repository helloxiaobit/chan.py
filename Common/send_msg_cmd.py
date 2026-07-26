"""统一消息推送:send_msg(title, content, level, image_path=None)

后端由 config.yaml notify.backend 决定:telegram / dingtalk / wecom / email / gotify / none;
所有后端懒加载 + 失败不抛异常(推送失败不能影响交易主流程),返回是否成功。
"""
import traceback
from typing import Optional


def get_notify_conf() -> dict:
    try:
        from Config.EnvConfig import CEnv
        return CEnv.get_instance().notify_conf
    except Exception:
        return {}


def send_msg(title: str, content: str, level: str = "INFO", image_path: Optional[str] = None) -> bool:
    conf = get_notify_conf()
    backend = conf.get("backend", "none")
    try:
        if backend == "telegram":
            return send_telegram(conf.get("telegram", {}), title, content, level, image_path)
        if backend == "dingtalk":
            return send_dingtalk(conf.get("dingtalk", {}), title, content, level)
        if backend == "wecom":
            return send_wecom(conf.get("wecom", {}), title, content, level)
        if backend == "email":
            return send_email(conf.get("email", {}), title, content, level)
        if backend == "gotify":
            return send_gotify(conf.get("gotify", {}), title, content, level)
        print(f"[send_msg][{level}] {title}: {content}")  # backend=none 时打印
        return True
    except Exception:
        print(f"[send_msg] 推送失败({backend}):\n{traceback.format_exc()}")
        return False


def send_telegram(conf: dict, title: str, content: str, level: str, image_path: Optional[str]) -> bool:
    import requests  # 懒加载
    token, chat_id = conf.get("bot_token"), conf.get("chat_id")
    if not token or not chat_id:
        print("[send_msg] telegram 未配置 bot_token/chat_id")
        return False
    proxies = {"http": conf["proxy"], "https": conf["proxy"]} if conf.get("proxy") else None
    text = f"[{level}] {title}\n{content}"
    if image_path:
        with open(image_path, "rb") as f:
            rsp = requests.post(
                f"https://api.telegram.org/bot{token}/sendPhoto",
                data={"chat_id": chat_id, "caption": text},
                files={"photo": f}, proxies=proxies, timeout=30,
            )
    else:
        rsp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            data={"chat_id": chat_id, "text": text}, proxies=proxies, timeout=30,
        )
    return bool(rsp.ok)


def send_dingtalk(conf: dict, title: str, content: str, level: str) -> bool:
    import base64
    import hashlib
    import hmac
    import time
    import urllib.parse

    import requests
    webhook = conf.get("webhook")
    if not webhook:
        print("[send_msg] dingtalk 未配置 webhook")
        return False
    if secret := conf.get("secret"):
        ts = str(round(time.time() * 1000))
        sign_str = f"{ts}\n{secret}"
        sign = urllib.parse.quote_plus(base64.b64encode(
            hmac.new(secret.encode(), sign_str.encode(), hashlib.sha256).digest()))
        webhook = f"{webhook}&timestamp={ts}&sign={sign}"
    rsp = requests.post(webhook, json={
        "msgtype": "text", "text": {"content": f"[{level}] {title}\n{content}"}}, timeout=30)
    return bool(rsp.ok)


def send_wecom(conf: dict, title: str, content: str, level: str) -> bool:
    import requests
    webhook = conf.get("webhook")
    if not webhook:
        print("[send_msg] wecom 未配置 webhook")
        return False
    rsp = requests.post(webhook, json={
        "msgtype": "text", "text": {"content": f"[{level}] {title}\n{content}"}}, timeout=30)
    return bool(rsp.ok)


def send_email(conf: dict, title: str, content: str, level: str) -> bool:
    import smtplib
    from email.mime.text import MIMEText
    host, user = conf.get("smtp_host"), conf.get("user")
    if not host or not user:
        print("[send_msg] email 未配置 smtp_host/user")
        return False
    msg = MIMEText(content, "plain", "utf-8")
    msg["Subject"] = f"[{level}] {title}"
    msg["From"] = user
    msg["To"] = conf.get("to", user)
    with smtplib.SMTP_SSL(host, int(conf.get("smtp_port", 465))) as server:
        server.login(user, conf.get("password", ""))
        server.send_message(msg)
    return True


def send_gotify(conf: dict, title: str, content: str, level: str) -> bool:
    import requests
    url, token = conf.get("url"), conf.get("token")
    if not url or not token:
        print("[send_msg] gotify 未配置 url/token")
        return False
    rsp = requests.post(
        f"{url.rstrip('/')}/message?token={token}",
        json={"title": f"[{level}] {title}", "message": content, "priority": 5}, timeout=30)
    return bool(rsp.ok)
