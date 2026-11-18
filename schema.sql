-- قاعدة بيانات نظام الوثائق والمحفوظات (MySQL)
CREATE DATABASE IF NOT EXISTS archive_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE archive_db;

CREATE TABLE IF NOT EXISTS users (
  id INT AUTO_INCREMENT PRIMARY KEY,
  username VARCHAR(50) NOT NULL UNIQUE,
  full_name VARCHAR(120) NOT NULL,
  password_hash VARCHAR(255) NOT NULL,
  role ENUM('admin','clerk','viewer') NOT NULL DEFAULT 'viewer',
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS categories (
  id INT AUTO_INCREMENT PRIMARY KEY,
  name VARCHAR(80) NOT NULL UNIQUE
) ENGINE=InnoDB;

CREATE TABLE IF NOT EXISTS documents (
  id INT AUTO_INCREMENT PRIMARY KEY,
  title VARCHAR(255) NOT NULL,
  doc_number VARCHAR(60),
  doc_date VARCHAR(20),              -- النص الأصلي للتاريخ كما في الوثيقة (أرشيف فقط)
  doc_date_h CHAR(10) NULL,          -- التاريخ الهجري المعتمد بصيغة YYYY-MM-DD (نص لأن DATE يرفض 30 صفر مثلاً)
  doc_date_source VARCHAR(10) NULL,  -- مصدر تاريخ الوثيقة: auto (مستخرج عند الرفع) / manual (المستخدم) / backfill (سكربت)
  category_id INT NULL,
  source VARCHAR(150),               -- الجهة المصدرة
  description TEXT,
  filename VARCHAR(255) NOT NULL,    -- الاسم المخزّن على القرص
  original_name VARCHAR(255) NOT NULL,
  ocr_text LONGTEXT,                 -- النص المستخرج بالـ OCR
  search_text LONGTEXT,              -- نص مُطبَّع للبحث الذكي
  summary TEXT,                      -- الملخص التلقائي
  uploaded_by INT NULL,
  created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME NULL,          -- آخر تعديل فعلي (UTC)، NULL = لم تُعدَّل منذ رفعها
  updated_by INT NULL,               -- من قام بآخر تعديل
  FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
  FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
  CONSTRAINT fk_documents_updated_by FOREIGN KEY (updated_by) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_doc_number (doc_number),
  INDEX idx_category (category_id),
  INDEX idx_doc_date_h (doc_date_h),
  INDEX idx_created_at (created_at)  -- البحث بتاريخ الرفع
) ENGINE=InnoDB;

-- سجل التعديلات: صف لكل تعديل فعلي على وثيقة
CREATE TABLE IF NOT EXISTS document_edits (
  id INT AUTO_INCREMENT PRIMARY KEY,
  document_id INT NOT NULL,
  user_id INT NULL,
  edited_at DATETIME NOT NULL,       -- UTC
  changes TEXT NOT NULL,             -- JSON: الحقول المتغيرة (القديم والجديد للحقول القصيرة)
  FOREIGN KEY (document_id) REFERENCES documents(id) ON DELETE CASCADE,
  FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_edits_doc (document_id, edited_at)
) ENGINE=InnoDB;

INSERT IGNORE INTO categories (name) VALUES
 ('تعميم'),('خطاب'),('قرار'),('محضر'),('نموذج'),('لائحة / تعليمات'),('أخرى');
