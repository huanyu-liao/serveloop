from flask import Blueprint, request, jsonify
from flask import send_from_directory
import os, uuid
from werkzeug.utils import secure_filename
from ..infra.repository import (
    list_console_orders, accept_order, complete_order, metrics_today, metrics_range,
    list_store_items, create_store_item, update_store_item, toggle_store_item, sort_store_items,
    list_stores_by_merchant, update_store, get_store,
    list_store_categories, create_store_category, get_merchant_by_slug, sort_store_categories,
    authenticate_merchant_user, update_merchant
)
from ..services.storage_service import upload_file_stream, get_presigned_url

merchant_bp = Blueprint('merchant', __name__)
UPLOAD_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "uploads"))
ALLOWED_IMAGE_EXTS = {"png", "jpg", "jpeg", "gif", "webp"}


@merchant_bp.route('/merchant/login', methods=['POST'])
def login():
    """
    商户端登录接口
    POST Body: { "username": "xxx", "password": "xxx" }
    """
    payload = request.get_json(force=True) or {}
    username = payload.get("username")
    password = payload.get("password")
    
    if not username or not password:
        return jsonify({"error": "Missing credentials"}), 400
        
    user = authenticate_merchant_user(username, password)
    if user:
        # 简单返回用户信息作为 Token (实际应使用 JWT)
        # 前端需存储 merchant_id (UUID), store_id, role
        return jsonify(user)
        
    return jsonify({"error": "Invalid username or password"}), 401


@merchant_bp.route('/merchant_console/stores', methods=['GET'])
def list_my_stores():
    """
    商家端-获取我的门店列表
    Query: merchant_id (可读ID 或 UUID)
    """
    mid_input = request.args.get("merchant_id", "m1")
    
    # 尝试将输入视为 Slug 解析
    m = get_merchant_by_slug(mid_input)
    if m:
        # 如果是有效的 Slug，使用其 UUID 查询
        mid = m["id"]
    else:
        # 否则假设它是 UUID (或者查不到)
        mid = mid_input
        
    return jsonify(list_stores_by_merchant(mid))


@merchant_bp.route('/store_console/orders', methods=['GET'])
def list_orders_endpoint():
    """
    商家端订单列表
    Query: status (CREATED | PAID | MAKING | DONE)
    """
    status = request.args.get("status")
    return jsonify(list_console_orders(status))


@merchant_bp.route('/store_console/orders/<order_id>/accept', methods=['POST'])
def accept_order_endpoint(order_id):
    """
    商家接单
    PAID -> MAKING
    """
    res = accept_order(order_id)
    if "error" in res:
        return jsonify(res), 400
    return jsonify(res)


@merchant_bp.route('/store_console/orders/<order_id>/complete', methods=['POST'])
def complete_order_endpoint(order_id):
    """
    商家出餐
    MAKING -> DONE
    """
    res = complete_order(order_id)
    if "error" in res:
        return jsonify(res), 400
    return jsonify(res)


@merchant_bp.route('/store_console/metrics/today', methods=['GET'])
def get_today_metrics():
    """
    今日经营数据
    包含：订单数、实收金额、制作进度统计
    """
    store_id = request.args.get("store_id")
    # 如果没传 store_id，repository.metrics_today 会使用当前 tenant_id 查所有
    # 但前端 dashboard 通常是针对单店的
    # 如果传了 store_id，metrics_today 需要支持按 store_id 过滤
    return jsonify(metrics_today(store_id))

@merchant_bp.route('/store_console/metrics', methods=['GET'])
def get_metrics_by_range():
    """
    时间范围经营数据
    Query: start=YYYY-MM-DD|ts, end=YYYY-MM-DD|ts, store_id
    """
    start = request.args.get("start")
    end = request.args.get("end")
    store_id = request.args.get("store_id")
    return jsonify(metrics_range(start, end, store_id))


@merchant_bp.route('/store_console/categories', methods=['GET'])
def get_categories():
    store_id = request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
    return jsonify(list_store_categories(store_id))


@merchant_bp.route('/store_console/categories', methods=['POST'])
def post_category():
    payload = request.get_json(force=True) or {}
    try:
        return jsonify(create_store_category(payload))
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@merchant_bp.post("/store_console/categories/sort")
def post_categories_sort():
    payload = request.get_json(force=True) or {}
    store_id = payload.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
        
    ordered_ids = payload.get("ordered_ids") or []
    try:
        cats = sort_store_categories(store_id, ordered_ids)
        return jsonify(cats)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@merchant_bp.route('/store_console/items', methods=['GET'])
def get_items():
    store_id = request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
    data = list_store_items(store_id)
    return jsonify(data)


@merchant_bp.post("/store_console/items")
def post_item():
    payload = request.get_json(force=True) or {}
    try:
        item = create_store_item(payload)
        return jsonify(item)
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@merchant_bp.put("/store_console/items/<item_id>")
def put_item(item_id):
    payload = request.get_json(force=True) or {}
    item = update_store_item(item_id, payload)
    if not item:
        return jsonify({"error": "not_found"}), 404
    return jsonify(item)


