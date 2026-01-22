import os
import uuid
import time
import hashlib
import random
import string
import xml.etree.ElementTree as ET
from urllib import request as urlreq, parse as urlparse

def _nonce_str() -> str:
    return ''.join(random.choice(string.ascii_letters + string.digits) for _ in range(16))

def _sign_v2(params: dict, api_key: str) -> str:
    items = sorted([(k, v) for k, v in params.items() if v is not None and v != "" and k != "sign"])
    raw = "&".join([f"{k}={v}" for k, v in items]) + f"&key={api_key}"
    return hashlib.md5(raw.encode()).hexdigest().upper()

def _dict_to_xml(d: dict) -> str:
    xml = ["<xml>"]
    for k, v in d.items():
        xml.append(f"<{k}><![CDATA[{v}]]></{k}>")
    xml.append("</xml>")
    return "".join(xml)

def _xml_to_dict(x: str) -> dict:
    root = ET.fromstring(x)
    res = {}
    for child in root:
        res[child.tag] = child.text
    return res

def jsapi_unified_order(appid: str, mchid: str, openid: str, description: str, out_trade_no: str, amount_cents: int, notify_url: str, client_ip: str = "127.0.0.1") -> dict:
    mode = (os.getenv("WX_PAY_MODE") or "MOCK").upper()
    if mode != "REAL":
        return {"prepay_id": uuid.uuid4().hex}
    api_key = os.getenv("WX_PAY_V2_KEY") or ""
    if not api_key:
        return {"error": "missing_api_key"}
    params = {
        "appid": appid,
        "mch_id": mchid,
        "nonce_str": _nonce_str(),
        "body": description,
        "out_trade_no": out_trade_no,
        "total_fee": str(int(amount_cents)),
        "spbill_create_ip": client_ip or "127.0.0.1",
        "notify_url": notify_url,
        "trade_type": "JSAPI",
        "openid": openid
    }
    params["sign"] = _sign_v2(params, api_key)
    xml = _dict_to_xml(params)
    url = "https://api.mch.weixin.qq.com/pay/unifiedorder"
    req = urlreq.Request(url, data=xml.encode("utf-8"), headers={"Content-Type": "application/xml"})
    resp = urlreq.urlopen(req, timeout=8)
    data = resp.read().decode("utf-8")
    r = _xml_to_dict(data)
    if r.get("return_code") != "SUCCESS":
        return {"error": "wechat_return_error", "detail": r.get("return_msg", "")}
    if r.get("result_code") != "SUCCESS":
        return {"error": "wechat_result_error", "code": r.get("err_code"), "detail": r.get("err_code_des")}
    return {"prepay_id": r.get("prepay_id")}

def build_jsapi_params(appid: str, prepay_id: str) -> dict:
    ts = str(int(time.time()))
    nonce = _nonce_str()
    pkg = "prepay_id=" + prepay_id
    sign_type = "MD5"
    api_key = os.getenv("WX_PAY_V2_KEY") or ""
    to_sign = {
        "appId": appid,
        "timeStamp": ts,
        "nonceStr": nonce,
        "package": pkg,
        "signType": sign_type
    }
    pay_sign = _sign_v2(to_sign, api_key) if api_key else hashlib.md5((ts + nonce + pkg).encode()).hexdigest()
    return {
        "appId": appid,
        "timeStamp": ts,
        "nonceStr": nonce,
        "package": pkg,
        "signType": sign_type,
        "paySign": pay_sign
    }

def decrypt_notify(resource: dict, apiv3_key: str) -> dict:
    return resource or {}
