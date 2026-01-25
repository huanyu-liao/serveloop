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
    
    # 状态机流转：CREATED -> PAID / WAIT_USE / WAIT_COMMENT
    target_status = OrderStatus.PAID
    if order.scene == "COUPON":
        target_status = OrderStatus.WAIT_USE
    elif order.scene == "BILL":
        target_status = OrderStatus.DONE
        
    if not update_order_status(order_id, target_status):
        return {"error": "invalid_transition"}
        
    payment = {
        "id": f"pm_{order_id}",
        "order_id": order_id,
        "status": "SUCCESS",
        "amount_cents": order.price_payable_cents,
        "channel": channel,
    }
    save_payment(payment)
    # 改为在订单完成（DONE）后再累计积分
    return {"ok": True, "payment": payment}
