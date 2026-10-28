"""Love in ZJU request intake. FC Python 3.12, max instances=1, concurrency=1.

Payment claims are declarations, never proof of payment. Production data must
be in a separate private OSS bucket. SMTP credentials stay in server env only.
"""
import base64
import hashlib
import hmac
from itertools import islice
import json
import os
import re
import smtplib
import ssl
import threading
import time
from datetime import datetime, timezone, timedelta
from email.message import EmailMessage
from pathlib import Path

LOCK = threading.RLock()
TZ = timezone(timedelta(hours=8))
PRODUCTS = {
    "birthday": ("星空生日", 990, 990, ("wish", "secret")),
    "strawberry": ("草莓生日（筹备中）", 990, 1990, ("wish", "secret")),
    "memory": ("我们的N个瞬间", 1990, 2990, ("names", "moments")),
    "record": ("送你一张唱片", 1590, 1990, ("track", "message")),
    "campus": ("青春有迹可循", 2990, 4990, ("title", "places")),
    "letters": ("大家的悄悄话", 2990, 4990, ("intro", "letters")),
}
ORIGINS = {"https://www.loveinzju.top", "https://loveinzju.top"}
STATUSES = {"new", "contacted", "making", "delivered", "cancelled"}


class APIError(Exception):
    def __init__(self, status, message):
        self.status, self.message = status, message


def now():
    return datetime.now(TZ).isoformat(timespec="seconds")


def secret():
    value = os.environ.get("ORDER_SECRET", "")
    if len(value) < 32:
        raise APIError(503, "收单服务配置未完成，请稍后再试。")
    return value


def digest(text):
    return hmac.new(secret().encode(), text.encode(), hashlib.sha256).hexdigest()


def text(value, name, maximum, required=True):
    if not isinstance(value, str):
        raise APIError(400, name + "格式不正确。")
    value = value.strip()
    if (required and not value) or len(value) > maximum or "\x00" in value:
        raise APIError(400, "请检查" + name + "。")
    return value


class FileStore:
    """Local QA only. Never select via a public request parameter."""
    def __init__(self):
        self.root = Path(os.environ["LOCAL_DATA"]).resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def get(self, key):
        path = self.root / key
        return json.loads(path.read_text(encoding="utf8")) if path.exists() else None

    def put(self, key, value, create=False):
        path = self.root / key
        path.parent.mkdir(parents=True, exist_ok=True)
        if create:
            try:
                with path.open("x", encoding="utf8") as f:
                    json.dump(value, f, ensure_ascii=False)
                return True
            except FileExistsError:
                return False
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(value, ensure_ascii=False), encoding="utf8")
        tmp.replace(path)
        return True

    def delete(self, key):
        (self.root / key).unlink(missing_ok=True)

    def keys(self, prefix, limit=200):
        return sorted(p.relative_to(self.root).as_posix()
                      for p in (self.root / prefix).glob("*.json"))[:limit]


class OSSStore:
    def __init__(self, context):
        import oss2
        name = os.environ.get("ORDERS_BUCKET", "")
        if not name or name == "liuyifen-hk-public" or "public" in name:
            raise APIError(503, "私有收单存储尚未配置。")
        creds = getattr(context, "credentials", None)
        if creds:
            values = (creds.access_key_id, creds.access_key_secret, creds.security_token)
        else:
            values = tuple(os.getenv(k) for k in (
                "ALIBABA_CLOUD_ACCESS_KEY_ID", "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
                "ALIBABA_CLOUD_SECURITY_TOKEN"))
        auth = oss2.StsAuth(*values, auth_version="v4")
        self.bucket = oss2.Bucket(auth, "https://oss-cn-hongkong-internal.aliyuncs.com",
                                  name, region="cn-hongkong", connect_timeout=5)
        if self.bucket.get_bucket_acl().acl != "private":
            raise APIError(503, "收单存储访问权限需检查。")
        self.oss2 = oss2

    def get(self, key):
        try:
            return json.loads(self.bucket.get_object(key).read())
        except self.oss2.exceptions.NoSuchKey:
            return None

    def put(self, key, value, create=False):
        headers = {"Content-Type": "application/json; charset=utf-8",
                   "x-oss-object-acl": "private"}
        if create:
            headers["x-oss-forbid-overwrite"] = "true"
        try:
            self.bucket.put_object(key, json.dumps(value, ensure_ascii=False).encode(), headers=headers)
            return True
        except self.oss2.exceptions.OssError as exc:
            if create and exc.status == 409:
                return False
            raise

    def delete(self, key):
        self.bucket.delete_object(key)

    def keys(self, prefix, limit=200):
        return [item.key for item in islice(self.oss2.ObjectIteratorV2(
            self.bucket, prefix=prefix, max_keys=min(limit, 1000)), limit)]


