from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime, date
from dateutil.relativedelta import relativedelta

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password = db.Column(db.String(200), nullable=False)
    role = db.Column(db.String(20), default='operador')

class Alumno(db.Model):
    __tablename__ = 'alumnos'
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    dni = db.Column(db.String(20), unique=True, nullable=False)
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(100))
    tipo = db.Column(db.String(20), default='normal')  # normal, personalizado
    fecha_inscripcion = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)
    
    # Datos de cuota
    valor_cuota = db.Column(db.Float, default=15000)  # Cuota mensual normal
    fecha_vencimiento = db.Column(db.Date)  # Próximo vencimiento
    estado_cuota = db.Column(db.String(20), default='al_dia')  # al_dia, deuda, vencido
    
    # Relaciones
    pagos = db.relationship('Pago', backref='alumno', lazy=True)

class Pago(db.Model):
    __tablename__ = 'pagos'
    
    id = db.Column(db.Integer, primary_key=True)
    alumno_id = db.Column(db.Integer, db.ForeignKey('alumnos.id'), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    fecha_pago = db.Column(db.DateTime, default=datetime.utcnow)
    periodo_mes = db.Column(db.Integer)  # 1-12
    periodo_anio = db.Column(db.Integer)
    metodo_pago = db.Column(db.String(20), default='efectivo')
    comprobante = db.Column(db.String(100))

class Bebida(db.Model):
    __tablename__ = 'bebidas'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(50), nullable=False)
    categoria = db.Column(db.String(20), default='agua')  # agua, gatorade, isotonico, proteina
    precio = db.Column(db.Float, nullable=False)
    stock = db.Column(db.Integer, default=0)
    tamanio = db.Column(db.String(20))  # 500ml, 1L, etc.

class VentaBebida(db.Model):
    __tablename__ = 'ventas_bebidas'
    
    id = db.Column(db.Integer, primary_key=True)
    bebida_id = db.Column(db.Integer, db.ForeignKey('bebidas.id'), nullable=False)
    bebida_nombre = db.Column(db.String(50))
    cantidad = db.Column(db.Integer, default=1)
    monto = db.Column(db.Float, nullable=False)
    fecha = db.Column(db.DateTime, default=datetime.utcnow)
    alumno_id = db.Column(db.Integer, db.ForeignKey('alumnos.id'), nullable=True)
    usuario_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    
    bebida = db.relationship('Bebida')
    alumno = db.relationship('Alumno')
    usuario = db.relationship('User')

class Personalizado(db.Model):
    __tablename__ = 'personalizados'
    
    id = db.Column(db.Integer, primary_key=True)
    nombre = db.Column(db.String(100), nullable=False)
    dni = db.Column(db.String(20), unique=True, nullable=False)
    telefono = db.Column(db.String(20))
    email = db.Column(db.String(100))
    entrenador = db.Column(db.String(100))  # Nombre del entrenador personal
    valor_mensual = db.Column(db.Float, default=30000)  # Cuota personalizada
    fecha_inscripcion = db.Column(db.DateTime, default=datetime.utcnow)
    activo = db.Column(db.Boolean, default=True)
    fecha_vencimiento = db.Column(db.Date)
    
    pagos = db.relationship('PagoPersonalizado', backref='personalizado', lazy=True)

class PagoPersonalizado(db.Model):
    __tablename__ = 'pagos_personalizados'
    
    id = db.Column(db.Integer, primary_key=True)
    personalizado_id = db.Column(db.Integer, db.ForeignKey('personalizados.id'), nullable=False)
    monto = db.Column(db.Float, nullable=False)
    fecha_pago = db.Column(db.DateTime, default=datetime.utcnow)
    periodo_mes = db.Column(db.Integer)
    periodo_anio = db.Column(db.Integer)
    metodo_pago = db.Column(db.String(20), default='efectivo')
    comprobante = db.Column(db.String(100))

class Configuracion(db.Model):
    __tablename__ = 'configuracion'
    
    id = db.Column(db.Integer, primary_key=True)
    clave = db.Column(db.String(50), unique=True, nullable=False)
    valor = db.Column(db.Text)
    
    @staticmethod
    def get(clave, default=''):
        config = Configuracion.query.filter_by(clave=clave).first()
        return config.valor if config else default
    
    @staticmethod
    def set(clave, valor):
        config = Configuracion.query.filter_by(clave=clave).first()
        if config:
            config.valor = valor
        else:
            config = Configuracion(clave=clave, valor=valor)
            db.session.add(config)
        db.session.commit()