@merchant_bp.post("/store_console/items/<item_id>/toggle")
def post_item_toggle(item_id):
    payload = request.get_json(force=True) or {}
    status = str(payload.get("status", "ON"))
    item = toggle_store_item(item_id, status)
    if not item:
        return jsonify({"error": "not_found"}), 404
    return jsonify(item)


@merchant_bp.post("/store_console/items/sort")
def post_items_sort():
    payload = request.get_json(force=True) or {}
    store_id = payload.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
        
    ordered_ids = payload.get("ordered_ids") or []
    items = sort_store_items(store_id, ordered_ids)
    return jsonify(items)


@merchant_bp.get("/merchant_console/info")
def get_merchant_info():
    """获取商户信息（含配置）"""
    mid = request.args.get("merchant_id")
    if not mid:
        return jsonify({"error": "merchant_id required"}), 400
        
    # Get by UUID
    from ..infra.models import Merchant
    m = Merchant.query.get(mid)
    if not m:
        return jsonify({"error": "not_found"}), 404
    banner_key = m.banner_url or ""
    banner_display_url = ""
    if banner_key:
        try:
            tmp = get_presigned_url(banner_key)
            if tmp:
                banner_display_url = tmp
        except Exception:
            banner_display_url = ""
    return jsonify({
        "id": m.id,
        "slug": m.slug,
        "name": m.name,
        "plan": m.plan,
        "banner_url": banner_key,
        "banner_display_url": banner_display_url,
        "theme_style": m.theme_style
    })


@merchant_bp.get("/store_console/info")
def get_store_info():
    """获取门店信息（含状态）"""
    store_id = request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
        
    info = get_store(store_id)
    if not info:
        return jsonify({"error": "not_found"}), 404
        
    # 处理 logo_url：如果是 cloud:// 或 相对路径 key，尝试获取临时链接供前端显示
    key = info.get("features", {}).get("logo_url")
    
    try:
        # 提取 path 部分
        # cloud://env.bucket/path/to/file
        # split by / at index 3?
        signed_url = get_presigned_url(key)
        if signed_url:
            info["features"]["logo_display_url"] = signed_url
    except:
        pass
             
    return jsonify(info)



@merchant_bp.post("/store_console/status")
def post_store_status():
    """切换门店营业状态"""
    payload = request.get_json(force=True) or {}
    store_id = payload.get("store_id")
    if not store_id:
         return jsonify({"error": "store_id required"}), 400
         
    status = str(payload.get("status", "OPEN")) # OPEN/CLOSED
    
    res = update_store(store_id, {"status": status})
    if not res:
        return jsonify({"error": "not_found"}), 404
    return jsonify(res)

@merchant_bp.put("/store_console/info")
def put_store_info():
    """更新门店信息：logo_url、address、business_hours、cuisines"""
    payload = request.get_json(force=True) or {}
    store_id = payload.get("store_id") or request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
    update_payload = {}
    for k in ["logo_url", "address", "business_hours", "cuisines", "rating"]:
        if k in payload:
            update_payload[k] = payload[k]
    res = update_store(store_id, update_payload)
    if not res:
        return jsonify({"error": "not_found"}), 404
    return jsonify(res)

@merchant_bp.post("/merchant_console/upload")
def merchant_upload():
    """商户端图片上传（用于门店Logo等）"""
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file provided"}), 400
    filename = secure_filename(f.filename)
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext not in ALLOWED_IMAGE_EXTS:
        return jsonify({"error": "Unsupported file type"}), 400
    
    # 使用 storage_service 上传
    # user_id 暂时用 merchant_id 或 guest
    # 实际应该从 token 获取 user_id，这里简化
    user_id = "merchant_console" 
    
    try:
        log.info("upload_file_stream:", user_id, filename)
        res = upload_file_stream(user_id, filename, f.read(), f.content_type)
        # res: { key, url, file_id(optional) }
        return jsonify(res)
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@merchant_bp.put("/merchant_console/config")
def put_merchant_config():
    """Update merchant global config (banner_url, theme_style)"""
    payload = request.get_json(force=True) or {}
    merchant_id = payload.get("merchant_id")
    if not merchant_id:
        return jsonify({"error": "merchant_id required"}), 400
        
    update_data = {}
    if "banner_url" in payload:
        update_data["banner_url"] = payload["banner_url"]
    
    if "theme_style" in payload:
        update_data["theme_style"] = payload["theme_style"]
        
    if not update_data:
        return jsonify({"ok": True})
        
    res = update_merchant(merchant_id, update_data)
    if not res:
        return jsonify({"error": "not_found"}), 404
    return jsonify(res)

# Deprecated Store Config - Redirect or keep for backward compat (but logic changed)
@merchant_bp.put("/store_console/config")
def put_store_config():
    """
    Deprecated: Config is now Global. 
    Ideally this should call merchant update if user has permission.
    """
    # For now, return error or mock success to prompt user to use new flow?
    # Or just silently update merchant if we can resolve it?
    # Let's return error to force frontend update
    return jsonify({"error": "Config is now managed at Merchant level. Please use Merchant Settings."}), 400
