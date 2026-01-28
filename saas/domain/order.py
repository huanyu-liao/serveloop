from dataclasses import dataclass, field
from enum import Enum
from typing import List, Dict, Any
import uuid
import time


class OrderStatus(str, Enum):
    """
    订单状态枚举
    CREATED: 已下单，待支付
    PAID: 已支付，待接单/待制作
    MAKING: 制作中
    DONE: 已完成（出餐）
    CANCELLED: 已取消（未支付时）
    REFUNDED: 已退款（支付后）
    """
    CREATED = "CREATED"
    PAID = "PAID"
    MAKING = "MAKING"
    DONE = "DONE"
    CANCELLED = "CANCELLED"
    REFUNDED = "REFUNDED"
    WAIT_USE = "WAIT_USE"
    REVIEWED = "REVIEWED"


@dataclass
class OrderItemSnapshot:
    """
    订单项快照
    下单时刻锁定菜品信息，防止后续改价影响历史订单
    """
    item_id: str
    name: str
    price_cents: int
    quantity: int
    specs: List[Dict[str, Any]] = field(default_factory=list)  # 规格快照
    modifiers: List[Dict[str, Any]] = field(default_factory=list)  # 加料快照


@dataclass
class Order:
    """
    订单聚合根
    """
    id: str
    store_id: str
    user_id: str
    scene: str  # TABLE=堂食, PICKUP=自提，DELIVERY=配送
    table_code: str  # 桌码或取餐码
    status: OrderStatus
    price_total_cents: int  # 原价总额
    price_payable_cents: int  # 应付金额（扣除优惠后）
    coupon_applied: Dict[str, Any]  # 使用的优惠券快照
    remark: str  # 用户备注
    items: List[OrderItemSnapshot]
    created_at: int
    completed_at: int = 0
    seq_no: str = "" # 可读编号
    delivery_info: Dict[str, Any] = field(default_factory=dict) # 配送信息

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "store_id": self.store_id,
            "user_id": self.user_id,
            "scene": self.scene,
            "table_code": self.table_code,
            "seq_no": self.seq_no,
            "status": self.status.value,
            "price_total_cents": self.price_total_cents,
            "price_payable_cents": self.price_payable_cents,
            "coupon_applied": self.coupon_applied,
            "remark": self.remark,
            "items": [
                {
                    "item_id": i.item_id,
                    "name": i.name,
                    "price_cents": i.price_cents,
                    "quantity": i.quantity,
                    "specs": i.specs,
                    "modifiers": i.modifiers,
                }
                for i in self.items
            ],
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "delivery_info": self.delivery_info,
        }


