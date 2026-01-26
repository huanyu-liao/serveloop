from flask import Flask
from .infra.models import db
from .infra.context import tenant_context_middleware
from flask_cors import CORS
import config

def create_app(test_config=None):
    app = Flask(__name__)
    CORS(app) # 开启全局跨域支持
    
    # 默认配置，可被 test_config 覆盖
    app.config.from_mapping(
        SECRET_KEY='dev',
        SQLALCHEMY_DATABASE_URI='mysql+pymysql://{}:{}@{}/saas_db'.format(config.username, config.password, config.db_address),
        SQLALCHEMY_TRACK_MODIFICATIONS=False,
    )

    if test_config:
        app.config.update(test_config)
        
    db.init_app(app)
    
    # 注册租户上下文中间件
    app.before_request(tenant_context_middleware)

    # 注册蓝图
    from .api.consumer import consumer_bp
    from .api.merchant import merchant_bp
    from .api.admin import admin_bp

    app.register_blueprint(consumer_bp, url_prefix='/api')
    app.register_blueprint(merchant_bp, url_prefix='/api')
    app.register_blueprint(admin_bp, url_prefix='/api')

    
    # 初始化数据库（开发环境方便起见）
    with app.app_context():
        # 尝试创建表（如果不报错）
        try:
            db.create_all()
            from .infra.repository import _ensure_seed_db
            _ensure_seed_db()
        except Exception as e:
            print(f"Warning: DB init failed (maybe connection error): {e}")

    return app

