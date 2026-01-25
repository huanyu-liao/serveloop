from typing import Dict, Any
from ..domain.order import new_order, OrderStatus
from ..infra.repository import save_order, get_order, update_order_status, add_points
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


def refund_order_service(order_id: str) -> dict:
    """
    订单退款服务
    仅支持 COUPON 场景且状态为 WAIT_USE
    """
    order = get_order(order_id)
    if not order:
        return {"error": "not_found"}
    
    if order.scene != "COUPON":
        return {"error": "scene_not_supported"}
        
    if order.status != OrderStatus.WAIT_USE:
        return {"error": "invalid_status"}
        
    # TODO: Call payment refund API (Mock for now)
    # Assume refund success
    
    if not update_order_status(order_id, OrderStatus.REFUNDED):
        return {"error": "invalid_transition"}
        
    return {"ok": True, "status": OrderStatus.REFUNDED}


def review_order_service(order_id: str, payload: dict) -> dict:
    """
    提交评价
    状态 DONE -> REVIEWED
    """
    order = get_order(order_id)
    if not order:
        return {"error": "not_found"}
        
    # Validate transition first
    if not update_order_status(order_id, OrderStatus.REVIEWED):
        return {"error": "invalid_transition"}
        
    # Save review
    rating = int(payload.get("rating", 5))
    content = str(payload.get("content", ""))
    
    # We need tenant context for OrderReview
    tid = get_current_tenant_id()
    # 如果没有租户上下文（理论上不应发生，因为是从API调用的），尝试从订单获取
    if not tid:
         # Hack: 假设 store_id 可以反查（但这里不好查），或者直接存库报错
         # 依赖 API 层设置上下文
         pass
    
    review = OrderReview(
        order_id=order_id,
        user_id=order.user_id,
        tenant_id=tid or "unknown", # Prevent crash
        rating=rating,
        content=content,
        created_at=int(time.time())
    )
    db.session.add(review)
    db.session.commit()
    
    return {"ok": True, "status": OrderStatus.DONE}