def store_for(context):
    if os.environ.get("DEV_MODE") == "1":
        return FileStore()
    return OSSStore(context)


def mail_ready():
    return bool(os.environ.get("SMTP_USER") and os.environ.get("SMTP_PASSWORD"))


def summary(order):
    lines = ["爱在ZJU · 定制需求", "需求编号：" + order["id"],
             "产品：" + order["productName"], "联系邮箱：" + order["email"],
             "送给：" + order["recipient"], "希望收到日期：" + order["desiredDate"],
             "来源：" + order["source"]]
    if order["quoteRequired"]:
        lines += ["状态：需要先报价；未展示收款要求。"]
    else:
        lines += ["基本款约定金额：¥%.2f" % (order["amountMinor"] / 100),
                  "付款状态：" + ("已人工核验" if order["paymentStatus"] == "verified"
                    else "客户声明已付款，待人工核验" if order["paymentStatus"] == "claimed"
                    else "待客户付款")]
    lines += ["", "定制内容", json.dumps(order["details"], ensure_ascii=False, indent=2),
              "", "素材需求：" + order["materials"], "补充说明：" + (order["extras"] or "无")]
    if order.get("payerReference"):
        lines += ["", "客户填写的付款说明：" + order["payerReference"],
                  "声明时间：" + order["claimedAt"],
                  "注意：这是客户的付款声明，不是微信到账通知。请先核对自己的收款账单。"]
    return "\n".join(lines)


def send_mail(order):
    if not mail_ready():
        raise RuntimeError("SMTP is not configured")
    msg = EmailMessage()
    user = os.environ["SMTP_USER"]
    msg["From"] = user
    # Fixed operator recipient; never accept a recipient supplied by visitors.
    msg["To"] = "loveshi1009@163.com"
    msg["Reply-To"] = order["email"]
    kind = "需报价" if order["quoteRequired"] else "付款待核验"
    msg["Subject"] = "[爱在ZJU][" + kind + "] " + order["id"] + " · " + order["productName"]
    msg["Message-ID"] = "<" + order["id"] + ".intake@loveinzju.top>"
    msg.set_content(summary(order))
    with smtplib.SMTP_SSL("smtp.163.com", 465, timeout=8,
                         context=ssl.create_default_context()) as smtp:
        smtp.login(user, os.environ["SMTP_PASSWORD"])
        smtp.send_message(msg)


def notify(store, order):
    if order["notificationStatus"] == "sent":
        return
    attempts = order.get("notificationAttempts", 0)
    if attempts >= 8:
        order["notificationStatus"] = "needs_attention"
        store.put("orders/" + order["id"] + ".json", order)
        return
    order["notificationAttempts"] = attempts + 1
    store.put("orders/" + order["id"] + ".json", order)
    try:
        send_mail(order)
        order["notificationStatus"] = "sent"  # SMTP accepted, not inbox delivery proof.
        order.pop("notificationError", None)
        order["notifiedAt"] = now()
        store.put("orders/" + order["id"] + ".json", order)
    except Exception as exc:
        # Customer records survive mail failure. Do not log bodies or credentials.
        order["notificationStatus"] = "pending_retry"
        if isinstance(exc, smtplib.SMTPAuthenticationError):
            order["notificationError"] = "smtp_authentication"
        elif isinstance(exc, (ConnectionError, TimeoutError, OSError)):
            order["notificationError"] = "smtp_network"
        elif isinstance(exc, smtplib.SMTPException):
            order["notificationError"] = "smtp_protocol"
        else:
            order["notificationError"] = "smtp_other"
        store.put("orders/" + order["id"] + ".json", order)


def enqueue(store, order):
    # The persisted notificationStatus is the queue. No second write that can
    # fail between saving the request and enqueuing its notification.
    pass


def retry_notifications(store):
    attempted = 0
    for key in store.keys("orders/", 5000):
        order = store.get(key)
        if order and order["notificationStatus"] == "pending_retry":
            notify(store, order)
            attempted += 1
            if attempted >= 2:
                break
    return {"attempted": attempted}


def limited(store, scope, limit):
    day = datetime.now(TZ).strftime("%Y%m%d")
    key = "limits/" + day + "-" + digest(scope)[:24] + ".json"
    value = store.get(key) or {"count": 0}
    if value["count"] >= limit:
        raise APIError(429, "当前提交较多，请稍后再试，或联系页面邮箱。")
    value["count"] += 1
    store.put(key, value)


