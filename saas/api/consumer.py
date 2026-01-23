from flask import Blueprint, request, jsonify, current_app
from ..infra.repository import (
    get_menu_by_store,
    create_order,
    list_orders,
    pay_order,
    get_order,
    bind_phone,
    update_member_profile,
    recharge_wallet,
    get_wallet,
    get_store,
    Store,
    get_merchant_by_slug,
    list_stores_by_merchant,
    list_stores,
    create_recharge_order,
    list_recharge_orders,
    confirm_recharge_order
)
from ..infra.models import MemberAddress, db, Merchant, Order
from ..infra.context import set_temporary_tenant
from ..services.wechat_service import jsapi_unified_order, build_jsapi_params, decrypt_notify
from ..infra.models import RechargeOrder
import os, json, time, hmac, hashlib, base64
from urllib import request as urlreq, parse as urlparse

consumer_bp = Blueprint("consumer_bp", __name__)

@consumer_bp.get('/merchants')
def list_merchants_public():
    """
    公开商户列表
    """
    from ..infra.repository import list_merchants
    try:
        ms = list_merchants()
        # 兼容前端期望字段，提供合理默认值
        for m in ms:
            m.setdefault("logo_url", "")       # 暂无 logo 字段，留空
            m.setdefault("rating", 4.8)        # 演示默认评分
            m.setdefault("distance_km", 1.2)   # 演示默认距离
            m.setdefault("cuisines", [])       # 暂无菜系字段
            m.setdefault("address_area", "")   # 暂无地址区域字段
        # 若数据库为空，返回一个演示商户，避免前端完全空白
        if not ms:
            ms = [{
                "id": "demo-merchant",
                "slug": "m1",
                "name": "示例商户",
                "plan": "pro",
                "banner_url": "",
                "theme_style": "light",
                "logo_url": "",
                "rating": 4.8,
                "distance_km": 1.2,
                "cuisines": ["咖啡", "简餐"],
                "address_area": "朝阳区"
            }]
        return jsonify(ms)
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500

@consumer_bp.get('/stores')
def list_stores_public():
    """
    公开门店列表（聚合所有商户）
    """
    try:
        ss = list_stores()
        # 展平必要字段，便于前端展示
        res = []
        for s in ss:
            feats = s.get("features") or {}
            logo = feats.get("logo_url", "")
            if isinstance(logo, str) and logo.startswith("/"):
                logo = request.url_root.rstrip("/") + logo
            res.append({
                "id": s.get("id"),
                "name": s.get("name"),
                "merchant_id": s.get("merchant_id"),
                "logo_url": logo,
                "rating": feats.get("rating", 4.8),
                "cuisines": feats.get("cuisines", []),
                "address": feats.get("address", ""),
                "address_area": feats.get("address_area", ""),
                "distance_km": 1.2
            })
        if not res:
            res = [{
                "id": "demo-store",
                "name": "示例门店",
                "merchant_id": "demo-merchant",
                "logo_url": "",
                "rating": 4.8,
                "cuisines": ["咖啡", "简餐"],
                "address": "演示地址",
                "address_area": "朝阳区",
                "distance_km": 1.2
            }]
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": "server_error", "detail": str(e)}), 500

