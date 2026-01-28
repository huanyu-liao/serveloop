from saas import create_app
from saas.infra.models import db
from sqlalchemy import text

app = create_app()

with app.app_context():
    try:
        with db.engine.connect() as conn:
            # Check if column exists first to avoid error? 
            # Or just try to add it. Let's try to add it.
            print("Attempting to add verification_code column...")
            conn.execute(text("ALTER TABLE orders ADD COLUMN verification_code VARCHAR(32) DEFAULT ''"))
            print("Column added. Attempting to add index...")
            conn.execute(text("CREATE INDEX ix_orders_verification_code ON orders (verification_code)"))
            conn.commit()
            print("Successfully added verification_code column and index.")
    except Exception as e:
        print(f"Error: {e}")
