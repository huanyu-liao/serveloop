from typing import Dict, Any, List, Optional
import time
from sqlalchemy import func
from werkzeug.security import generate_password_hash, check_password_hash
from .models import db, Merchant, Store, Category, Item, Order, OrderItem, Payment, Member, Wallet, Coupon, MerchantUser, RechargeOrder, OrderReview
from ..domain.order import Order as DomainOrder, OrderStatus, can_transition, OrderItemSnapshot
from .context import get_current_tenant_id, set_temporary_tenant
from sqlalchemy import func, text

# 兼容旧接口的 Repository 层

def _get_tenant_filter():
    """
    获取当前租户过滤条件
    """
    tid = get_current_tenant_id()
    return tid

def _apply_tenant_filter(query):
    """
    给查询附加租户过滤
    安全加固：如果没有租户上下文，强制返回空结果（防止越权）
    """
    tid = _get_tenant_filter()
    if tid:
        return query.filter_by(tenant_id=tid)
    
    # 强制 1=0，查不到任何数据
    return query.filter(text("1=0"))

import uuid

def _ensure_seed_db():
    """
    初始化示例数据到数据库
    """
    # 种子数据初始化时，可能没有租户上下文，或者我们手动指定
    # 这里不做租户隔离检查，直接插入
    # 检查是否已有商户
    if Merchant.query.first():
        return

    # 创建示例商户
    m_uuid = uuid.uuid4().hex
    m = Merchant(id=m_uuid, slug="m1", name="示例商户", plan="pro")
    db.session.add(m)
        
    # 创建示例门店
    s_uuid = uuid.uuid4().hex
    s = Store(id=s_uuid, slug="1", name="示例门店", tenant_id=m_uuid, features={"wallet": True, "campaign": True, "member": True})
    db.session.add(s)
    
    # Menu
    c1 = Category(id="c1", store_id=s_uuid, tenant_id=m_uuid, name="热销", sort=1)
    c2 = Category(id="c2", store_id=s_uuid, tenant_id=m_uuid, name="饮品", sort=2)
    db.session.add_all([c1, c2])
    
    i1 = Item(id="i1", store_id=s_uuid, tenant_id=m_uuid, category_id="c1", name="拿铁", base_price_cents=2800, status="ON", sort=1)
    i2 = Item(id="i2", store_id=s_uuid, tenant_id=m_uuid, category_id="c1", name="美式", base_price_cents=2200, status="ON", sort=2)
    db.session.add_all([i1, i2])
        
    try:
        db.session.commit()
    except Exception as e:
        db.session.rollback()
        print(f"Seed error: {e}")

# --- Merchant ---

def list_merchants() -> List[Dict[str, Any]]:
    # Admin 接口，通常不需要租户隔离，或者只能看自己的
    # 这里假设是超级管理员
    ms = Merchant.query.all()
    return [{
        "id": m.id,
        "slug": m.slug,
        "name": m.name,
        "plan": m.plan,
        "banner_url": getattr(m, "banner_url", "") or "",
        "theme_style": getattr(m, "theme_style", "light") or "light"
    } for m in ms]

def create_merchant(payload: Dict[str, Any]) -> Dict[str, Any]:
    slug = payload.get("slug")
    if not slug:
        raise ValueError("Slug is required")
    if Merchant.query.filter_by(slug=slug).first():
        raise ValueError("Slug already exists")

    mid = uuid.uuid4().hex
    m = Merchant(
        id=mid,
        slug=slug,
        name=payload.get("name") or f"商户{slug}",
        plan=payload.get("plan") or "basic"
    )
    db.session.add(m)
    db.session.commit()
    return {"id": m.id, "slug": m.slug, "name": m.name, "plan": m.plan}