@consumer_bp.route('/auth/login', methods=['POST'])
def auth_login():
    payload = request.get_json(force=True) or {}
    code = payload.get("code")
    if not code:
        return jsonify({"error": "code required"}), 400

    appid = os.getenv("WECHAT_APPID") or request.headers.get("X-WX-AppID")
    secret = os.getenv("WECHAT_APPSECRET") or request.headers.get("X-WX-AppSecret")

    if not appid or not secret:
        return jsonify({"error": "missing_wechat_config"}), 400
        
    url = (
        "https://api.weixin.qq.com/sns/jscode2session?" +
        urlparse.urlencode({
            "appid": appid,
            "secret": secret,
            "js_code": code,
            "grant_type": "authorization_code"
        })
    )
    try:
        resp = urlreq.urlopen(url, timeout=5)
        data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        return jsonify({"error": "wechat_api_error", "detail": str(e)}), 500
    if data.get("errcode"):
        return jsonify({
            "error": "wechat_api_error",
            "code": data.get("errcode"),
            "detail": data.get("errmsg")
        }), 400
    openid = data.get("openid")
    if not openid:
        return jsonify({"error": "openid_missing"}), 400
    iat = int(time.time())
    exp = iat + 7 * 24 * 3600
    header_json = {"alg": "HS256", "typ": "JWT"}
    payload_json = {"sub": openid, "iat": iat, "exp": exp}
    signing_input = base64.urlsafe_b64encode(json.dumps(header_json, separators=(",", ":")).encode()).rstrip(b"=").decode() + "." + \
                    base64.urlsafe_b64encode(json.dumps(payload_json, separators=(",", ":")).encode()).rstrip(b"=").decode()
    secret_key = current_app.config.get("SECRET_KEY", "dev")
    signature = hmac.new(secret_key.encode(), signing_input.encode(), hashlib.sha256).digest()
    token = signing_input + "." + base64.urlsafe_b64encode(signature).rstrip(b"=").decode()
    return jsonify({
        "token": token,
        "user_id": openid,
        "openid": openid
    })

@consumer_bp.route('/auth/phone', methods=['POST'])
def auth_phone():
    """
    Get WeChat Phone Number
    Payload: { "code": "...", "encryptedData": "...", "iv": "..." }
    """
    # In real world: decrypt data using session_key
    # Here: just return a mock phone number
    return jsonify({
        "phone": "13800138000",
        "countryCode": "86"
    })

@consumer_bp.route('/merchants/<merchant_slug>/stores', methods=['GET'])
def list_merchant_stores_public(merchant_slug):
    """
    获取商户下的所有门店（公开）
    """
    # 1. Resolve merchant slug to UUID
    m_info = get_merchant_by_slug(merchant_slug)
    if not m_info:
        # Fallback: check if slug is actually a UUID
        from ..infra.models import Merchant
        m = Merchant.query.get(merchant_slug)
        if m:
            m_info = {
                "id": m.id, 
                "name": m.name,
                "banner_url": m.banner_url,
                "theme_style": m.theme_style
            }
        else:
            return jsonify({"error": "merchant_not_found"}), 404
            
    merchant_id = m_info["id"]
    
    # 2. List stores
    stores = list_stores_by_merchant(merchant_id)

    print(stores)
    
    # Return wrapper with merchant info
    return jsonify({
        "merchant": m_info,
        "stores": stores
    })

@consumer_bp.get('/merchants/<merchant_slug>/decoration')
def get_merchant_decoration(merchant_slug):
    m_info = get_merchant_by_slug(merchant_slug)
    if not m_info:
        m = Merchant.query.get(merchant_slug)
        if not m:
            return jsonify({"error": "merchant_not_found"}), 404
        return jsonify({
            "id": m.id,
            "slug": m.slug,
            "name": m.name,
            "banner_url": m.banner_url or "",
            "theme_style": m.theme_style or "light"
        })
    return jsonify({
        "id": m_info["id"],
        "slug": m_info.get("slug"),
        "name": m_info.get("name"),
        "banner_url": m_info.get("banner_url") or "",
        "theme_style": m_info.get("theme_style") or "light"
    })