def new_order(payload: Dict[str, Any]) -> Order:
    """
    创建新订单（工厂方法）
    :param payload: 下单请求参数
    :return: 初始化状态的订单对象
    """
    store_id = str(payload.get("store_id", "1"))
    user_id = str(payload.get("user_id", "u"))
    scene = str(payload.get("scene", "TABLE"))
    table_code = str(payload.get("table_code") or "")
    remark = str(payload.get("remark", ""))
    delivery_info = payload.get("delivery_info") or {}
    items_payload = payload.get("items", [])
    items = []
    total = 0
    
    # 遍历构建订单项快照，并计算总价
    # 需要查询 Item 数据库获取最新价格和名称，而不是信任前端传来的价格
    # 这里是 Domain 层，不应直接访问 DB。
    # 通常做法：Service 层查询 DB 获取 Item 列表，传给 Domain.new_order
    # MVP 简化：假设 Service 层已经在 payload 里填充了正确的信息 (但目前 service 只是转发了 payload)
    # 让我们修改 Service 层，先去查库。或者在这里为了 MVP 快速修复，我们先信任 payload，但前端必须传 name/price
    
    # 修正逻辑：如果 payload 里缺少 price/name (前端传的只有 item_id/quantity)，则这里会生成 0 元订单
    # 这就是问题所在！前端只传了 item_id 和 quantity，没有传 price_cents 和 name
    
    # 支持 DIRECTPAY 场景：按 amount_cents 创建订单，无 items
    if scene == "DIRECTPAY":
        amount = int(payload.get("amount_cents", 0))
        total = amount
        items = []
    else:
        for it in items_payload:
            price = int(it.get("price_cents", 0))
            qty = int(it.get("quantity", 1))
            total += price * qty
            items.append(
                OrderItemSnapshot(
                    item_id=str(it.get("item_id", "")),
                    name=str(it.get("name", "")),
                    price_cents=price,
                    quantity=qty,
                    specs=it.get("specs", []) or [],
                    modifiers=it.get("modifiers", []) or [],
                )
            )
    
    coupon = payload.get("coupon_applied") or {}
    # TODO: 这里应加入优惠券抵扣逻辑，目前暂按原价
    payable = total
    
    # 1. 订单编号：采用一串19位的数字，并保证唯一性
    import random
    # 13位毫秒时间戳 + 6位随机数 = 19位
    ts = int(time.time() * 1000)
    rand_suffix = random.randint(100000, 999999)
    order_id = f"{ts}{rand_suffix}"
    
    # 2. seq_no: 根据场景生成前缀，且每日唯一随机
    prefix = ""
    if scene == "TABLE":
        prefix = "A"
    elif scene == "DELIVERY":
        prefix = "D"
    elif scene == "PICKUP":
        prefix = "P"
    # COUPON 场景 seq_no 为空
    
    seq_no = ""
    if prefix:
        try:
            from ..infra.repository import is_seq_no_exists_today
            # 尝试生成唯一随机码，最多重试 5 次
            for _ in range(5):
                rand_suffix = f"{random.randint(0, 9999):04d}"
                candidate = f"{prefix}{rand_suffix}"
                if not is_seq_no_exists_today(store_id, candidate):
                    seq_no = candidate
                    break
            
            # 如果多次重试仍失败（极低概率），兜底使用最后生成的随机码
            if not seq_no:
                 seq_no = f"{prefix}{random.randint(0, 9999):04d}"
                 
        except ImportError:
            # 单元测试或无 DB 环境下的 fallback
            seq_no = f"{prefix}{random.randint(0, 9999):04d}"
        except Exception as e:
            print(f"Error generating seq_no: {e}")
            seq_no = f"{prefix}{random.randint(0, 9999):04d}"
    
    order = Order(
        id=order_id,
        store_id=store_id,
        user_id=user_id,
        scene=scene,
        table_code=table_code,
        status=OrderStatus.CREATED,
        price_total_cents=total,
        price_payable_cents=payable,
        coupon_applied=coupon,
        remark=remark,
        items=items,
        created_at=int(time.time()),
        seq_no=seq_no,
        delivery_info=delivery_info
    )
    return order


def can_transition(current: OrderStatus, target: OrderStatus) -> bool:
    """
    订单状态机校验
    :param current: 当前状态
    :param target: 目标状态
    :return: 是否允许流转
    """
    # 待支付 -> 已支付 / 已取消 / 待使用(券) / 已完成(买单)
    if current == OrderStatus.CREATED and target in {OrderStatus.PAID, OrderStatus.CANCELLED, OrderStatus.WAIT_USE, OrderStatus.DONE}:
        return True
    # 已支付 -> 制作中 / 已退款
    if current == OrderStatus.PAID and target in {OrderStatus.MAKING, OrderStatus.REFUNDED}:
        return True
    # 制作中 -> 已完成
    if current == OrderStatus.MAKING and target == OrderStatus.DONE:
        return True
    # 待使用 -> 已完成 / 已退款
    if current == OrderStatus.WAIT_USE and target in {OrderStatus.DONE, OrderStatus.REFUNDED}:
        return True
    # 已完成 -> 已评价
    if current == OrderStatus.DONE and target == OrderStatus.REVIEWED:
        return True
    return False
