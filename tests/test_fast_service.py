"""Counter transactions, recipes, shift isolation and additive upgrade safety."""
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import hashlib
import sqlite3
import unittest
from uuid import uuid4
from unittest.mock import patch
from sqlalchemy import inspect, text

import test_restaurant as restaurant_tests
from app import create_app
from app.config import Config
from app.extensions import db
from app.models import (Categoria, Producto, Orden, OrdenItem, OrdenMesa, Pago, MovimientoInventario,
    Usuario, Rol, SesionCaja, DocumentoFiscal, FiscalEnvio, FiscalIntento)
from app.fast_models import (RecetaIngrediente, ConsumoVenta, VentaRapida, CierreTurno, UnidadInsumo)
from app.services import get_pending_kitchen_items, session_cash_expected
from app.routes import ticket_payment_context


class FastServiceTests(unittest.TestCase):
    admin_name = restaurant_tests.RestaurantRegressionTests.admin_name
    admin_password = restaurant_tests.RestaurantRegressionTests.admin_password
    setUp = restaurant_tests.RestaurantRegressionTests.setUp
    dispose_database = restaurant_tests.RestaurantRegressionTests.dispose_database
    login = restaurant_tests.RestaurantRegressionTests.login
    post = restaurant_tests.RestaurantRegressionTests.post

    def fixture(self):
        self.login()
        self.client.get('/venta')
        with self.client.session_transaction() as s:
            self.csrf = s['counter_csrf']
        self.post('/caja/abrir', {'opening_amount': '20.00'})
        with self.app.app_context():
            kitchen = Categoria(nombre='Comida', envia_a_cocina=True)
            drinks = Categoria(nombre='Bebidas', envia_a_cocina=False)
            warehouse = Categoria(nombre='Insumos', envia_a_cocina=False)
            burger = Producto(nombre='Hamburguesa', categoria=kitchen, precio_venta=Decimal('5'),
                stock_actual=0, maneja_stock=False, es_inventario=False)
            soda = Producto(nombre='Soda', categoria=drinks, precio_venta=Decimal('2'),
                stock_actual=5, maneja_stock=True, precio_costo=Decimal('.50'))
            meat = Producto(nombre='Carne', categoria=warehouse, es_inventario=True,
                precio_venta=0, stock_actual=1000, maneja_stock=True, disponible=False)
            db.session.add_all([burger, soda, meat]); db.session.flush()
            db.session.add_all([UnidadInsumo(producto_id=meat.id, unidad='g'),
                RecetaIngrediente(producto_id=burger.id, insumo_id=meat.id, cantidad=125),
                MovimientoInventario(producto_id=meat.id, tipo='compra', cantidad_unidades=1000,
                    precio_unitario=Decimal('4.00'), usuario_id=Usuario.query.filter_by(nickname=self.admin_name).one().id)])
            db.session.commit()
            self.burger, self.soda, self.meat = burger.id, soda.id, meat.id
            self.shift = SesionCaja.query.filter_by(estado='abierta').one().id
        return self.payload()

    def payload(self, **overrides):
        result = dict(key=str(uuid4()), shift_id=self.shift, channel='llevar', method='efectivo',
            received='20.00', customer='Ana', lines=[
                {'id':self.burger, 'quantity':2, 'price':'5.00', 'notes':'Sin cebolla'},
                {'id':self.soda, 'quantity':1, 'price':'2.00'}])
        result.update(overrides)
        return result

    def checkout(self, payload, client=None, csrf=None):
        return (client or self.client).post('/venta/cobrar', json=payload,
            headers={'X-CSRF-Token': csrf or self.csrf})

    def test_mixed_sale_pays_before_kitchen_and_consumes_recipe_once(self):
        payload = self.fixture()
        response = self.checkout(payload)
        self.assertEqual(response.status_code, 201, response.get_json())
        result = response.get_json()
        self.assertEqual((result['total'],result['change'],result['kitchen']), ('12.00','8.00',True))
        with self.app.app_context():
            order = db.session.get(Orden,result['order_id'])
            self.assertEqual(order.estado,'pagada')
            self.assertEqual(order.total_pagado,Decimal('12'))
            self.assertEqual(db.session.get(Producto,self.meat).stock_actual,750)
            self.assertEqual(db.session.get(Producto,self.soda).stock_actual,4)
            item = OrdenItem.query.filter_by(orden_id=order.id,producto_id=self.burger).one()
            self.assertTrue(item.pagado)
            self.assertEqual(item.estado,'pendiente')
            self.assertEqual(item.costo_unitario,Decimal('.50'))
            self.assertEqual(item.notas,'Sin cebolla')
            self.assertEqual(len(get_pending_kitchen_items()),1)
            self.assertEqual(session_cash_expected(db.session.get(SesionCaja,self.shift)),Decimal('32'))
            self.assertEqual(ConsumoVenta.query.count(),2)
            receipt = ticket_payment_context(order)
            self.assertEqual((receipt['received'],receipt['change']),(Decimal('20'),Decimal('8')))
            kitchen_id = item.id
        replay = self.checkout(payload)
        self.assertEqual(replay.status_code,200)
        self.assertTrue(replay.get_json()['replay'])
        self.post(f'/items/{kitchen_id}/preparar',{})
        self.assertEqual(self.client.get(f"/ordenes/{result['order_id']}").status_code,200)
        with self.app.app_context():
            self.assertEqual(Orden.query.one().estado,'pagada')
            self.assertEqual(db.session.get(OrdenItem,kitchen_id).estado,'listo')
            self.assertEqual(db.session.get(Producto,self.meat).stock_actual,750)
            self.assertEqual(Pago.query.count(),1)
            self.assertEqual(VentaRapida.query.count(),1)
            self.assertEqual(get_pending_kitchen_items(),[])
        self.post(f"/venta/{result['order_id']}/entregar",{'csrf':self.csrf})
        with self.app.app_context():
            self.assertTrue(Orden.query.one().todos_entregados)

    def test_insufficient_stock_is_atomic_including_shared_ingredient(self):
        self.fixture()
        payload = self.payload(lines=[{'id':self.burger,'quantity':5,'price':'5'},
            {'id':self.burger,'quantity':5,'price':'5'}],received='100')
        response = self.checkout(payload)
        self.assertEqual(response.status_code,400)
        self.assertIn('Carne',response.get_json()['error'])
        with self.app.app_context():
            self.assertEqual(Orden.query.count(),0)
            self.assertEqual(Pago.query.count(),0)
            self.assertEqual(ConsumoVenta.query.count(),0)
            self.assertEqual(db.session.get(Producto,self.meat).stock_actual,1000)

    def test_failure_after_partial_consumption_rolls_back_everything(self):
        payload = self.fixture()
        from app.fast_inventory import consume_item
        calls = []
        def fail(item):
            calls.append(item.producto_id)
            consume_item(item)
            if len(calls) == 2:
                raise ValueError('Falla de prueba después del consumo')
        with patch('app.fast_service.consume_item',side_effect=fail):
            self.assertEqual(self.checkout(payload).status_code,400)
        with self.app.app_context():
            self.assertEqual(Orden.query.count(),0)
            self.assertEqual(MovimientoInventario.query.count(),1)
            self.assertEqual(db.session.get(Producto,self.meat).stock_actual,1000)
            self.assertEqual(db.session.get(Producto,self.soda).stock_actual,5)

    def test_price_shift_invalid_money_and_csrf_rejected_without_writes(self):
        self.fixture()
        cases = [self.payload(received='NaN'),self.payload(received='-5'),self.payload(received='1'),
            self.payload(received='20.001'),self.payload(shift_id=self.shift+1),
            self.payload(method='transferencia'),self.payload(lines=[{'id':self.soda,'quantity':1,'price':'1'}]),
            self.payload(lines=[{'id':self.soda,'quantity':-1,'price':'2'}]),
            self.payload(lines=[{'id':self.meat,'quantity':1,'price':'0'}])]
        for payload in cases:
            with self.subTest(payload=payload):
                self.assertEqual(self.checkout(payload).status_code,400)
        self.assertEqual(self.checkout(self.payload(),csrf='incorrect').status_code,400)
        with self.app.app_context():
            self.assertEqual(Orden.query.count(),0)
            self.assertEqual(db.session.get(Producto,self.soda).stock_actual,5)

    def test_counter_restart_preserves_all_existing_rows(self):
        self.fixture()
        self.assertEqual(self.checkout(self.payload()).status_code,201)
        def table_rows():
            return {name:sorted(repr(tuple(row)) for row in db.session.execute(text('SELECT * FROM '+name)))
                for name in inspect(db.engine).get_table_names()}
        with self.app.app_context():
            before=table_rows()
            uri=self.app.config['SQLALCHEMY_DATABASE_URI']
            product_dir=self.app.config['PRODUCT_UPLOAD_DIR']
            branding_dir=self.app.config['BRANDING_UPLOAD_DIR']
            db.session.remove();db.engine.dispose()
        with patch.multiple(Config,SQLALCHEMY_DATABASE_URI=uri,
            DEFAULT_ADMIN_NICKNAME=self.admin_name,DEFAULT_ADMIN_PASSWORD=self.admin_password,
            PRODUCT_UPLOAD_DIR=product_dir,BRANDING_UPLOAD_DIR=branding_dir):
            restarted=create_app()
        with restarted.app_context():
            after=table_rows()
            db.session.remove();db.engine.dispose()
        self.assertEqual(before,after)

    def test_existing_unpaid_order_reserves_recipe_ingredients(self):
        self.fixture()
        with self.app.app_context():
            order = Orden(mesa_id=999,sesion_caja_id=self.shift,usuario_id=Usuario.query.first().id)
            db.session.add(order);db.session.flush()
            db.session.add(OrdenMesa(orden=order,mesa_id=order.mesa_id))
            db.session.add(OrdenItem(orden=order,producto_id=self.burger,cantidad=6,
                precio_unitario=5,costo_unitario=0,estado='pendiente',pagado=False))
            db.session.commit()
        response = self.checkout(self.payload(lines=[{'id':self.burger,'quantity':3,'price':'5'}]))
        self.assertEqual(response.status_code,400)
        self.assertIn('250',response.get_json()['error'])
        stocks = self.client.get('/venta/estado').get_json()['stocks']
        self.assertEqual(stocks[str(self.burger)],2)

    def test_recipe_edit_preserves_consumption_snapshots(self):
        payload=self.fixture();self.assertEqual(self.checkout(payload).status_code,201)
        self.post(f'/recetas/{self.burger}',{'csrf':self.csrf,'ingredient_id':str(self.meat),'quantity':'250'})
        with self.app.app_context():
            self.assertEqual(RecetaIngrediente.query.one().cantidad,250)
            snapshot = ConsumoVenta.query.filter_by(insumo_id=self.meat).one()
            self.assertEqual((snapshot.cantidad,snapshot.unidad,snapshot.costo),(250,'g',Decimal('1.00')))
            self.assertEqual(db.session.get(Producto,self.meat).stock_actual,750)

    def test_shift_closes_with_paid_kitchen_items_and_saves_variance(self):
        self.fixture();self.assertEqual(self.checkout(self.payload()).status_code,201)
        self.post('/caja/cerrar',{'closing_amount':'-1'})
        self.post('/caja/cerrar',{'closing_amount':'31'})
        with self.app.app_context():
            self.assertEqual(CierreTurno.query.count(),0)
            self.assertEqual(SesionCaja.query.one().estado,'abierta')
        self.post('/caja/cerrar',{'closing_amount':'31','notes':'Falta un dólar de cambio'})
        with self.app.app_context():
            cut=CierreTurno.query.one()
            self.assertEqual((cut.esperado,cut.contado,cut.diferencia,cut.ventas),(Decimal('32'),Decimal('31'),Decimal('-1'),Decimal('12')))
            self.assertEqual(SesionCaja.query.one().estado,'cerrada')
            self.assertEqual(len(get_pending_kitchen_items()),1)
        self.post('/caja/abrir',{'opening_amount':'10'})
        self.assertEqual(self.checkout(self.payload()).status_code,400)  # stale shift
        self.assertEqual(self.client.get('/caja').status_code,200)

    def test_unpaid_orders_prevent_shift_close(self):
        self.fixture()
        with self.app.app_context():
            db.session.add(Orden(mesa_id=999,sesion_caja_id=self.shift,usuario_id=Usuario.query.first().id))
            db.session.commit()
        self.post('/caja/cerrar',{'closing_amount':'20'})
        with self.app.app_context():self.assertEqual(SesionCaja.query.one().estado,'abierta')

    def test_card_sale_and_closed_shift_replay(self):
        self.fixture()
        payload=self.payload(method='tarjeta',received='')
        result=self.checkout(payload)
        self.assertEqual(result.status_code,201,result.get_json())
        self.assertEqual(result.get_json()['change'],'0.00')
        self.post('/caja/cerrar',{'closing_amount':'20'})
        self.assertEqual(self.checkout(payload).status_code,200)
        self.assertEqual(self.checkout(self.payload()).status_code,400)
        with self.app.app_context():
            self.assertEqual(CierreTurno.query.one().tarjetas,Decimal('12'))
            self.assertEqual(Pago.query.count(),1)

    def test_ingredient_purchase_and_merma_keep_units_and_exact_cost(self):
        self.fixture()
        self.post('/insumos',{'csrf':self.csrf,'name':'Jarabe','unit':'ml','quantity':'1000','cost':'3.20'})
        with self.app.app_context():
            jar = Producto.query.filter_by(nombre='Jarabe').one(); jar_id=jar.id
            self.assertEqual(db.session.get(UnidadInsumo,jar.id).unidad,'ml')
            self.assertEqual(jar.stock_actual,1000)
        self.post('/insumos',{'csrf':self.csrf,'ingredient_id':jar_id,'kind':'merma','quantity':'50','notes':'Derrame'})
        self.post('/insumos',{'csrf':self.csrf,'ingredient_id':jar_id,'kind':'merma','quantity':'5000','notes':'Derrame'})
        with self.app.app_context():self.assertEqual(db.session.get(Producto,jar_id).stock_actual,950)

    def test_concurrent_retry_creates_one_payment(self):
        payload=self.fixture()
        clients=[self.app.test_client(),self.app.test_client()]
        tokens=[]
        for client in clients:
            self.login(client=client);client.get('/venta')
            with client.session_transaction() as s:tokens.append(s['counter_csrf'])
        with ThreadPoolExecutor(max_workers=2) as executor:
            futures=[executor.submit(self.checkout,payload,client,token) for client,token in zip(clients,tokens)]
            responses=[f.result() for f in futures]
        self.assertEqual(sorted(r.status_code for r in responses),[200,201])
        with self.app.app_context():
            self.assertEqual(Pago.query.count(),1)
            self.assertEqual(db.session.get(Producto,self.meat).stock_actual,750)

    def test_replenish_sale_units_directly_without_warehouse_transfer(self):
        self.fixture()
        self.post('/insumos',{'csrf':self.csrf,'ingredient_id':self.soda,'quantity':'6','cost':'6.00'})
        with self.app.app_context():
            self.assertEqual(db.session.get(Producto,self.soda).stock_actual,11)
            self.assertFalse(db.session.get(Producto,self.soda).es_inventario)
        result=self.checkout(self.payload(lines=[{'id':self.soda,'quantity':1,'price':'2'}]))
        self.assertEqual(result.status_code,201)
        with self.app.app_context():
            self.assertEqual(db.session.get(Producto,self.soda).stock_actual,10)
            self.assertEqual(ConsumoVenta.query.one().costo,Decimal('1.00'))

    def test_concurrent_sales_cannot_oversell(self):
        self.fixture()
        with self.app.app_context():
            db.session.get(Producto,self.soda).stock_actual=1;db.session.commit()
        clients=[self.app.test_client(),self.app.test_client()];tokens=[]
        for client in clients:
            self.login(client=client);client.get('/venta')
            with client.session_transaction() as s:tokens.append(s['counter_csrf'])
        payloads=[self.payload(lines=[{'id':self.soda,'quantity':1,'price':'2'}]) for _ in clients]
        with ThreadPoolExecutor(max_workers=2) as executor:
            responses=[f.result() for f in [executor.submit(self.checkout,payload,client,token)
                for payload,client,token in zip(payloads,clients,tokens)]]
        self.assertEqual(sorted(r.status_code for r in responses),[201,400])
        with self.app.app_context():
            self.assertEqual(Pago.query.count(),1)
            self.assertEqual(db.session.get(Producto,self.soda).stock_actual,0)

    def test_restricted_staff_cannot_checkout_or_edit_recipes(self):
        self.fixture()
        with self.app.app_context():
            role=Rol(codigo='readonly',nombre='Lectura');role.permisos={'inventario.view'}
            user=Usuario(nickname='viewer',nombre='View',apellido='Only',rol=role.codigo)
            user.set_password(self.admin_password);db.session.add_all([role,user]);db.session.commit()
        self.client.post('/logout')
        self.login(nickname='viewer')
        self.assertEqual(self.client.get('/recetas').status_code,200)
        self.assertEqual(self.client.get('/venta').status_code,302)
        self.assertEqual(self.checkout(self.payload()).status_code,302)
        self.post('/insumos',{'csrf':self.csrf,'name':'No','unit':'g','quantity':'1','cost':'0'})
        with self.app.app_context():self.assertIsNone(Producto.query.filter_by(nombre='No').first())

    def test_additive_startup_preserves_legacy_fiscal_evidence(self):
        self.fixture()
        with self.app.app_context():
            actor=Usuario.query.first().id
            order=Orden(mesa_id=999,sesion_caja_id=self.shift,usuario_id=actor,total=2,estado='pagada')
            db.session.add(order);db.session.flush()
            db.session.add(OrdenMesa(orden=order,mesa_id=order.mesa_id))
            draft=DocumentoFiscal(orden_id=order.id,usuario_id=actor,codigo_generacion=str(uuid4()),
                numero_control='DTE-01-M001P001-000000000000001',nombre_receptor='Histórico',
                total=2,iva=Decimal('.23'),documento_json='{"version":1}',
                documento_sha256=hashlib.sha256(b'{"version":1}').hexdigest(),snapshot_json='{"original":true}')
            db.session.add(draft);db.session.flush()
            evidence=FiscalEnvio(documento_id=draft.id,estado='ACEPTADO',firma='historical-signature',
                sello='historical-seal',respuesta_json='{"kept":true}',transmisiones=1)
            db.session.add(evidence);db.session.flush()
            db.session.add(FiscalIntento(envio_id=evidence.id,etapa='consulta',resultado='ACEPTADO',respuesta_json='{"kept":true}'))
            db.session.commit()
            uri=self.app.config['SQLALCHEMY_DATABASE_URI'];db.session.remove();db.engine.dispose()
        path=uri.removeprefix('sqlite:///')
        conn=sqlite3.connect(path)
        tables=['documentos_fiscales','fiscales_envios','fiscales_intentos','ordenes','orden_mesas','pagos','productos','roles','usuarios']
        before={t:conn.execute('SELECT * FROM '+t).fetchall() for t in tables}
        for t in ['consumos_venta','ventas_rapidas','cierres_turno','recetas_ingredientes','unidades_insumo','guardias_operacion']:
            conn.execute('DROP TABLE '+t)
        conn.commit();conn.close()
        with patch.multiple(Config,SQLALCHEMY_DATABASE_URI=uri,
            DEFAULT_ADMIN_NICKNAME=self.admin_name, DEFAULT_ADMIN_PASSWORD=self.admin_password,
            PRODUCT_UPLOAD_DIR=self.app.config['PRODUCT_UPLOAD_DIR'],BRANDING_UPLOAD_DIR=self.app.config['BRANDING_UPLOAD_DIR']):
            upgraded=create_app()
        with upgraded.app_context():db.session.remove();db.engine.dispose()
        conn=sqlite3.connect(path)
        after={t:conn.execute('SELECT * FROM '+t).fetchall() for t in tables};conn.close()
        self.assertEqual(before,after)
        self.assertFalse(upgraded.config['DTE_TRANSMISSION_ENABLED'])


if __name__ == '__main__':unittest.main()