@consumer_bp.route('/member/assets', methods=['GET'])
def get_member_assets():
    """
    获取会员资产（余额、积分、优惠券数量）
    Query: merchant_id (UUID 或 slug)
    Header: X-User-ID
    """
    user_id = request.headers.get("X-User-ID", "guest")
    merchant_input = request.args.get("merchant_id") or request.args.get("merchant_slug") or request.args.get("merchant")
    if not merchant_input:
        # 平台级会员资产：跨所有商户聚合
        from ..infra.models import Member, Wallet
        mems = Member.query.filter_by(user_id=user_id).all()
        total_points = 0
        nickname = ""
        for mem in mems:
            try:
                total_points += getattr(mem, "points", 0) or 0
            except Exception:
                pass
            if not nickname:
                nickname = getattr(mem, "nickname", "") or ""
        wallets = Wallet.query.filter_by(user_id=user_id).all()
        total_balance = 0
        for w in wallets:
            try:
                total_balance += getattr(w, "balance_cents", 0) or 0
            except Exception:
                pass
        return jsonify({
            "balance_cents": int(total_balance),
            "points": int(total_points),
            "coupon_count": 0,
            "nickname": nickname
        })
    
    # 兼容旧逻辑：按单个商户返回会员资产
    if not merchant_input:
        merchant_input = request.headers.get("X-Tenant-ID")
    if not merchant_input:
        return jsonify({"error": "merchant_id required"}), 400
    
    m = Merchant.query.get(merchant_input)
    if m:
        tenant_id = m.id
    else:
        m_info = get_merchant_by_slug(merchant_input)
        if not m_info:
            return jsonify({"error": "merchant_not_found"}), 404
        tenant_id = m_info["id"]
    
    with set_temporary_tenant(tenant_id):
        w = get_wallet(user_id)
        from ..infra.models import Member, Coupon
        mem = Member.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
        points = mem.points if mem else 0
        nickname = getattr(mem, "nickname", "") if mem else ""
        coupon_count = 0
        return jsonify({
            "balance_cents": w.get("balance_cents", 0),
            "points": points,
            "coupon_count": coupon_count,
            "nickname": nickname
        })

@consumer_bp.route('/stores/<store_id>', methods=['GET'])
def get_store_info_public(store_id):
    """
    获取门店公开信息
    """
    store = get_store(store_id)
    if not store:
        return jsonify({"error": "not_found"}), 404
    
    s_obj = Store.query.get(store_id)
    m_banner = ""
    m_theme = "light"
    if s_obj:
        m = Merchant.query.get(s_obj.tenant_id)
        if m:
            m_banner = m.banner_url or ""
            m_theme = m.theme_style or "light"
    feats = store.get("features") or {}
    logo = feats.get("logo_url", "")
    if isinstance(logo, str) and logo.startswith("/"):
        logo = request.url_root.rstrip("/") + logo
    rating = feats.get("rating", 4.8)
    monthly_sales = feats.get("monthly_sales")
    if monthly_sales is None:
        try:
            now = int(time.time())
            last_30_days = now - 30 * 24 * 3600
            monthly_sales = Order.query.filter_by(store_id=store_id).filter(Order.status == "DONE", Order.created_at >= last_30_days).count()
        except Exception:
            monthly_sales = 0
    return jsonify({
        "id": store["id"],
        "name": store["name"],
        "merchant_id": store["merchant_id"],
        "status": store["status"],
        "banner_url": m_banner,
        "theme_style": m_theme,
        "logo_url": logo,
        "rating": rating,
        "monthly_sales": int(monthly_sales or 0)
    })

@consumer_bp.route('/stores/<store_id>/menu', methods=['GET'])
def get_store_menu(store_id):
    """
    获取门店菜单
    """
    # 必须切换到租户上下文，否则 filter_by(tenant_id) 会过滤失败或报错
    store = Store.query.get(store_id)
    if not store:
        return jsonify({"error": "store_not_found"}), 404
        
    with set_temporary_tenant(store.tenant_id):
        menu = get_menu_by_store(store_id)
        return jsonify(menu)


@consumer_bp.route('/orders', methods=['POST'])
def create_order_endpoint():
    """
    创建订单
    """
    payload = request.get_json()
    # 自动补充 user_id (Mock)
    if "user_id" not in payload:
        payload["user_id"] = request.headers.get("X-User-ID", "guest")
        
    # 如果没传 items，直接报错（防止创建空订单）
    if not payload.get("items"):
         return jsonify({"error": "empty_items"}), 400

    # 租户上下文切换!
    store_id = payload.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
        
    store = Store.query.get(store_id)
    if not store:
        return jsonify({"error": "store_not_found"}), 404
        
    with set_temporary_tenant(store.tenant_id):
        try:
            # Re-inject store_id into payload just in case, though it should be there
            # Also ensure scene, table_code, etc. are correct if logic needs them
            order = create_order(payload)
            return jsonify(order)
        except Exception as e:
            # Log error stack trace for debugging 500s or hidden errors
            import traceback
            traceback.print_exc()
            return jsonify({"error": str(e)}), 400


