import logging
from flask import Blueprint, request, jsonify
from flask import send_from_directory
import os, uuid
from werkzeug.utils import secure_filename
from ..infra.repository import (
    list_console_orders, accept_order, complete_order, metrics_today, metrics_range,
    list_store_items, create_store_item, update_store_item, toggle_store_item, sort_store_items,
    list_stores_by_merchant, update_store, get_store,
    list_store_categories, create_store_category, get_merchant_by_slug, sort_store_categories,
    authenticate_merchant_user, update_merchant, verify_order
)
from ..services.storage_service import upload_file_stream, get_presigned_url

logger = logging.getLogger('log')


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

@merchant_bp.route('/store_console/items', methods=['GET'])
def get_items():
    store_id = request.args.get("store_id")
    if not store_id:
        return jsonify({"error": "store_id required"}), 400
    return jsonify(list_store_items(store_id))

@merchant_bp.route('/store_console/items', methods=['POST'])
def post_item():
    payload = request.get_json(force=True) or {}
    try:
        return jsonify(create_store_item(payload))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@merchant_bp.route('/store_console/items/<item_id>', methods=['PUT'])
def put_item(item_id):
    payload = request.get_json(force=True) or {}
    try:
        return jsonify(update_store_item(item_id, payload))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@merchant_bp.route('/store_console/items/<item_id>/toggle', methods=['POST'])
def toggle_item(item_id):
    try:
        return jsonify(toggle_store_item(item_id))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@merchant_bp.route('/store_console/items/sort', methods=['POST'])
def sort_items():
    payload = request.get_json(force=True) or {}
    store_id = payload.get("store_id")
    ordered_ids = payload.get("ordered_ids", [])
    try:
        return jsonify(sort_store_items(store_id, ordered_ids))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@merchant_bp.route('/store_console/categories/sort', methods=['POST'])
def sort_categories():
    payload = request.get_json(force=True) or {}
    store_id = payload.get("store_id")
    ordered_ids = payload.get("ordered_ids", [])
    try:
        return jsonify(sort_store_categories(store_id, ordered_ids))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@merchant_bp.route('/store_console/store', methods=['PUT'])
def put_store():
    payload = request.get_json(force=True) or {}
    store_id = payload.get("id")
    if not store_id:
         return jsonify({"error": "id required"}), 400
    try:
        return jsonify(update_store(store_id, payload))
    except Exception as e:
        return jsonify({"error": str(e)}), 400

@merchant_bp.route('/store_console/store', methods=['GET'])
def get_store_info():
    store_id = request.args.get("id")
    if not store_id:
         return jsonify({"error": "id required"}), 400
    return jsonify(get_store(store_id))

@merchant_bp.route('/store_console/orders/verify', methods=['POST'])
def verify_order_endpoint():
    """
    商家核销订单
    POST { "store_id": "...", "code": "..." }
    """
    payload = request.get_json(force=True) or {}
    store_id = payload.get("store_id")
    code = payload.get("code")
    
    if not store_id or not code:
        return jsonify({"error": "missing_params", "message": "缺少参数"}), 400
        
    res = verify_order(store_id, code)
    if "error" in res:
        return jsonify(res), 400
    return jsonify(res)
