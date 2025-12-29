from ..infra.repository import get_order, update_order_status, save_payment, charge_wallet, add_points
from ..domain.order import OrderStatus


def pay_order_service(order_id: str, channel: str = "WX_JSAPI") -> dict:
    """
    处理订单支付逻辑
    :param order_id: 订单ID
    :param channel: 支付渠道 (WX_JSAPI | WALLET)
    :return: 支付结果或错误信息
    """
    order = get_order(order_id)
    if not order:
        return {"error": "not_found"}
        
    # 处理余额支付扣减
    if channel == "WALLET":
        if not charge_wallet(order.user_id, order.price_payable_cents):
            return {"error": "insufficient_balance"}
    
    # 状态机流转：CREATED -> PAID
    if not update_order_status(order_id, OrderStatus.PAID):
        return {"error": "invalid_transition"}
        
    payment = {
        "id": f"pm_{order_id}",
        "order_id": order_id,
        "status": "SUCCESS",
        "amount_cents": order.price_payable_cents,
        "channel": channel,
    }
    save_payment(payment)
    
    # 支付成功后赠送积分 (100分 = 1元)
    points = order.price_payable_cents // 100
    if points > 0:
        add_points(order.user_id, points)
        
    return {"ok": True, "payment": payment}