@consumer_bp.route('/orders/<order_id>/pay', methods=['POST'])
def pay_order_endpoint(order_id):
    """
    支付订单
    """
    payload = request.get_json() or {}
    channel = payload.get("channel", "WX_JSAPI")
    res = pay_order(order_id, channel)
    if "error" in res:
        return jsonify(res), 400
    return jsonify(res)

@consumer_bp.post('/orders/<order_id>/prepay')
def pay_order_prepay(order_id):
    payload = request.get_json(force=True) or {}
    openid = payload.get("openid") or request.headers.get("X-User-ID", "guest")
    order = get_order(order_id)
    if not order:
        return jsonify({"error": "not_found"}), 404
    store_id = order.store_id
    s = Store.query.get(store_id)
    if not s:
        return jsonify({"error": "store_not_found"}), 404
    m = Merchant.query.get(s.tenant_id)
    appid = request.headers.get("X-WX-AppID") or (m.slug if m else "")
    mchid = request.headers.get("X-WX-MchID") or ""
    notify_url = request.url_root.rstrip("/") + "/api/orders/pay/notify"
    prepay = jsapi_unified_order(appid, mchid, openid, "Order Payment", order.id, order.price_payable_cents, notify_url, request.remote_addr)
    if prepay.get("error"):
        return jsonify(prepay), 400
    params = build_jsapi_params(appid, prepay.get("prepay_id", ""))
    return jsonify({
        "order_id": order.id,
        "timeStamp": params["timeStamp"],
        "nonceStr": params["nonceStr"],
        "package": params["package"],
        "signType": params["signType"],
        "paySign": params["paySign"]
    })


@consumer_bp.route('/wallet', methods=['GET'])
def get_my_wallet():
    """
    查询会员钱包余额
    Query: merchant_id (UUID 或 slug，用于定位租户)
    Header: X-User-ID
    """
    merchant_input = request.args.get("merchant_id") or request.args.get("merchant_slug") or request.args.get("merchant")
    if not merchant_input:
        merchant_input = request.headers.get("X-Tenant-ID")
    if not merchant_input:
        return jsonify({"error": "merchant_id required"}), 400
    
    user_id = request.headers.get("X-User-ID", "guest")
    
    # 解析为租户UUID
    m = Merchant.query.get(merchant_input)
    if m:
        tenant_id = m.id
    else:
        m_info = get_merchant_by_slug(merchant_input)
        if not m_info:
            return jsonify({"error": "merchant_not_found"}), 404
        tenant_id = m_info["id"]
    
    with set_temporary_tenant(tenant_id):
        return jsonify(get_wallet(user_id))


@consumer_bp.route('/wallet/recharge', methods=['POST'])
def recharge_my_wallet():
    """
    会员储值充值
    POST Body:
    { "merchant_id": "<slug or uuid>", "amount_cents": 10000 }
    Header: X-User-ID
    """
    payload = request.get_json()
    merchant_input = payload.get("merchant_id") or payload.get("merchant_slug") or request.headers.get("X-Tenant-ID")
    if not merchant_input:
        return jsonify({"error": "merchant_id required"}), 400
        
    user_id = request.headers.get("X-User-ID", "guest")
    amount = int(payload.get("amount_cents", 0))
    
    if amount <= 0:
        return jsonify({"error": "invalid_amount"}), 400
        
    # 充值活动规则: 充100送10 (10000分送1000分)
    bonus = 0
    if amount >= 10000:
        bonus = 1000
        
    total_add = amount + bonus
    
    # 获取租户上下文（按商户）
    m = Merchant.query.get(merchant_input)
    if m:
        tenant_id = m.id
    else:
        m_info = get_merchant_by_slug(merchant_input)
        if not m_info:
            return jsonify({"error": "merchant_not_found"}), 404
        tenant_id = m_info["id"]
        
    with set_temporary_tenant(tenant_id):
        # 注意：这里直接修改余额，实际项目应创建充值订单->支付->回调
        # MVP直接模拟充值成功
        res = recharge_wallet(user_id, total_add)
        res["bonus_cents"] = bonus
        return jsonify(res)

