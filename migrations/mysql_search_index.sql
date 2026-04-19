CREATE TABLE IF NOT EXISTS texts_sentences (
    id BIGINT AUTO_INCREMENT PRIMARY KEY,
    text_id INT NOT NULL,
    sent_no INT NOT NULL,
    lang VARCHAR(16) NOT NULL DEFAULT 'default',
    content LONGTEXT NOT NULL,
    content_norm LONGTEXT NOT NULL,
    year INT NULL,
    geo VARCHAR(255) NULL,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    UNIQUE KEY uq_text_sent (text_id, sent_no, lang),
    INDEX idx_text_id (text_id),
    INDEX idx_year_geo (year, geo),
    FULLTEXT INDEX ft_content_norm (content_norm)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;

-- For existing databases: add the composite index if it does not already exist.
-- MySQL does not support IF NOT EXISTS for indexes, so this will error
-- harmlessly if the index is already present.
-- Run this manually if upgrading an existing installation:
--
--   ALTER TABLE texts_sentences ADD INDEX idx_year_geo (year, geo);
