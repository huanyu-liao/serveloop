from flask import Blueprint, request, jsonify, abort
from functools import wraps
from ..infra.repository import (
    list_coupons, create_coupon, 
    list_stores, create_store, update_store, delete_store, toggle_feature,
    list_merchants, create_merchant, get_store, update_merchant, delete_merchant,
    list_merchant_users, create_merchant_user, update_merchant_user, delete_merchant_user
)


admin_bp = Blueprint("admin_bp", __name__)

# 简单的硬编码 Token，实际生产应使用 JWT 或 Session
ADMIN_TOKEN = "saas-admin-token-secret"

def require_admin(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        token = request.headers.get("X-Admin-Token")
        if token != ADMIN_TOKEN:
            return jsonify({"error": "Unauthorized"}), 401
        return f(*args, **kwargs)
    return decorated_function


@admin_bp.post("/admin/login")
def login():
    payload = request.get_json(force=True) or {}
    username = payload.get("username")
    password = payload.get("password")
    
    # 简单的硬编码用户校验
    if username == "admin" and password == "admin":
        return jsonify({"token": ADMIN_TOKEN, "username": "admin"})
    
    return jsonify({"error": "Invalid credentials"}), 401


@admin_bp.route('/admin/merchants', methods=['GET'])
@require_admin
def get_merchants():
    """
    获取商户列表
    """
    return jsonify(list_merchants())


@admin_bp.route('/admin/merchants', methods=['POST'])
@require_admin
def post_merchant():
    """
    创建新商户
    POST Body:
    {
        "slug": "m1",
        "name": "xxx餐饮",
        "plan": "pro"
    }
    """
    payload = request.get_json(force=True) or {}
    try:
        result = create_merchant(payload)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


@admin_bp.put('/admin/merchants/<merchant_id>')
@require_admin
def put_merchant(merchant_id):
    payload = request.get_json(force=True) or {}
    result = update_merchant(merchant_id, payload)
    if not result:
        return jsonify({"error": "Merchant not found"}), 404
    return jsonify(result)


@admin_bp.delete('/admin/merchants/<merchant_id>')
@require_admin
def del_merchant(merchant_id):
    success = delete_merchant(merchant_id)
    if not success:
        return jsonify({"error": "Merchant not found"}), 404
    return jsonify({"ok": True})


@admin_bp.get("/admin/coupons")
@require_admin
def get_coupons():
    data = list_coupons()
    return jsonify(data)


@admin_bp.post("/admin/coupons")
@require_admin
def post_coupon():
    payload = request.get_json(force=True) or {}
    result = create_coupon(payload)
    return jsonify(result)


@admin_bp.get("/admin/stores")
@require_admin
def get_stores():
    merchant_id = request.args.get('merchant_id')
    data = list_stores(merchant_id)
    return jsonify(data)


@admin_bp.post("/admin/stores")
@require_admin
def post_store():
    payload = request.get_json(force=True) or {}
    result = create_store(payload)
    return jsonify(result)


@admin_bp.put("/admin/stores/<store_id>")
@require_admin
def put_store(store_id):
    payload = request.get_json(force=True) or {}
    result = update_store(store_id, payload)
    if result is None:
        return jsonify({"error": "Store not found"}), 404
    return jsonify(result)


@admin_bp.delete("/admin/stores/<store_id>")
@require_admin
def del_store(store_id):
    success = delete_store(store_id)
    if not success:
        return jsonify({"error": "Store not found"}), 404
    return jsonify({"ok": True})


@admin_bp.post("/admin/store/<store_id>/toggle_feature")
@require_admin
def post_toggle_feature(store_id):
    payload = request.get_json(force=True) or {}
    result = toggle_feature(store_id, payload)
    return jsonify(result)

# --- Merchant Users ---

@admin_bp.get("/admin/merchants/<merchant_id>/users")
@require_admin
def get_merchant_users(merchant_id):
    data = list_merchant_users(merchant_id)
    return jsonify(data)

@admin_bp.post("/admin/merchants/<merchant_id>/users")
@require_admin
def post_merchant_user(merchant_id):
    payload = request.get_json(force=True) or {}
    try:
        result = create_merchant_user(merchant_id, payload)
        return jsonify(result)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400

@admin_bp.put("/admin/merchants/<merchant_id>/users/<user_id>")
@require_admin
def put_merchant_user(merchant_id, user_id):
    # merchant_id is not strictly needed for update by user_id but good for URL structure and potential checks
    payload = request.get_json(force=True) or {}
    result = update_merchant_user(user_id, payload)
    if not result:
        return jsonify({"error": "User not found"}), 404
    return jsonify(result)

@admin_bp.delete("/admin/merchants/<merchant_id>/users/<user_id>")
@require_admin
def del_merchant_user(merchant_id, user_id):
    success = delete_merchant_user(user_id)
    if not success:
        return jsonify({"error": "User not found"}), 404
    return jsonify({"ok": True})