@consumer_bp.post("/wallet/recharge/prepay")
def wallet_recharge_prepay():
    payload = request.get_json(force=True) or {}
    merchant_input = payload.get("merchant_id") or payload.get("merchant_slug") or request.headers.get("X-Tenant-ID")
    if not merchant_input:
        return jsonify({"error": "merchant_id required"}), 400
    user_id = request.headers.get("X-User-ID", "guest")
    amount = int(payload.get("amount_cents", 0))
    if amount <= 0:
        return jsonify({"error": "invalid_amount"}), 400
    bonus = 0
    if amount >= 10000:
        bonus = 1000
    openid = payload.get("openid") or user_id
    m = Merchant.query.get(merchant_input)
    if m:
        tenant_id = m.id
    else:
        m_info = get_merchant_by_slug(merchant_input)
        if not m_info:
            return jsonify({"error": "merchant_not_found"}), 404
        tenant_id = m_info["id"]
    with set_temporary_tenant(tenant_id):
        order = create_recharge_order(user_id, amount, bonus, "WX_JSAPI")
        appid = request.headers.get("X-WX-AppID") or (Merchant.query.get(tenant_id).slug if Merchant.query.get(tenant_id) else "")
        mchid = request.headers.get("X-WX-MchID") or ""
        notify_url = (request.url_root.rstrip("/") + "/api/wallet/recharge/notify")
        prepay = jsapi_unified_order(appid, mchid, openid, "Wallet Recharge", order["id"], amount, notify_url)
        params = build_jsapi_params(appid, prepay.get("prepay_id", ""))
        return jsonify({
            "order_id": order["id"],
            "timeStamp": params["timeStamp"],
            "nonceStr": params["nonceStr"],
            "package": params["package"],
            "signType": params["signType"],
            "paySign": params["paySign"]
        })

@consumer_bp.post("/wallet/recharge/confirm")
def wallet_recharge_confirm():
    payload = request.get_json(force=True) or {}
    order_id = payload.get("order_id")
    if not order_id:
        return jsonify({"error": "order_id required"}), 400
    user_id = request.headers.get("X-User-ID", "guest")
    ro = confirm_recharge_order(order_id)
    if "error" in ro:
        return jsonify(ro), 404
    return jsonify(ro)

@consumer_bp.get("/wallet/recharge/orders")
def wallet_recharge_orders():
    merchant_input = request.args.get("merchant_id") or request.args.get("merchant_slug") or request.headers.get("X-Tenant-ID")
    if not merchant_input:
        return jsonify({"error": "merchant_id required"}), 400
    user_id = request.headers.get("X-User-ID", "guest")
    m = Merchant.query.get(merchant_input)
    if m:
        tenant_id = m.id
    else:
        m_info = get_merchant_by_slug(merchant_input)
        if not m_info:
            return jsonify({"error": "merchant_not_found"}), 404
        tenant_id = m_info["id"]
    with set_temporary_tenant(tenant_id):
        data = list_recharge_orders(user_id)
        return jsonify(data)

@consumer_bp.post("/wallet/recharge/notify")
def wallet_recharge_notify():
    payload = request.get_json(force=True) or {}
    resource = payload.get("resource") or {}
    apiv3_key = ""
    data = decrypt_notify(resource, apiv3_key)
    out_trade_no = data.get("out_trade_no")
    if not out_trade_no:
        return jsonify({"code": "FAIL"}), 400
    ro = RechargeOrder.query.get(out_trade_no)
    if not ro:
        return jsonify({"code": "FAIL"}), 404
    with set_temporary_tenant(ro.tenant_id):
        res = confirm_recharge_order(out_trade_no)
        return jsonify({"code": "SUCCESS"})


