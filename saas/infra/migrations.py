from sqlalchemy import text, inspect
from .models import db

def run_auto_migrations():
    """
    简易的自动迁移脚本，用于开发环境自动修补 schema
    """
    try:
        # Use inspector to check columns
        inspector = inspect(db.engine)
        
        # Check orders table
        if inspector.has_table('orders'):
            columns = [c['name'] for c in inspector.get_columns('orders')]
            
            if 'verification_code' not in columns:
                print("Migrating: Adding verification_code to orders table...")
                with db.engine.connect() as conn:
                    conn.execute(text("ALTER TABLE orders ADD COLUMN verification_code VARCHAR(32) DEFAULT ''"))
                    conn.execute(text("CREATE INDEX ix_orders_verification_code ON orders (verification_code)"))
                    conn.commit()
                print("Migration done: verification_code added.")
    except Exception as e:
        print(f"Auto migration failed: {e}")
