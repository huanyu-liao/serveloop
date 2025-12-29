from flask import g, request, abort
from contextlib import contextmanager

def get_current_tenant_id():
    """
    获取当前上下文的 tenant_id
    """
    tid = g.get('tenant_id')
    return tid

@contextmanager
def set_temporary_tenant(tenant_id):
    """
    临时切换租户上下文（用于 C 端接口自动推导）
    """
    original = g.get('tenant_id')
    g.tenant_id = tenant_id
    try:
        yield
    finally:
        if original is None:
            g.pop('tenant_id', None)
        else:
            g.tenant_id = original

def tenant_context_middleware():
    """
    Flask before_request 钩子
    解析 X-Tenant-ID Header
    """
    if request.path.startswith('/static'):
        return
        
    # 尝试从 Header 获取
    tenant_id = request.headers.get('X-Tenant-ID')
    
    # 兼容：方便调试，也允许 query string
    if not tenant_id:
        tenant_id = request.args.get('tenant_id') or request.args.get('merchant_id')
    
    # 暂不强制拦截，由 Repository 层决定是否需要 tenant_id
    if tenant_id:
        # 尝试解析 Slug -> UUID
        # 如果长度不为32（UUID hex），则尝试作为 Slug 查询商户
        if len(tenant_id) != 32:
            from .models import Merchant
            # 注意：这里可能会在请求早期触发 DB 查询
            m = Merchant.query.filter_by(slug=tenant_id).first()
            if m:
                tenant_id = m.id
                
        g.tenant_id = tenant_id
