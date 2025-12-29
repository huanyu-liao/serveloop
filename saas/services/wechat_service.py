import os
import uuid
import time
import hashlib

def jsapi_unified_order(appid: str, mchid: str, openid: str, description: str, out_trade_no: str, amount_cents: int, notify_url: str) -> dict:
    mode = os.getenv("WX_PAY_MODE", "MOCK").upper()
    if mode != "REAL":
        return {"prepay_id": uuid.uuid4().hex}
    return {"prepay_id": uuid.uuid4().hex}

def build_jsapi_params(appid: str, prepay_id: str, private_key: str = "") -> dict:
    ts = str(int(time.time()))
    nonce = uuid.uuid4().hex[:16]
    pkg = "prepay_id=" + prepay_id
    raw = ts + nonce + pkg
    sign = hashlib.md5(raw.encode()).hexdigest()
    return {
        "appId": appid,
        "timeStamp": ts,
        "nonceStr": nonce,
        "package": pkg,
        "signType": "MD5",
        "paySign": sign
    }

def decrypt_notify(resource: dict, apiv3_key: str) -> dict:
    return resource or {}
