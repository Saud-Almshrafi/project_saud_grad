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
  doc_date VARCHAR(20),              -- نص لدعم التاريخ الهجري والميلادي
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
  FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE SET NULL,
  FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL,
  INDEX idx_doc_number (doc_number),
  INDEX idx_category (category_id)
) ENGINE=InnoDB;

INSERT IGNORE INTO categories (name) VALUES
 ('تعميم'),('خطاب'),('قرار'),('محضر'),('نموذج'),('لائحة / تعليمات'),('أخرى');
