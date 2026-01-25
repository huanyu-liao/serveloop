from flask_sqlalchemy import SQLAlchemy
from sqlalchemy import Column, String, Integer, Text, JSON, BigInteger, Boolean, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase

class Base(DeclarativeBase):
    pass

db = SQLAlchemy(model_class=Base)

# 租户隔离 Mixin
class TenantMixin:
    # 统一使用 tenant_id 字段（对应业务概念 merchant_id）
    # 在新设计中，tenant_id 存储 Merchant 的 UUID
    tenant_id = Column(String(32), nullable=False, index=True)

class Merchant(db.Model):
    __tablename__ = 'merchants'
    id = Column(String(32), primary_key=True) # UUID
    slug = Column(String(64), unique=True, nullable=False) # 可读ID
    name = Column(String(128), nullable=False)
    plan = Column(String(32), default="basic") # basic, pro, enterprise
    
    # 全局配置 (原在Store, 现移至Merchant)
    banner_url = Column(String(512), default="")
    theme_style = Column(String(32), default="light")

class Store(db.Model, TenantMixin):
    __tablename__ = 'stores'
    id = Column(String(32), primary_key=True) # UUID
    slug = Column(String(64), nullable=False) # 可读ID，租户内唯一
    name = Column(String(128), nullable=False)
    status = Column(String(16), default="OPEN") # OPEN/CLOSED
    # 存储功能开关，如 {"wallet": true, ...}
    features = Column(JSON, default=dict)

    __table_args__ = (
        UniqueConstraint('tenant_id', 'slug', name='uix_store_tenant_slug'),
    )

    @property
    def merchant_id(self):
        return self.tenant_id

class Category(db.Model, TenantMixin):
    __tablename__ = 'categories'
    id = Column(String(32), primary_key=True)
    store_id = Column(String(32), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    sort = Column(Integer, default=0)

class Item(db.Model, TenantMixin):
    __tablename__ = 'items'
    id = Column(String(32), primary_key=True)
    store_id = Column(String(32), nullable=False, index=True)
    category_id = Column(String(32), nullable=True)
    name = Column(String(128), nullable=False)
    image_url = Column(String(512), default="")
    base_price_cents = Column(Integer, default=0)
    status = Column(String(16), default="ON") # ON/OFF
    sort = Column(Integer, default=0)
    
    def to_dict(self):
        return {
            "id": self.id,
            "store_id": self.store_id,
            "tenant_id": self.tenant_id,
            "category_id": self.category_id,
            "name": self.name,
            "image_url": self.image_url,
            "base_price_cents": self.base_price_cents,
            "status": self.status,
            "sort": self.sort
        }

class Order(db.Model, TenantMixin):
    __tablename__ = 'orders'
    id = Column(String(64), primary_key=True)
    store_id = Column(String(32), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    scene = Column(String(16), default="TABLE")
    table_code = Column(String(32), default="")
    
    # 增加可读编号
    seq_no = Column(String(16), default="") # A001, B002
    
    status = Column(String(16), default="CREATED", index=True)
    price_total_cents = Column(Integer, default=0)
    price_payable_cents = Column(Integer, default=0)
    coupon_applied = Column(JSON, default=dict)
    remark = Column(String(256), default="")
    created_at = Column(BigInteger, nullable=False)
    
    # 增加完成时间
    completed_at = Column(BigInteger, nullable=True)
    
    # 配送信息快照 {"name": "", "phone": "", "address": "..."}
    delivery_info = Column(JSON, default=dict)
    
    # 关联 OrderItem，暂不使用 relationship，手动查询
    
    def to_dict(self):
        # 注意：items 需要额外填充
        return {
            "id": self.id,
            "store_id": self.store_id,
            "tenant_id": self.tenant_id,
            "user_id": self.user_id,
            "scene": self.scene,
            "table_code": self.table_code,
            "seq_no": self.seq_no,
            "status": self.status,
            "price_total_cents": self.price_total_cents,
            "price_payable_cents": self.price_payable_cents,
            "coupon_applied": self.coupon_applied,
            "remark": self.remark,
            "created_at": self.created_at,
            "completed_at": self.completed_at,
            "delivery_info": self.delivery_info
        }

class OrderItem(db.Model, TenantMixin):
    __tablename__ = 'order_items'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), nullable=False, index=True)
    item_id = Column(String(32), nullable=False)
    name = Column(String(128), nullable=False)
    price_cents = Column(Integer, default=0)
    quantity = Column(Integer, default=1)
    specs = Column(JSON, default=list)
    modifiers = Column(JSON, default=list)
    
    def to_dict(self):
        return {
            "item_id": self.item_id,
            "name": self.name,
            "price_cents": self.price_cents,
            "quantity": self.quantity,
            "specs": self.specs,
            "modifiers": self.modifiers
        }

