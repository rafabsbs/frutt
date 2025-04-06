from app import db
from app import create_app

app = create_app()

def init_db():
    with app.app_context():
        db.create_all()
        print("✅ Database tables created successfully!")

if __name__ == '__main__':
    init_db()