@consumer_bp.get("/orders")
def get_orders():
    """
    查询我的订单
    Query: store_id
    Header: X-User-ID
    """
    store_id = request.args.get("store_id")
    status = request.args.get("status")
    
    # 同样需要租户上下文来过滤
    if store_id:
        store = Store.query.get(store_id)
        if store:
             with set_temporary_tenant(store.tenant_id):
                 # 这里 list_orders 内部其实没按 user_id 过滤，MVP 假设 list_orders 应该过滤 user_id
                 # 但 repository.list_orders 目前是查所有。我们需要修改 list_orders 支持 user_id 过滤
                 # 暂时先全部返回，或者在 consumer.py 过滤
                 data = list_orders(status)
                 # 过滤当前用户
                 user_id = request.headers.get("X-User-ID", "guest")
                 my_orders = [o for o in data if o["user_id"] == user_id]
                 return jsonify(my_orders)
                 
    return jsonify([])


@consumer_bp.post("/members/bind_phone")
def post_bind_phone():
    payload = request.get_json(force=True) or {}
    merchant_input = payload.get("merchant_id") or payload.get("merchant_slug") or request.headers.get("X-Tenant-ID")
    if not merchant_input:
        return jsonify({"error": "merchant_id required"}), 400
        
    # 用户唯一标识改为手机号
    phone = str(payload.get("phone", "")).strip()
    if not phone:
        return jsonify({"error": "phone required"}), 400
    payload["user_id"] = phone
    
    m = Merchant.query.get(merchant_input)
    if m:
        tenant_id = m.id
    else:
        m_info = get_merchant_by_slug(merchant_input)
        if not m_info:
            return jsonify({"error": "merchant_not_found"}), 404
        tenant_id = m_info["id"]
        
    with set_temporary_tenant(tenant_id):
        result = bind_phone(payload)
        return jsonify(result)

@consumer_bp.post("/members/profile")
def post_member_profile():
    payload = request.get_json(force=True) or {}
    merchant_input = payload.get("merchant_id") or payload.get("merchant_slug") or request.headers.get("X-Tenant-ID")
    if not merchant_input:
        return jsonify({"error": "merchant_id required"}), 400
    payload["user_id"] = request.headers.get("X-User-ID", "guest")
    m = Merchant.query.get(merchant_input)
    if m:
        tenant_id = m.id
    else:
        m_info = get_merchant_by_slug(merchant_input)
        if not m_info:
            return jsonify({"error": "merchant_not_found"}), 404
        tenant_id = m_info["id"]
    with set_temporary_tenant(tenant_id):
        result = update_member_profile(payload)
        return jsonify(result)

@consumer_bp.get("/members/profile")
def get_member_profile():
    """
    获取会员资料（按商户/租户隔离）
    Query: merchant_id 或 merchant_slug
    Header: X-User-ID
    """
    merchant_input = request.args.get("merchant_id") or request.args.get("merchant_slug") or request.headers.get("X-Tenant-ID")
    if not merchant_input:
        return jsonify({"error": "merchant_id required"}), 400
    user_id = request.headers.get("X-User-ID", "guest")
    m = Merchant.query.get(merchant_input)
    if m:
        tenant_id = m.id
    else:
        m_info = get_merchant_by_slug(merchant_input)
        if not m_info:
            return jsonify({"error": "merchant_not_found"}), 404
        tenant_id = m_info["id"]
    from ..infra.models import Member
    from ..infra.repository import _ensure_member_profile_columns
    with set_temporary_tenant(tenant_id):
        # 保障缺失列（老库）在运行时补齐
        try:
            _ensure_member_profile_columns()
        except Exception:
            pass
        mem = Member.query.filter_by(user_id=user_id, tenant_id=tenant_id).first()
        # 统一返回前端所需字段，暂未存储的字段使用合理默认值
        return jsonify({
            "user_id": user_id,
            "phone": getattr(mem, "phone", "") if mem else "",
            "nickname": getattr(mem, "nickname", "") if mem else "",
            "points": getattr(mem, "points", 0) if mem else 0,
            "realname": getattr(mem, "realname", "") if mem else "",
            "gender": getattr(mem, "gender", "male") if mem else "male",
            "birthday": getattr(mem, "birthday", "") if mem else "",
            "avatar_url": getattr(mem, "avatar_url", "") if mem else ""
        })