def validate_order(body):
    if not isinstance(body, dict) or body.get("website"):
        raise APIError(400, "请检查提交内容。")
    request_id = text(body.get("requestId"), "请求编号", 64)
    if not re.fullmatch(r"[a-fA-F0-9-]{32,36}", request_id):
        raise APIError(400, "请重新打开表单后提交。")
    product = body.get("product")
    if product not in PRODUCTS:
        raise APIError(400, "请选择礼物。")
    email = text(body.get("email"), "联系邮箱", 160)
    if not re.fullmatch(r"[A-Za-z0-9.!#$%&'*+/=?^_{}|~-]+@[A-Za-z0-9](?:[A-Za-z0-9.-]*[A-Za-z0-9])?\.[A-Za-z]{2,63}", email):
        raise APIError(400, "请填写有效的联系邮箱。")
    recipient = text(body.get("recipient"), "收礼称呼", 30)
    date = text(body.get("desiredDate"), "希望收到日期", 10)
    try:
        datetime.strptime(date, "%Y-%m-%d")
    except ValueError:
        raise APIError(400, "请检查希望收到日期。")
    details = body.get("details")
    if not isinstance(details, dict) or set(details) != set(PRODUCTS[product][3]):
        raise APIError(400, "请填写该产品所需的定制内容。")
    details = {key: text(details[key], "定制内容", 2000) for key in PRODUCTS[product][3]}
    materials = body.get("materials", "base")
    if materials not in {"base", "custom", "unsure"}:
        raise APIError(400, "请检查素材需求。")
    extras = text(body.get("extras", ""), "补充说明", 400, False)
    source = text(body.get("source", "未注明"), "来源", 30, False)
    return dict(requestId=request_id, product=product, email=email, recipient=recipient,
                desiredDate=date, details=details, materials=materials, extras=extras, source=source)


def public_receipt(order):
    return {"id": order["id"], "accessToken": digest("receipt:" + order["id"]),
            "productName": order["productName"], "quoteRequired": order["quoteRequired"],
            "amountMinor": order["amountMinor"], "paymentStatus": order["paymentStatus"],
            "notificationStatus": order["notificationStatus"]}


def create_order(store, body, ip):
    data = validate_order(body)
    order_id = "AZ-" + digest("request:" + data["requestId"])[:16].upper()
    key = "orders/" + order_id + ".json"
    fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
    old = store.get(key)
    if old:
        if old["fingerprint"] != fingerprint:
            raise APIError(409, "这份定制单已经确认。如需修改，请返回重新生成一份。")
        return public_receipt(old)
    limited(store, "ip:" + ip, 12)
    limited(store, "all-orders", int(os.getenv("DAILY_ORDER_LIMIT", "50")))
    quote = data["materials"] != "base" or data["product"] == "strawberry"
    today = datetime.now(TZ).date().isoformat()
    offer = "2026-10-28" <= today <= "2026-11-27"
    product = PRODUCTS[data["product"]]
    order = {**data, "id": order_id, "fingerprint": fingerprint, "createdAt": now(),
             "productName": product[0], "amountMinor": None if quote else product[1 if offer else 2],
             "quoteRequired": quote, "status": "new", "paymentStatus": "not_required" if quote else "unpaid",
             "notificationStatus": "pending_retry" if quote else "not_requested", "notificationAttempts": 0}
    if not store.put(key, order, create=True):
        return public_receipt(store.get(key))
    if quote:
        enqueue(store, order)
        notify(store, order)
    return public_receipt(order)


def claim_payment(store, order_id, body, token):
    if not hmac.compare_digest(token, digest("receipt:" + order_id)):
        raise APIError(403, "这份需求的访问凭据无效，请重新提交。")
    order = store.get("orders/" + order_id + ".json")
    if not order:
        raise APIError(404, "未找到该需求，请保留填写内容并联系邮箱。")
    if order["quoteRequired"]:
        raise APIError(409, "这份需求需要先确认报价，请不要直接付款。")
    if order["paymentStatus"] in {"claimed", "verified"}:
        return public_receipt(order)
    if body.get("paidDeclaration") is not True:
        raise APIError(400, "请确认你已按显示金额付款。")
    reference = text(body.get("payerReference"), "付款说明", 200)
    order.update(paymentStatus="claimed", payerReference=reference, claimedAt=now(),
                 notificationStatus="pending_retry")
    store.put("orders/" + order_id + ".json", order)
    enqueue(store, order)
    notify(store, order)
    return public_receipt(order)


def admin_ok(headers):
    token = os.environ.get("ADMIN_TOKEN", "")
    supplied = headers.get("authorization", "")
    return len(token) >= 32 and hmac.compare_digest(supplied, "Bearer " + token)


