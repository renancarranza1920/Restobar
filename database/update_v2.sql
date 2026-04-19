ALTER TABLE orden_items
    MODIFY estado ENUM('pendiente', 'listo', 'entregado', 'cancelado') DEFAULT 'pendiente';

CREATE TABLE IF NOT EXISTS orden_divisiones (
    id INT AUTO_INCREMENT PRIMARY KEY,
    orden_id INT NOT NULL,
    numero_persona INT NOT NULL,
    etiqueta VARCHAR(50) NULL,
    total DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    pagada BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (orden_id) REFERENCES ordenes(id)
);

CREATE TABLE IF NOT EXISTS orden_division_items (
    id INT AUTO_INCREMENT PRIMARY KEY,
    division_id INT NOT NULL,
    orden_item_id INT NOT NULL,
    cantidad INT NOT NULL DEFAULT 1,
    subtotal DECIMAL(10,2) NOT NULL DEFAULT 0.00,
    FOREIGN KEY (division_id) REFERENCES orden_divisiones(id),
    FOREIGN KEY (orden_item_id) REFERENCES orden_items(id)
);

CREATE INDEX idx_orden_divisiones_orden ON orden_divisiones(orden_id);
CREATE INDEX idx_orden_division_items_division ON orden_division_items(division_id);
CREATE INDEX idx_orden_division_items_item ON orden_division_items(orden_item_id);