def update_merchant(merchant_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # 优先根据 UUID 查找，如果找不到再尝试根据 Slug 查找
    m = Merchant.query.get(merchant_id)
    if not m:
        m = Merchant.query.filter_by(slug=merchant_id).first()
        
    if not m:
        return None
        
    if "name" in payload:
        m.name = str(payload["name"])
    if "plan" in payload:
        m.plan = str(payload["plan"])
        
    if "banner_url" in payload:
        m.banner_url = str(payload["banner_url"])
    if "theme_style" in payload:
        m.theme_style = str(payload["theme_style"])
        
    db.session.commit()
    return {
        "id": m.id, 
        "slug": m.slug, 
        "name": m.name, 
        "plan": m.plan,
        "banner_url": m.banner_url,
        "theme_style": m.theme_style
    }

def delete_merchant(merchant_id: str) -> bool:
    # 优先根据 UUID 查找，如果找不到再尝试根据 Slug 查找
    m = Merchant.query.get(merchant_id)
    if not m:
        m = Merchant.query.filter_by(slug=merchant_id).first()
        
    if not m:
        return False
        
    # 需要级联删除相关数据? 暂时只删除 Merchant 本身，实际业务可能需要软删除或级联
    db.session.delete(m)
    db.session.commit()
    return True

def get_merchant_by_slug(slug: str) -> Optional[Dict[str, Any]]:
    m = Merchant.query.filter_by(slug=slug).first()
    if not m:
        return None
    return {
        "id": m.id, 
        "slug": m.slug, 
        "name": m.name, 
        "plan": m.plan,
        "banner_url": m.banner_url,
        "theme_style": m.theme_style
    }

# --- Merchant Users ---

def list_merchant_users(merchant_id: str) -> List[Dict[str, Any]]:
    users = MerchantUser.query.filter_by(tenant_id=merchant_id).all()
    return [{
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "store_id": u.store_id,
        "created_at": u.created_at
    } for u in users]

def create_merchant_user(merchant_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # Check username uniqueness (globally or per tenant? Let's do per tenant for now, but safer globally)
    if MerchantUser.query.filter_by(username=payload['username']).first():
         raise ValueError("Username already exists")
    
    uid = f"u{int(time.time())}"
    u = MerchantUser(
        id=uid,
        tenant_id=merchant_id,
        store_id=payload.get("store_id"), # Optional
        username=payload["username"],
        password_hash=generate_password_hash(payload["password"], method='pbkdf2:sha256'),
        role=payload.get("role", "STORE_ADMIN"),
        created_at=int(time.time())
    )
    db.session.add(u)
    db.session.commit()
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "store_id": u.store_id,
        "created_at": u.created_at
    }

def update_merchant_user(user_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    u = MerchantUser.query.get(user_id)
    if not u:
        return None
        
    if "password" in payload and payload["password"]:
        u.password_hash = generate_password_hash(payload["password"], method='pbkdf2:sha256')
    if "role" in payload:
        u.role = payload["role"]
    if "store_id" in payload:
        u.store_id = payload["store_id"]
        
    db.session.commit()
    return {
        "id": u.id,
        "username": u.username,
        "role": u.role,
        "store_id": u.store_id,
        "created_at": u.created_at
    }

def delete_merchant_user(user_id: str) -> bool:
    u = MerchantUser.query.get(user_id)
    if not u:
        return False
    db.session.delete(u)
    db.session.commit()
    return True

def authenticate_merchant_user(username: str, password: str) -> Optional[Dict[str, Any]]:
    # username is unique per tenant, but since we don't know tenant_id at login,
    # we assume username is globally unique OR we require merchant_slug/id to be passed (User story doesn't specify)
    # But wait, MerchantUser model has 'username' which we assumed to be unique.
    # Let's find by username.
    u = MerchantUser.query.filter_by(username=username).first()
    if not u:
        return None
    
    if check_password_hash(u.password_hash, password):
        # Resolve merchant slug
        m = Merchant.query.get(u.tenant_id)
        merchant_slug = m.slug if m else ""
        
        return {
            "id": u.id,
            "username": u.username,
            "role": u.role,
            "merchant_id": u.tenant_id, # UUID
            "merchant_slug": merchant_slug, # Readable ID
            "store_id": u.store_id
        }
    return None

# --- Store ---

def list_stores(merchant_id: Optional[str] = None) -> List[Dict[str, Any]]:
    # Admin 接口
    q = Store.query
    if merchant_id:
        q = q.filter_by(tenant_id=merchant_id)
    ss = q.all()
    # merchant_id property 映射到 tenant_id
    res = []
    for s in ss:
        feats = dict(s.features or {})
        try:
            avg_rating = db.session.query(func.avg(OrderReview.rating))\
                .join(Order, OrderReview.order_id == Order.id)\
                .filter(Order.store_id == s.id, OrderReview.rating > 0).scalar()
        except Exception:
            avg_rating = None
        res.append({
            "id": s.id,
            "slug": s.slug,
            "name": s.name,
            "merchant_id": s.tenant_id,
            "status": s.status,
            "features": {
                **feats,
                "address": feats.get("address", ""),
                "logo_url": feats.get("logo_url", ""),
                "cuisines": feats.get("cuisines", []),
                "business_hours": feats.get("business_hours", ""),
                "rating": avg_rating if avg_rating is not None else None,
                "wallet": feats.get("wallet", False),
                "campaign": feats.get("campaign", False),
                "member": feats.get("member", True)
            },
            "rating": float(avg_rating) if avg_rating is not None else None
        })
    return res

def list_stores_by_merchant(merchant_id: str) -> List[Dict[str, Any]]:
    # 显式查询指定商户
    ss = Store.query.filter_by(tenant_id=merchant_id).all()
    res = []
    for s in ss:
        feats = dict(s.features or {})
        try:
            avg_rating = db.session.query(func.avg(OrderReview.rating))\
                .join(Order, OrderReview.order_id == Order.id)\
                .filter(Order.store_id == s.id, OrderReview.rating > 0).scalar()
        except Exception:
            avg_rating = None
        res.append({
            "id": s.id,
            "slug": s.slug,
            "name": s.name,
            "merchant_id": s.tenant_id,
            "address": feats.get("address", ""),
            "logo_url": feats.get("logo_url", ""),
            "cuisines": feats.get("cuisines", []),
            "business_hours": feats.get("business_hours", ""),
            "rating": float(avg_rating) if avg_rating is not None else None
        })
    return res

def create_store(payload: Dict[str, Any]) -> Dict[str, Any]:
    merchant_id = str(payload.get("merchant_id", "m1"))
    
    slug = payload.get("slug")
    if not slug:
         raise ValueError("Slug is required")
         
    # 检查当前租户下 slug 是否唯一
    if Store.query.filter_by(tenant_id=merchant_id, slug=slug).first():
        raise ValueError("Store slug already exists in this merchant")

    # 使用 UUID
    sid = uuid.uuid4().hex
    
    # 支持传入 features
    features = payload.get("features")
    if not features:
        features = {"wallet": False, "campaign": False, "member": True}
        
    s = Store(
        id=sid, 
        slug=slug,
        name=payload.get("name") or f"门店{slug}", 
        tenant_id=merchant_id, # 显式设置租户
        features=features
    )
    db.session.add(s)
    db.session.commit()
    return {"id": s.id, "slug": s.slug, "name": s.name, "merchant_id": s.tenant_id}

def update_store(store_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    # Admin 接口，根据ID直接更新
    s = Store.query.get(store_id)
    if not s:
        return None
        
    if "name" in payload:
        s.name = str(payload["name"])
    
    if "slug" in payload:
        # Check uniqueness if changed
        new_slug = str(payload["slug"])
        if new_slug != s.slug:
             if Store.query.filter_by(tenant_id=s.tenant_id, slug=new_slug).first():
                 raise ValueError("Store slug already exists in this merchant")
             s.slug = new_slug
        
    if "status" in payload:
        s.status = str(payload["status"])

    if "features" in payload:
        # 覆盖或合并，这里选择合并更新
        features = dict(s.features or {})
        for k, v in payload["features"].items():
            features[k] = bool(v)
        s.features = features
    
    # 允许直接更新扩展字段（与 features 并存）
    extras = ["logo_url", "address", "cuisines", "business_hours", "rating"]
    if any(k in payload for k in extras):
        features = dict(s.features or {})
        for k in extras:
            if k in payload:
                features[k] = payload[k]
        s.features = features
        
    db.session.commit()
    return {"id": s.id, "slug": s.slug, "name": s.name, "merchant_id": s.tenant_id, "features": s.features}

def delete_store(store_id: str) -> bool:
    s = Store.query.get(store_id)
    if not s:
        return False
    db.session.delete(s)
    db.session.commit()
    return True

def toggle_feature(store_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    # 增加租户校验
    query = Store.query.filter_by(id=store_id)
    query = _apply_tenant_filter(query)
    s = query.first()
    
    if not s:
        return {}
    features = dict(s.features or {})
    for k, v in payload.items():
        features[k] = bool(v)
    s.features = features
    db.session.commit()
    return features

def get_store(store_id: str) -> Optional[Dict[str, Any]]:
    # 通用获取门店信息
    s = Store.query.get(store_id)
    if not s:
        return None
    
    # 2025-01: Config moved to Merchant level
    # Fetch Merchant to get banner and theme
    m = Merchant.query.get(s.tenant_id)
    banner_url = m.banner_url if m else ""
    theme_style = m.theme_style if m else "light"
        
    return {
        "id": s.id,
        "slug": s.slug,
        "name": s.name, 
        "merchant_id": s.tenant_id, 
        "status": s.status, 
        "features": s.features or {},
        "banner_url": banner_url, 
        "theme_style": theme_style
    }

# --- Menu ---

def get_menu_by_store(store_id: str) -> Dict[str, Any]:
    # 自动推导租户上下文
    store = Store.query.get(store_id)
    if not store:
        return {"categories": [], "items": []}
        
    # 使用该 Store 的租户上下文进行查询
    with set_temporary_tenant(store.tenant_id):
        cats_q = Category.query.filter_by(store_id=store_id)
        items_q = Item.query.filter_by(store_id=store_id)
        
        cats_q = _apply_tenant_filter(cats_q)
        items_q = _apply_tenant_filter(items_q)
        
        cats = cats_q.order_by(Category.sort).all()
        items = items_q.order_by(Item.sort).all()
        
        return {
            "categories": [{"id": c.id, "name": c.name, "sort": c.sort} for c in cats],
            "items": [i.to_dict() for i in items]
        }

def list_store_categories(store_id: str) -> List[Dict[str, Any]]:
    q = Category.query.filter_by(store_id=store_id)
    q = _apply_tenant_filter(q)
    cats = q.order_by(Category.sort).all()
    return [{"id": c.id, "name": c.name, "sort": c.sort} for c in cats]

def create_store_category(payload: Dict[str, Any]) -> Dict[str, Any]:
    tid = get_current_tenant_id()
    if not tid:
        raise Exception("Missing tenant context")
    
    store_id = payload.get("store_id")
    if not store_id:
        # 尝试使用默认值（仅用于兼容旧数据，建议废弃）或者报错
        # 由于现在是 UUID，无法猜测默认值，必须由前端传递
        raise Exception("store_id is required")

    store_id = str(store_id)
    store = Store.query.filter_by(id=store_id, tenant_id=tid).first()
    if not store:
        raise Exception("Store not found or access denied")
        
    count = Category.query.filter_by(store_id=store_id).count()
    cid = f"c{int(time.time())}"
    cat = Category(
        id=cid,
        store_id=store_id,
        tenant_id=tid,
        name=str(payload.get("name", "")),
        sort=count + 1
    )
    db.session.add(cat)
    db.session.commit()
    return {"id": cat.id, "name": cat.name, "sort": cat.sort}

def sort_store_categories(store_id: str, ordered_ids: List[str]) -> List[Dict[str, Any]]:
    tid = get_current_tenant_id()
    for idx, cid in enumerate(ordered_ids, start=1):
        q = Category.query.filter_by(id=cid, store_id=store_id)
        if tid:
            q = q.filter_by(tenant_id=tid)
        q.update({"sort": idx})
    db.session.commit()
    return list_store_categories(store_id)

def list_store_items(store_id: str) -> List[Dict[str, Any]]:
    q = Item.query.filter_by(store_id=store_id)
    q = _apply_tenant_filter(q)
    items = q.order_by(Item.sort).all()
    # 填充 category_id
    res = []
    for i in items:
        d = i.to_dict()
        d["category_id"] = i.category_id
        res.append(d)
    return res

def create_store_item(payload: Dict[str, Any]) -> Dict[str, Any]:
    tid = get_current_tenant_id()
    if not tid:
        raise Exception("Missing tenant context")
        
    store_id = str(payload.get("store_id", "1"))
    # 校验 store 是否属于当前租户
    store = Store.query.filter_by(id=store_id, tenant_id=tid).first()
    if not store:
        raise Exception("Store not found or access denied")

    count = Item.query.filter_by(store_id=store_id).count()
    iid = f"i{int(time.time())}" 
    item = Item(
        id=iid,
        store_id=store_id,
        tenant_id=tid, # 自动填充
        name=str(payload.get("name", "")),
        category_id=str(payload.get("category_id", "")),
        image_url=str(payload.get("image_url", "")),
        base_price_cents=int(payload.get("base_price_cents", 0)),
        status=str(payload.get("status", "ON")),
        sort=count + 1
    )
    db.session.add(item)
    db.session.commit()
    return item.to_dict()

def update_store_item(item_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    q = Item.query.filter_by(id=item_id)
    q = _apply_tenant_filter(q)
    item = q.first()
    
    if not item:
        return None
    if "name" in payload:
        item.name = str(payload["name"])
    if "category_id" in payload:
        item.category_id = str(payload["category_id"])
    if "image_url" in payload:
        item.image_url = str(payload["image_url"])
    if "base_price_cents" in payload:
        item.base_price_cents = int(payload["base_price_cents"])
    if "status" in payload:
        item.status = str(payload["status"])
    db.session.commit()
    return item.to_dict()

def toggle_store_item(item_id: str, status: str) -> Optional[Dict[str, Any]]:
    q = Item.query.filter_by(id=item_id)
    q = _apply_tenant_filter(q)
    item = q.first()
    
    if not item:
        return None
    item.status = str(status)
    db.session.commit()
    return item.to_dict()

def sort_store_items(store_id: str, ordered_ids: List[str]) -> List[Dict[str, Any]]:
    tid = get_current_tenant_id()
    # 批量更新需小心，这里循环更新
    for idx, iid in enumerate(ordered_ids, start=1):
        q = Item.query.filter_by(id=iid, store_id=store_id)
        if tid:
            q = q.filter_by(tenant_id=tid)
        q.update({"sort": idx})
    db.session.commit()
    return list_store_items(store_id)

# --- Order ---

def _domain_to_model(o: DomainOrder, tenant_id: str) -> Order:
    return Order(
        id=o.id,
        store_id=o.store_id,
        tenant_id=tenant_id,
        user_id=o.user_id,
        scene=o.scene,
        table_code=o.table_code,
        seq_no=o.seq_no, # Add seq_no
        status=o.status.value,
        price_total_cents=o.price_total_cents,
        price_payable_cents=o.price_payable_cents,
        coupon_applied=o.coupon_applied,
        remark=o.remark,
        created_at=o.created_at,
        delivery_info=o.delivery_info
    )

def _model_to_domain(o: Order) -> DomainOrder:
    # OrderItem 也要过滤 tenant_id
    items_q = OrderItem.query.filter_by(order_id=o.id)
    # 理论上 items 属于 order，order 已经过滤了，items 不需要再严格过滤，但为了保险
    # items_q = _apply_tenant_filter(items_q) 
    order_items = items_q.all()
    
    items_snapshot = [
        OrderItemSnapshot(
            item_id=oi.item_id,
            name=oi.name,
            price_cents=oi.price_cents,
            quantity=oi.quantity,
            specs=oi.specs,
            modifiers=oi.modifiers
        ) for oi in order_items
    ]
    return DomainOrder(
        id=o.id,
        store_id=o.store_id,
        user_id=o.user_id,
        scene=o.scene,
        table_code=o.table_code,
        status=OrderStatus(o.status),
        price_total_cents=o.price_total_cents,
        price_payable_cents=o.price_payable_cents,
        coupon_applied=o.coupon_applied or {},
        remark=o.remark,
        items=items_snapshot,
        created_at=o.created_at,
        completed_at=o.completed_at,
        seq_no=o.seq_no, # Add seq_no
        delivery_info=o.delivery_info or {}
    )

def save_order(domain_order: DomainOrder) -> None:
    tid = get_current_tenant_id()
    # 下单时必须有租户上下文
    # 如果是 consumer api，可能需要从 store 反查，或者 payload 带
    if not tid:
        # 尝试从 store 获取 (MVP Hack)
        store = Store.query.get(domain_order.store_id)
        if store:
            tid = store.tenant_id
            
    q = Order.query.filter_by(id=domain_order.id)
    if tid:
        q = q.filter_by(tenant_id=tid)
    existing = q.first()
    
    if existing:
        existing.status = domain_order.status.value
        existing.price_total_cents = domain_order.price_total_cents
        existing.price_payable_cents = domain_order.price_payable_cents
        existing.coupon_applied = domain_order.coupon_applied
        existing.remark = domain_order.remark
        existing.delivery_info = domain_order.delivery_info
    else:
        if not tid:
             raise Exception("Cannot create order without tenant context")
        o = _domain_to_model(domain_order, tid)
        db.session.add(o)
        
        # 必须先 flush 以生成 order.id (如果 id 是 auto-increment)
        # 这里 id 是传入的，所以不需要 flush，但为了保险还是写上
        # db.session.flush() 
        
        for it in domain_order.items:
            oi = OrderItem(
                order_id=o.id,
                item_id=it.item_id,
                tenant_id=tid, # 填充
                name=it.name,
                price_cents=it.price_cents,
                quantity=it.quantity,
                specs=it.specs,
                modifiers=it.modifiers
            )
            db.session.add(oi)
            
    db.session.commit()

def get_order(order_id: str) -> Optional[DomainOrder]:
    q = Order.query.filter_by(id=order_id)
    q = _apply_tenant_filter(q)
    o = q.first()
    if not o:
        return None
    return _model_to_domain(o)

def update_order_status(order_id: str, target: OrderStatus) -> bool:
    q = Order.query.filter_by(id=order_id)
    q = _apply_tenant_filter(q)
    o = q.first()
    
    if not o:
        return False
    current_status = OrderStatus(o.status)
    if not can_transition(current_status, target):
        return False
    o.status = target.value
    
    # 记录完成时间
    if target == OrderStatus.DONE:
        o.completed_at = int(time.time())
        
    db.session.commit()
    return True

def list_orders(status: Optional[str]) -> List[Dict[str, Any]]:
    q = Order.query
    q = _apply_tenant_filter(q)
    
    if status:
        q = q.filter(func.lower(Order.status) == func.lower(status))
    orders = q.order_by(Order.created_at.desc()).all()
    
    res = []
    for o in orders:
        d = o.to_dict()
        order_items = OrderItem.query.filter_by(order_id=o.id).all()
        # Enrich items with image_url from Item table
        items_dict_list = []
        for oi in order_items:
            oi_dict = oi.to_dict()
            # Fetch item to get image_url
            item = Item.query.filter_by(id=oi.item_id).first()
            if item:
                oi_dict['image_url'] = item.image_url
            items_dict_list.append(oi_dict)
            
        d["items"] = items_dict_list
        # Ensure delivery_info is not None for frontend
        if not d.get("delivery_info"):
            d["delivery_info"] = {}
        res.append(d)
    return res

def list_console_orders(status: Optional[str]) -> List[Dict[str, Any]]:
    return list_orders(status)

def list_orders_by_user(user_id: str, status: Optional[str] = None, store_id: Optional[str] = None) -> List[Dict[str, Any]]:
    q = Order.query.filter_by(user_id=user_id)
    if status:
        q = q.filter(func.lower(Order.status) == func.lower(status))
    if store_id:
        q = q.filter_by(store_id=store_id)
    orders = q.order_by(Order.created_at.desc()).all()
    res = []
    for o in orders:
        d = o.to_dict()
        s = Store.query.get(o.store_id)
        d["store_name"] = s.name if s else ""
        r = OrderReview.query.filter_by(order_id=o.id, user_id=user_id).first()
        d["reviewed"] = True if r else False
        if r:
            d["rating"] = r.rating
        order_items = OrderItem.query.filter_by(order_id=o.id).all()
        items_dict_list = []
        for oi in order_items:
            oi_dict = oi.to_dict()
            item = Item.query.filter_by(id=oi.item_id).first()
            if item:
                oi_dict['image_url'] = item.image_url
            items_dict_list.append(oi_dict)
        d["items"] = items_dict_list
        if not d.get("delivery_info"):
            d["delivery_info"] = {}
        res.append(d)
    return res

def get_order_review(order_id: str, user_id: str) -> Optional[Dict[str, Any]]:
    r = OrderReview.query.filter_by(order_id=order_id, user_id=user_id).first()
    if not r:
        return None
    return r.to_dict()

def upsert_order_review(order_id: str, user_id: str, rating: int, content: str) -> Dict[str, Any]:
    o = Order.query.get(order_id)
    if not o:
        return {"error": "not_found"}
    if o.user_id != user_id:
        return {"error": "forbidden"}
    r = OrderReview.query.filter_by(order_id=order_id, user_id=user_id).first()
    now = int(time.time())
    if r:
        r.rating = int(rating)
        r.content = str(content or "")
        r.updated_at = now
        db.session.commit()
        return r.to_dict()
    rr = OrderReview(
        order_id=order_id,
        tenant_id=o.tenant_id,
        user_id=user_id,
        rating=int(rating),
        content=str(content or ""),
        created_at=now,
        updated_at=now
    )
    db.session.add(rr)
    db.session.commit()
    return rr.to_dict()
def create_order(payload: Dict[str, Any]) -> Dict[str, Any]:
    from ..services.order_service import create_order_service
    return create_order_service(payload)

def pay_order(order_id: str, channel: str = "WX_JSAPI") -> Dict[str, Any]:
    # 自动推导租户上下文
    order = Order.query.get(order_id)
    if not order:
        return {"error": "not_found"}
        
    with set_temporary_tenant(order.tenant_id):
        from ..services.payment_service import pay_order_service
        return pay_order_service(order_id, channel)

def accept_order(order_id: str) -> Dict[str, Any]:
    from ..services.order_service import accept_order_service
    # 确保租户上下文
    from .models import Order
    o = Order.query.get(order_id)
    if not o:
        return {"error": "not_found"}
    with set_temporary_tenant(o.tenant_id):
        return accept_order_service(order_id)

def complete_order(order_id: str) -> Dict[str, Any]:
    from ..services.order_service import complete_order_service
    # 确保租户上下文
    from .models import Order
    o = Order.query.get(order_id)
    if not o:
        return {"error": "not_found"}
    with set_temporary_tenant(o.tenant_id):
        return complete_order_service(order_id)

# --- Payment ---

def save_payment(payment_dict: Dict[str, Any]) -> None:
    # 支付记录也需要 tenant_id，需要先查 order
    order = Order.query.get(payment_dict["order_id"])
    tid = order.tenant_id if order else get_current_tenant_id()
    
    p = Payment(
        id=payment_dict["id"],
        order_id=payment_dict["order_id"],
        tenant_id=tid,
        amount_cents=payment_dict["amount_cents"],
        status=payment_dict["status"],
        channel=payment_dict["channel"],
        created_at=int(time.time())
    )
    db.session.add(p)
    db.session.commit()

# --- Coupon ---

def _ensure_coupon_columns():
    """
    运行时保障：为 coupons 表补充缺失字段
    """
    try:
        existing = set()
        sql = text("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'coupons'")
        rows = db.session.execute(sql).fetchall()
        for r in rows or []:
            c = r[0] if isinstance(r, tuple) else getattr(r, "COLUMN_NAME", None)
            if c:
                existing.add(str(c))
        
        def ensure(col_name, ddl):
            if col_name not in existing:
                db.session.execute(text(ddl))
        
        ensure("store_id", "ALTER TABLE coupons ADD COLUMN store_id VARCHAR(32)")
        db.session.commit()
    except Exception:
        db.session.rollback()

def list_coupons(store_id: Optional[str] = None) -> List[Dict[str, Any]]:
    _ensure_coupon_columns()
    q = Coupon.query
    q = _apply_tenant_filter(q)
    if store_id:
        q = q.filter_by(store_id=store_id)
    cs = q.order_by(Coupon.id.asc()).all()
    return [{"id": c.id, "store_id": c.store_id, "rule": c.rule, "status": c.status} for c in cs]

def create_coupon(payload: Dict[str, Any]) -> Dict[str, Any]:
    _ensure_coupon_columns()
    tid = get_current_tenant_id()
    if not tid:
        raise Exception("Missing tenant context")
        
    count = Coupon.query.filter_by(tenant_id=tid).count()
    cid = str(count + 1)
    c = Coupon(
        id=cid,
        tenant_id=tid,
        store_id=str(payload.get("store_id") or ""),
        rule=payload.get("rule") or {},
        status=str(payload.get("status", "ON"))
    )
    db.session.add(c)
    db.session.commit()
    return {"id": c.id, "store_id": c.store_id, "rule": c.rule, "status": c.status}

def update_coupon(coupon_id: str, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    _ensure_coupon_columns()
    q = Coupon.query.filter_by(id=coupon_id)
    q = _apply_tenant_filter(q)
    c = q.first()
    if not c:
        return None
    if "store_id" in payload:
        c.store_id = str(payload.get("store_id") or "")
    if "rule" in payload and isinstance(payload["rule"], dict):
        c.rule = payload["rule"]
    if "status" in payload:
        c.status = str(payload["status"])
    db.session.commit()
    return {"id": c.id, "store_id": c.store_id, "rule": c.rule, "status": c.status}

def delete_coupon(coupon_id: str) -> bool:
    _ensure_coupon_columns()
    q = Coupon.query.filter_by(id=coupon_id)
    q = _apply_tenant_filter(q)
    c = q.first()
    if not c:
        return False
    db.session.delete(c)
    db.session.commit()
    return True

# --- Member & Wallet ---

def bind_phone(payload: Dict[str, Any]) -> Dict[str, Any]:
    tid = get_current_tenant_id()
    # 必须有 tenant_id，因为 Member 是 TenantMixin
    if not tid:
         # 尝试从 store 获取? payload 如果带 store_id 可以
         # 这里简单假设必须传 header
         raise Exception("Missing tenant context for member binding")
         
    user_id = str(payload.get("user_id", "u"))
    phone = str(payload.get("phone", ""))
    nickname = str(payload.get("nickname", "")).strip()
    _ensure_member_profile_columns()
    
    m = Member.query.filter_by(user_id=user_id, tenant_id=tid).first()
    if not m:
        if not nickname:
            nickname = "用户" + uuid.uuid4().hex[:6]
        m = Member(user_id=user_id, tenant_id=tid, phone=phone, points=0, nickname=nickname)
        db.session.add(m)
    else:
        m.phone = phone
        if nickname:
            m.nickname = nickname
    db.session.commit()
    return {"ok": True, "nickname": m.nickname or ""}

def _ensure_member_profile_columns():
    """
    运行时保障：为 members 表补充缺失的资料字段
    适配 MySQL；其他数据库场景下异常将被忽略（保持后端可用）
    """
    try:
        cols = ["nickname", "realname", "gender", "birthday", "avatar_url", "points", "phone", "user_id", "tenant_id"]
        existing = set()
        sql = text("SELECT COLUMN_NAME FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = 'members'")
        rows = db.session.execute(sql).fetchall()
        for r in rows or []:
            c = r[0] if isinstance(r, tuple) else getattr(r, "COLUMN_NAME", None)
            if c:
                existing.add(str(c))
        def ensure(col_name, ddl):
            if col_name not in existing:
                db.session.execute(text(ddl))
        ensure("nickname", "ALTER TABLE members ADD COLUMN nickname VARCHAR(64) DEFAULT ''")
        ensure("realname", "ALTER TABLE members ADD COLUMN realname VARCHAR(64) DEFAULT ''")
        ensure("gender", "ALTER TABLE members ADD COLUMN gender VARCHAR(16) DEFAULT 'male'")
        ensure("birthday", "ALTER TABLE members ADD COLUMN birthday VARCHAR(32) DEFAULT ''")
        ensure("avatar_url", "ALTER TABLE members ADD COLUMN avatar_url VARCHAR(512) DEFAULT ''")
        db.session.commit()
    except Exception:
        db.session.rollback()

def update_member_profile(payload: Dict[str, Any]) -> Dict[str, Any]:
    tid = get_current_tenant_id()
    if not tid:
        raise Exception("Missing tenant context for member profile")
    _ensure_member_profile_columns()
    user_id = str(payload.get("user_id", "u"))
    nickname = str(payload.get("nickname", "")).strip()
    realname = str(payload.get("realname", "")).strip()
    gender = str(payload.get("gender", "") or "male")
    birthday = str(payload.get("birthday", "")).strip()
    avatar_url = str(payload.get("avatar_url", "")).strip()
    m = Member.query.filter_by(user_id=user_id, tenant_id=tid).first()
    if not m:
        m = Member(user_id=user_id, tenant_id=tid, phone="", points=0, nickname=nickname, realname=realname, gender=gender, birthday=birthday, avatar_url=avatar_url)
        db.session.add(m)
    else:
        if nickname:
            m.nickname = nickname
        if realname is not None:
            m.realname = realname
        if gender:
            m.gender = gender
        if birthday is not None:
            m.birthday = birthday
        if avatar_url is not None:
            m.avatar_url = avatar_url
    db.session.commit()
    return {
        "ok": True,
        "user_id": m.user_id,
        "phone": m.phone or "",
        "nickname": m.nickname or "",
        "realname": m.realname or "",
        "gender": m.gender or "male",
        "birthday": m.birthday or "",
        "avatar_url": m.avatar_url or ""
    }

def get_wallet(user_id: str) -> Dict[str, int]:
    w = Wallet.query.filter_by(user_id=user_id).order_by(Wallet.id.asc()).first()
    balance = w.balance_cents if w else 0
    return {"balance_cents": balance}

def recharge_wallet(user_id: str, amount_cents: int) -> Dict[str, Any]:
    w = Wallet.query.filter_by(user_id=user_id).order_by(Wallet.id.asc()).first()
    if not w:
        # 默认将平台级钱包记录的 tenant_id 固定为 'platform'
        w = Wallet(user_id=user_id, tenant_id="platform", balance_cents=0)
        db.session.add(w)
    w.balance_cents += amount_cents
    db.session.commit()
    return {"balance_cents": w.balance_cents}

def charge_wallet(user_id: str, amount_cents: int) -> bool:
    w = Wallet.query.filter_by(user_id=user_id).order_by(Wallet.id.asc()).first()
    if not w or w.balance_cents < amount_cents:
        return False
    w.balance_cents -= amount_cents
    db.session.commit()
    return True

def create_bill_order(user_id: str, store_id: str, amount_cents: int, remark: str = "") -> Dict[str, Any]:
    """
    创建优惠买单订单（无菜品项）
    """
    store = Store.query.get(store_id)
    if not store:
        raise Exception("store_not_found")
    oid = f"b{int(time.time())}"
    o = Order(
        id=oid,
        store_id=store_id,
        tenant_id=store.tenant_id,
        user_id=user_id,
        scene="BILL",
        table_code="",
        seq_no="",
        status="CREATED",
        price_total_cents=int(amount_cents),
        price_payable_cents=int(amount_cents),
        coupon_applied={},
        remark=remark or "",
        created_at=int(time.time()),
        delivery_info={}
    )
    db.session.add(o)
    db.session.commit()
    return o.to_dict()

def create_recharge_order(user_id: str, amount_cents: int, bonus_cents: int, channel: str = "WX_JSAPI") -> Dict[str, Any]:
    tid = get_current_tenant_id()
    if not tid:
        raise Exception("Missing tenant context")
    rid = uuid.uuid4().hex
    ro = RechargeOrder(
        id=rid,
        tenant_id=tid,
        user_id=user_id,
        amount_cents=amount_cents,
        bonus_cents=bonus_cents,
        status="CREATED",
        channel=channel,
        created_at=int(time.time())
    )
    db.session.add(ro)
    db.session.commit()
    return {
        "id": ro.id,
        "user_id": ro.user_id,
        "amount_cents": ro.amount_cents,
        "bonus_cents": ro.bonus_cents,
        "status": ro.status,
        "channel": ro.channel,
        "created_at": ro.created_at
    }

def get_recharge_order(order_id: str) -> Optional[Dict[str, Any]]:
    q = RechargeOrder.query.filter_by(id=order_id)
    q = _apply_tenant_filter(q)
    ro = q.first()
    if not ro:
        return None
    return {
        "id": ro.id,
        "user_id": ro.user_id,
        "amount_cents": ro.amount_cents,
        "bonus_cents": ro.bonus_cents,
        "status": ro.status,
        "channel": ro.channel,
        "created_at": ro.created_at,
        "paid_at": ro.paid_at
    }

def list_recharge_orders(user_id: Optional[str] = None) -> List[Dict[str, Any]]:
    q = RechargeOrder.query
    q = _apply_tenant_filter(q)
    if user_id:
        q = q.filter_by(user_id=user_id)
    rows = q.order_by(RechargeOrder.created_at.desc()).all()
    return [{
        "id": r.id,
        "user_id": r.user_id,
        "amount_cents": r.amount_cents,
        "bonus_cents": r.bonus_cents,
        "status": r.status,
        "channel": r.channel,
        "created_at": r.created_at,
        "paid_at": r.paid_at
    } for r in rows]

def confirm_recharge_order(order_id: str) -> Dict[str, Any]:
    q = RechargeOrder.query.filter_by(id=order_id)
    q = _apply_tenant_filter(q)
    ro = q.first()
    if not ro:
        return {"error": "not_found"}
    if ro.status == "PAID":
        return {
            "id": ro.id,
            "status": ro.status,
            "paid_at": ro.paid_at
        }
    ro.status = "PAID"
    ro.paid_at = int(time.time())
    db.session.commit()
    added = ro.amount_cents + (ro.bonus_cents or 0)
    res = recharge_wallet(ro.user_id, added)
    return {
        "order_id": ro.id,
        "wallet": res
    }

def add_points(user_id: str, points: int) -> int:
    tid = get_current_tenant_id()
    if not tid:
        # 如果是内部调用（如支付后赠送），支付时应该已经确保了上下文
        # 这里的 user_id 是 domain 的 user_id，如果是支付回调可能没有 request context
        # 需要注意：如果 add_points 在异步队列执行，需手动传递 tenant_id
        return 0 
        
    m = Member.query.filter_by(user_id=user_id, tenant_id=tid).first()
    if not m:
        m = Member(user_id=user_id, tenant_id=tid, phone="", points=0)
        db.session.add(m)
    m.points += points
    db.session.commit()
    return m.points

# --- Metrics ---

def metrics_today(store_id: Optional[str] = None) -> Dict[str, Any]:
    tid = get_current_tenant_id()
    
    # 构造基础查询
    order_q = Order.query
    payment_q = Payment.query
    
    if tid:
        order_q = order_q.filter_by(tenant_id=tid)
        payment_q = payment_q.filter_by(tenant_id=tid)
        
    if store_id:
        order_q = order_q.filter_by(store_id=store_id)
        # Payment 表没有 store_id, 需要 join order 或 先查 order_ids
        # 这里简化处理，payment 统计暂不支持 store_id 过滤 (或者 Payment 应该冗余 store_id)
        # 暂时只过滤 order 相关指标
    
    total = order_q.count()
    
    paid_status = [OrderStatus.PAID.value, OrderStatus.MAKING.value, OrderStatus.DONE.value]
    paid_query = order_q.filter(Order.status.in_(paid_status))
    paid_count = paid_query.count()
    
    revenue = db.session.query(func.sum(Order.price_payable_cents)).filter(
        Order.status.in_(paid_status)
    )
    if tid:
        revenue = revenue.filter(Order.tenant_id == tid)
    if store_id:
        revenue = revenue.filter(Order.store_id == store_id)
        
    revenue_val = revenue.scalar() or 0
    
    # 修改待接单数量逻辑：PAID 状态即为待接单
    pending_count = order_q.filter_by(status=OrderStatus.PAID.value).count()
    making = order_q.filter_by(status=OrderStatus.MAKING.value).count()
    done = order_q.filter_by(status=OrderStatus.DONE.value).count()
    
    payments_wx = payment_q.filter_by(channel="WX_JSAPI").count()
    
    return {
        "orders_total": total,
        "paid": pending_count, # 修正：paid 字段在前端用于显示待接单红点，应为 PAID 状态数量
        "revenue_cents": int(revenue_val),
        "making": making,
        "done": done,
        "payments_wx": payments_wx,
    }

def metrics_range(start: Optional[str], end: Optional[str], store_id: Optional[str] = None) -> Dict[str, Any]:
    """
    按时间范围获取经营数据
    start/end: YYYY-MM-DD 或时间戳（秒）
    """
    tid = get_current_tenant_id()
    def to_ts(v: Optional[str], is_end: bool = False) -> Optional[int]:
        if not v:
            return None
        try:
            # 数字字符串当作秒级时间戳
            if str(v).isdigit():
                ts = int(v)
                return ts
            # 解析 YYYY-MM-DD
            tm = time.strptime(str(v), "%Y-%m-%d")
            base = int(time.mktime(tm))
            return base + (86399 if is_end else 0)
        except Exception:
            return None
    start_ts = to_ts(start, is_end=False)
    end_ts = to_ts(end, is_end=True)
    if not start_ts or not end_ts:
        return metrics_today(store_id)
    
    order_q = Order.query
    payment_q = Payment.query
    
    if tid:
        order_q = order_q.filter_by(tenant_id=tid)
        payment_q = payment_q.filter_by(tenant_id=tid)
    if store_id:
        order_q = order_q.filter_by(store_id=store_id)
    
    order_q = order_q.filter(Order.created_at >= start_ts, Order.created_at <= end_ts)
    
    total = order_q.count()
    
    paid_status = [OrderStatus.PAID.value, OrderStatus.MAKING.value, OrderStatus.DONE.value]
    paid_query = order_q.filter(Order.status.in_(paid_status))
    paid_count = paid_query.count()
    
    revenue = db.session.query(func.sum(Order.price_payable_cents)).filter(
        Order.status.in_(paid_status),
        Order.created_at >= start_ts,
        Order.created_at <= end_ts
    )
    if tid:
        revenue = revenue.filter(Order.tenant_id == tid)
    if store_id:
        revenue = revenue.filter(Order.store_id == store_id)
    revenue_val = revenue.scalar() or 0
    
    pending_count = order_q.filter_by(status=OrderStatus.PAID.value).count()
    making = order_q.filter_by(status=OrderStatus.MAKING.value).count()
    done = order_q.filter_by(status=OrderStatus.DONE.value).count()
    
    payments_wx_q = payment_q.filter_by(channel="WX_JSAPI").filter(
        Payment.created_at >= start_ts,
        Payment.created_at <= end_ts
    )
    if store_id:
        # 通过订单关联过滤门店
        payments_wx_q = payments_wx_q.join(Order, Payment.order_id == Order.id).filter(Order.store_id == store_id)
    payments_wx = payments_wx_q.count()
    
    return {
        "orders_total": total,
        "paid": pending_count,
        "revenue_cents": int(revenue_val),
        "making": making,
        "done": done,
        "payments_wx": payments_wx,
        "range": {"start": start_ts, "end": end_ts}
    }