def admin_route(store, method, path, body, query):
    if path == "/api/admin/orders" and method == "GET":
        rows = [store.get(key) for key in store.keys("orders/", 5000)]
        rows.sort(key=lambda x: x["createdAt"], reverse=True)
        return {"orders": rows}
    match = re.fullmatch(r"/api/admin/orders/(AZ-[A-F0-9]{16})/(status|verify|notify)", path)
    if not match or method != "POST":
        raise APIError(404, "接口不存在。")
    order_id, action = match.groups()
    order = store.get("orders/" + order_id + ".json")
    if not order:
        raise APIError(404, "需求不存在。")
    if action == "verify":
        if order["paymentStatus"] != "claimed":
            raise APIError(409, "只可核验客户已声明付款的需求。")
        order.update(paymentStatus="verified", verifiedAt=now())
    elif action == "status":
        if body.get("status") not in STATUSES:
            raise APIError(400, "状态不正确。")
        order["status"] = body["status"]
    else:
        if order["notificationStatus"] == "not_requested":
            raise APIError(409, "客户还没有声明付款，暂不发送付款核验邮件。")
        order["notificationAttempts"] = 0
        order["notificationStatus"] = "pending_retry"
        enqueue(store, order)
        notify(store, order)
    store.put("orders/" + order_id + ".json", order)
    return {"order": order}


def handler(event, context):
    origin = ""
    allowed = set(ORIGINS)
    if os.environ.get("DEV_MODE") == "1":
        allowed.add("http://127.0.0.1:8766")
    try:
        evt = json.loads(event) if isinstance(event, (str, bytes)) else event
        if "requestContext" not in evt:
            if "triggerName" in evt and "payload" in evt:
                evt = json.loads(evt["payload"])
            if evt.get("job") != "retry_notifications":
                raise APIError(400, "未知内部任务。")
            with LOCK:
                return retry_notifications(store_for(context))
        headers = {str(k).lower(): str(v) for k, v in evt.get("headers", {}).items()}
        origin = headers.get("origin", "")
        method = evt["requestContext"]["http"]["method"].upper()
        path = evt.get("rawPath", "/")
        if origin and origin not in allowed:
            raise APIError(403, "请求来源不受支持。")
        if method == "OPTIONS":
            return response(204, {}, origin)
        if method == "GET" and path == "/health":
            return response(200, {"service": "love-intake", "mailConfigured": mail_ready()}, origin)
        raw = evt.get("body", "")
        if evt.get("isBase64Encoded"):
            raw = base64.b64decode(raw, validate=True).decode("utf8")
        if len(raw.encode()) > 22000:
            raise APIError(413, "内容过长，请精简后再提交。")
        if raw and "application/json" not in headers.get("content-type", ""):
            raise APIError(415, "请使用网页表单提交。")
        body = json.loads(raw) if raw else {}
        if not isinstance(body, dict):
            raise APIError(400, "提交格式不正确。")
        with LOCK:
            store = store_for(context)
            if path.startswith("/api/admin/"):
                if not admin_ok(headers):
                    raise APIError(401, "请先输入管理密钥。")
                result = admin_route(store, method, path, body, evt.get("queryParameters", {}))
            elif method == "POST" and path == "/api/orders":
                if not mail_ready() and os.environ.get("DEV_MODE") != "1":
                    raise APIError(503, "收单通知服务暂未就绪，请稍后再试。")
                result = create_order(store, body, evt["requestContext"]["http"].get("sourceIp", "unknown"))
            else:
                match = re.fullmatch(r"/api/orders/(AZ-[A-F0-9]{16})/payment-claim", path)
                if not match or method != "POST":
                    raise APIError(404, "接口不存在。")
                result = claim_payment(store, match[1], body, headers.get("x-order-token", ""))
        return response(200, result, origin)
    except APIError as exc:
        return response(exc.status, {"error": exc.message}, origin if origin in allowed else "")
    except (ValueError, UnicodeError, TypeError, KeyError):
        return response(400, {"error": "提交格式不正确，请检查后重试。"}, origin if origin in allowed else "")
    except Exception:
        return response(503, {"error": "暂时无法完成提交，请保留内容后重试。"}, origin if origin in allowed else "")


def response(status, data, origin):
    headers = {"Content-Type": "application/json; charset=utf-8", "Cache-Control": "no-store",
               "X-Content-Type-Options": "nosniff", "Vary": "Origin"}
    # FC3's HTTPS gateway already supplies CORS headers on production HTTP
    # requests. Returning another Access-Control-Allow-Origin makes browsers
    # reject the response. Origin is still validated in handler() above.
    if origin and os.environ.get("DEV_MODE") == "1":
        headers.update({"Access-Control-Allow-Origin": origin,
                        "Access-Control-Allow-Methods": "GET,POST,OPTIONS",
                        "Access-Control-Allow-Headers": "Content-Type,Authorization,X-Order-Token",
                        "Access-Control-Max-Age": "600"})
    return {"statusCode": status, "headers": headers, "isBase64Encoded": False,
            "body": json.dumps(data, ensure_ascii=False)}
