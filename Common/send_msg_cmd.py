"""统一消息推送:send_msg(title, content, level, image_path=None)

后端由 config.yaml notify.backend 决定:telegram / dingtalk / wecom / email / gotify / none;
所有后端懒加载 + 失败不抛异常(推送失败不能影响交易主流程),返回是否成功。
"""
from typing import Optional
from .NotificationStatus import notification_attempt, notification_result


def get_notify_conf() -> dict:
    from Config.EnvConfig import CEnv
    section = CEnv.get_instance().conf.get("notify", {})
    if not isinstance(section, dict):
        raise ValueError("explicit notification configuration must be an object")
    return section


def _failed(backend, reason):
    notification_result(backend, "failed")
    try:
        print(f"[send_msg] delivery_failed backend={backend} reason={reason}")
    except Exception:
        pass  # 输出服务本身失败也不能改变已经提交的交易状态。
    return False


def _ack(response, backend):
    if type(response.status_code) is not int or not 200 <= response.status_code < 300:
        return False
    body = response.json()
    if not isinstance(body, dict):
        return False
    if backend == "telegram":
        return body.get("ok") is True
    if backend in {"dingtalk", "wecom"}:
        return type(body.get("errcode")) is int and body["errcode"] == 0
    return type(body.get("id")) is int and body["id"] > 0  # Gotify message identity


def send_msg(title: str, content: str, level: str = "INFO", image_path: Optional[str] = None) -> bool:
    backend = "unknown"
    try:
        conf = get_notify_conf()
        candidate = conf.get("backend", "none")
    except Exception:
        notification_attempt(backend)
        return _failed(backend, "configuration_unavailable")
    if type(candidate) is not str or candidate not in {"telegram", "dingtalk", "wecom", "email", "gotify", "none"}:
        notification_attempt(backend)
        return _failed(backend, "unsupported_backend")
    backend = candidate
    notification_attempt(backend)
    try:
        if backend == "telegram":
            result = send_telegram(conf.get("telegram", {}), title, content, level, image_path)
        elif backend == "dingtalk":
            result = send_dingtalk(conf.get("dingtalk", {}), title, content, level)
        elif backend == "wecom":
            result = send_wecom(conf.get("wecom", {}), title, content, level)
        elif backend == "email":
            result = send_email(conf.get("email", {}), title, content, level)
        elif backend == "gotify":
            result = send_gotify(conf.get("gotify", {}), title, content, level)
        else:
            print(f"[send_msg][{level}] {title}: {content}")  # 显式 none 保留本地输出，不是外部送达。
            notification_result(backend, "local_only")
            return True
        if result is not True:
            return _failed(backend, "backend_rejected")
        notification_result(backend, "accepted")
        return True
    except Exception:
        return _failed(backend, "transport_error")


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
    return _ack(rsp, "telegram")


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
    return _ack(rsp, "dingtalk")


def send_wecom(conf: dict, title: str, content: str, level: str) -> bool:
    import requests
    webhook = conf.get("webhook")
    if not webhook:
        print("[send_msg] wecom 未配置 webhook")
        return False
    rsp = requests.post(webhook, json={
        "msgtype": "text", "text": {"content": f"[{level}] {title}\n{content}"}}, timeout=30)
    return _ack(rsp, "wecom")


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
    with smtplib.SMTP_SSL(host, int(conf.get("smtp_port", 465)), timeout=30) as server:
        server.login(user, conf.get("password", ""))
        refused = server.send_message(msg)
    return type(refused) is dict and not refused


def send_gotify(conf: dict, title: str, content: str, level: str) -> bool:
    import requests
    url, token = conf.get("url"), conf.get("token")
    if not url or not token:
        print("[send_msg] gotify 未配置 url/token")
        return False
    rsp = requests.post(
        f"{url.rstrip('/')}/message?token={token}",
        json={"title": f"[{level}] {title}", "message": content, "priority": 5}, timeout=30)
    return _ack(rsp, "gotify")
