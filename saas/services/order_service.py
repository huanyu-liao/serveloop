from typing import Dict, Any
from ..domain.order import new_order, OrderStatus
from ..infra.repository import save_order, get_order, update_order_status, add_points, find_order_by_seq_no_today
from ..infra.context import get_current_tenant_id
import time


from ..infra.models import Item, Store, Coupon, OrderReview, db
from ..infra.context import set_temporary_tenant

def create_order_service(payload: dict) -> dict:
    """
    创建订单服务
    1. 构建订单对象（计算价格、快照化菜品）
    2. 持久化存储
    :param payload: 下单参数
    :return: 订单详情字典
    """
    # 补充 Item 信息 (Price, Name)
    # 必须先获取租户上下文
    store_id = payload.get("store_id")
    if not store_id:
        raise ValueError("store_id required")
        
    store = Store.query.get(store_id)
    if not store:
        raise ValueError("store not found")
        
    with set_temporary_tenant(store.tenant_id):
        scene = payload.get("scene", "TABLE")
        items_payload = payload.get("items", [])
        enriched_items = []
        
        if scene == "COUPON":
            for it in items_payload:
                item_id = it.get("item_id")
                if not item_id:
                    continue
                coupon = Coupon.query.get(item_id)
                if not coupon:
                    continue
                
                # 注入优惠券价格和名称
                rule = coupon.rule or {}
                it["price_cents"] = rule.get("price_cents", 0)
                it["name"] = rule.get("title", "特价券")
                enriched_items.append(it)
        else:
            for it in items_payload:
                item_id = it.get("item_id")
                if not item_id:
                    continue
                item = Item.query.get(item_id)
                if not item:
                    continue
                    
                # 注入真实价格和名称
                it["price_cents"] = item.base_price_cents
                it["name"] = item.name
                # TODO: 计算 specs 加价
                
                enriched_items.append(it)
        
        payload["items"] = enriched_items
        
        order = new_order(payload)
        save_order(order)
        return order.to_dict()


def accept_order_service(order_id: str) -> dict:
    """
    商家接单服务
    将订单状态从 PAID 变更为 MAKING
    """
    if not update_order_status(order_id, OrderStatus.MAKING):
        return {"error": "invalid_transition"}
    return {"ok": True, "status": OrderStatus.MAKING}


def complete_order_service(order_id: str) -> dict:
    """
    商家出餐/核销服务
    将订单状态从 MAKING/WAIT_USE 变更为 DONE
    """
    # 读取订单以计算积分
    order = get_order(order_id)
    if not order:
        return {"error": "not_found"}
    
    # Transition to DONE (待评价)
    # 无论是外卖/堂食(MAKING) 还是 优惠券(WAIT_USE)，都流转到 DONE
    if not update_order_status(order_id, OrderStatus.DONE):
        return {"error": "invalid_transition"}
    # 完成后累计积分 (100分 = 1元)
    points = order.price_payable_cents // 100
    if points > 0:
        add_points(order.user_id, points)
    return {"ok": True, "status": OrderStatus.DONE}

def verify_order_service(store_id: str, code: str) -> dict:
    """
    核销服务
    根据核销码(Order ID 或 Seq No) 查找并核销订单
    """
    # 1. Try Order ID
    order = get_order(code)
    if not order:
        # 2. Try Seq No
        order = find_order_by_seq_no_today(store_id, code)
    
    if not order:
        return {"error": "not_found", "message": "核销码无效或订单不存在"}
        
    if order.store_id != store_id:
        return {"error": "invalid_store", "message": "非本店订单"}
        
    # Check status
    if order.status == OrderStatus.DONE:
        return {"error": "already_used", "message": "订单已核销"}
        
    # 允许核销的状态：WAIT_USE (优惠券), MAKING (自提/堂食)
    if order.status not in [OrderStatus.WAIT_USE, OrderStatus.MAKING]:
        return {"error": "invalid_status", "message": f"订单状态不可核销: {order.status.value}"}
        
    # Perform verification (complete order)
    res = complete_order_service(order.id)
    if "error" in res:
         # Map error codes to friendly messages
         if res["error"] == "invalid_transition":
             return {"error": "invalid_transition", "message": "状态流转失败"}
         return res
         
    return {"ok": True, "order": order.to_dict()}
