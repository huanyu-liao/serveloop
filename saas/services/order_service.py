from typing import Dict, Any
from ..domain.order import new_order, OrderStatus
from ..infra.repository import save_order, get_order, update_order_status, add_points


from ..infra.models import Item, Store
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
        items_payload = payload.get("items", [])
        enriched_items = []
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
    商家出餐服务
    将订单状态从 MAKING 变更为 DONE
    """
    # 读取订单以计算积分
    order = get_order(order_id)
    if not order:
        return {"error": "not_found"}
    if not update_order_status(order_id, OrderStatus.DONE):
        return {"error": "invalid_transition"}
    # 完成后累计积分 (100分 = 1元)
    points = order.price_payable_cents // 100
    if points > 0:
        add_points(order.user_id, points)
    return {"ok": True, "status": OrderStatus.DONE}