class Payment(db.Model, TenantMixin):
    __tablename__ = 'payments'
    id = Column(String(64), primary_key=True)
    order_id = Column(String(64), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    status = Column(String(16), default="INIT")
    channel = Column(String(16), default="WX_JSAPI")
    created_at = Column(BigInteger, nullable=True)

class Member(db.Model, TenantMixin):
    __tablename__ = 'members'
    # 会员在每个租户下是隔离的，所以主键需包含 tenant_id
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    phone = Column(String(20), default="")
    nickname = Column(String(64), default="")
    points = Column(Integer, default=0)
    realname = Column(String(64), default="")
    gender = Column(String(16), default="male")
    birthday = Column(String(32), default="")
    avatar_url = Column(String(512), default="")

class Wallet(db.Model, TenantMixin):
    __tablename__ = 'wallets'
    # 钱包在每个租户下隔离
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(String(64), nullable=False, index=True)
    balance_cents = Column(Integer, default=0)

class RechargeOrder(db.Model, TenantMixin):
    __tablename__ = 'recharge_orders'
    id = Column(String(64), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    amount_cents = Column(Integer, nullable=False)
    bonus_cents = Column(Integer, default=0)
    status = Column(String(16), default="CREATED")  # CREATED, PAID
    channel = Column(String(16), default="WX_JSAPI")
    created_at = Column(BigInteger, nullable=True)
    paid_at = Column(BigInteger, nullable=True)

class MemberAddress(db.Model, TenantMixin):
    __tablename__ = 'member_addresses'
    id = Column(String(32), primary_key=True)
    user_id = Column(String(64), nullable=False, index=True)
    name = Column(String(64), nullable=False)
    phone = Column(String(20), nullable=False)
    address = Column(String(256), nullable=False) # Area/Street
    detail = Column(String(256), nullable=False) # Door no
    is_default = Column(Boolean, default=False)
    created_at = Column(BigInteger, nullable=True)
    
    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "phone": self.phone,
            "address": self.address,
            "detail": self.detail,
            "is_default": self.is_default
        }

class Coupon(db.Model, TenantMixin):
    __tablename__ = 'coupons'
    id = Column(String(32), primary_key=True)
    store_id = Column(String(32), nullable=True, index=True)
    rule = Column(JSON, default=dict)
    status = Column(String(16), default="ON")

class MerchantUser(db.Model, TenantMixin):
    __tablename__ = 'merchant_users'
    id = Column(String(32), primary_key=True)
    # tenant_id 来自 TenantMixin，关联 Merchant
    store_id = Column(String(32), nullable=True, index=True) # 若为空，则是商户级超管；若有值，则是门店管理员
    username = Column(String(64), nullable=False) # 建议全局唯一，或者 (tenant_id, username) 唯一
    password_hash = Column(String(256), nullable=False)
    role = Column(String(16), default="STORE_ADMIN") # SUPER_ADMIN / STORE_ADMIN
    created_at = Column(BigInteger, nullable=False)

class OrderReview(db.Model, TenantMixin):
    __tablename__ = 'order_reviews'
    id = Column(Integer, primary_key=True, autoincrement=True)
    order_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    rating = Column(Integer, default=0)
    content = Column(Text, default="")
    created_at = Column(BigInteger, nullable=False)
    updated_at = Column(BigInteger, nullable=True)
    def to_dict(self):
        return {
            "id": self.id,
            "order_id": self.order_id,
            "user_id": self.user_id,
            "rating": self.rating,
            "content": self.content,
            "created_at": self.created_at,
            "updated_at": self.updated_at
        }
