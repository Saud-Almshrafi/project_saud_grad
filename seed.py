"""ينشئ حساب المدير الأول. شغّله مرة واحدة بعد استيراد schema.sql:

    python seed.py                 # admin / admin123 (غيّرها بعد أول دخول)
    python seed.py myuser MyPass1  # حساب بمواصفاتك
"""
import sys

from werkzeug.security import generate_password_hash

import app as appmod
import db

username = sys.argv[1] if len(sys.argv) > 1 else "admin"
password = sys.argv[2] if len(sys.argv) > 2 else "admin123"

with appmod.app.app_context():
    if db.ENGINE == "sqlite":
        db.init_sqlite()
    if db.query("SELECT id FROM users WHERE username=%s", (username,), one=True):
        print("المستخدم موجود مسبقاً:", username)
    else:
        db.execute("INSERT INTO users (username, full_name, password_hash, role) VALUES (%s,%s,%s,'admin')",
                   (username, "مدير النظام", generate_password_hash(password)))
        print(f"تم إنشاء المدير: {username} / {password}")