# --- Address APIs ---

@consumer_bp.route('/member/addresses', methods=['GET'])
def list_addresses():
    store_id = request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
        
    user_id = request.headers.get("X-User-ID", "guest")
    
    store = Store.query.get(store_id)
    if not store:
        return jsonify({"error": "store_not_found"}), 404
        
    with set_temporary_tenant(store.tenant_id):
        addrs = MemberAddress.query.filter_by(user_id=user_id, tenant_id=store.tenant_id).order_by(MemberAddress.created_at.desc()).all()
        return jsonify([a.to_dict() for a in addrs])

@consumer_bp.route('/member/addresses', methods=['POST'])
def create_address():
    payload = request.get_json()
    store_id = payload.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
    
    user_id = request.headers.get("X-User-ID", "guest")
    
    store = Store.query.get(store_id)
    if not store:
        return jsonify({"error": "store_not_found"}), 404
        
    with set_temporary_tenant(store.tenant_id):
        count = MemberAddress.query.filter_by(user_id=user_id, tenant_id=store.tenant_id).count()
        if count >= 20:
             return jsonify({"error": "address_limit_reached"}), 400
             
        import uuid
        import time
        addr = MemberAddress(
            id=uuid.uuid4().hex,
            tenant_id=store.tenant_id,
            user_id=user_id,
            name=payload.get("name"),
            phone=payload.get("phone"),
            address=payload.get("address"),
            detail=payload.get("detail", ""),
            is_default=payload.get("is_default", False),
            created_at=int(time.time())
        )
        
        if addr.is_default:
            MemberAddress.query.filter_by(user_id=user_id, tenant_id=store.tenant_id).update({"is_default": False})
            
        db.session.add(addr)
        db.session.commit()
        return jsonify(addr.to_dict())

@consumer_bp.route('/member/addresses/<addr_id>', methods=['PUT'])
def update_address(addr_id):
    payload = request.get_json()
    store_id = payload.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
        
    user_id = request.headers.get("X-User-ID", "guest")
    store = Store.query.get(store_id)
    if not store:
        return jsonify({"error": "store_not_found"}), 404
        
    with set_temporary_tenant(store.tenant_id):
        addr = MemberAddress.query.filter_by(id=addr_id, user_id=user_id, tenant_id=store.tenant_id).first()
        if not addr:
            return jsonify({"error": "address_not_found"}), 404
            
        if "name" in payload: addr.name = payload["name"]
        if "phone" in payload: addr.phone = payload["phone"]
        if "address" in payload: addr.address = payload["address"]
        if "detail" in payload: addr.detail = payload["detail"]
        if "is_default" in payload:
            addr.is_default = payload["is_default"]
            if addr.is_default:
                 MemberAddress.query.filter(MemberAddress.id != addr_id, MemberAddress.user_id == user_id, MemberAddress.tenant_id == store.tenant_id).update({"is_default": False})
        
        db.session.commit()
        return jsonify(addr.to_dict())

@consumer_bp.route('/member/addresses/<addr_id>', methods=['DELETE'])
def delete_address(addr_id):
    store_id = request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
        
    user_id = request.headers.get("X-User-ID", "guest")
    store = Store.query.get(store_id)
    if not store:
        return jsonify({"error": "store_not_found"}), 404
        
    with set_temporary_tenant(store.tenant_id):
        addr = MemberAddress.query.filter_by(id=addr_id, user_id=user_id, tenant_id=store.tenant_id).first()
        if addr:
            db.session.delete(addr)
            db.session.commit()
        return jsonify({"ok": True})
