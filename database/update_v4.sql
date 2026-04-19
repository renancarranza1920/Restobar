ALTER TABLE mesas
    ADD COLUMN limpieza_estado ENUM('limpia', 'sucia') NOT NULL DEFAULT 'limpia' AFTER estado;
