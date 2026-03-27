import os
import pandas as pd
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from models import db, User, Alumno, Pago, Bebida, VentaBebida, Personalizado, PagoPersonalizado, Configuracion
from datetime import datetime, date, timedelta
from sqlalchemy import func, extract
from io import BytesIO
from dateutil.relativedelta import relativedelta

app = Flask(__name__)

# Configuración
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'boxfit_lite_key_2024')

db_url = os.environ.get('DATABASE_URL')
if db_url and db_url.startswith("postgres://"):
    db_url = db_url.replace("postgres://", "postgresql://", 1)

app.config['SQLALCHEMY_DATABASE_URI'] = db_url or 'sqlite:///gym_lite.db'
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db.init_app(app)

login_manager = LoginManager(app)
login_manager.login_view = 'login'
login_manager.login_message = 'Por favor iniciá sesión'

@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

# ====================== HELPERS ======================

def calcular_vencimiento(fecha_inicio):
    """Calcula próximo vencimiento (30 días)"""
    return fecha_inicio + relativedelta(days=30)

def get_ventas_bebidas_semanales():
    hoy = date.today()
    ventas = []
    for i in range(6, -1, -1):
        dia = hoy - timedelta(days=i)
        total = db.session.query(func.sum(VentaBebida.monto)).filter(
            func.date(VentaBebida.fecha) == dia
        ).scalar() or 0
        ventas.append({'dia': dia.strftime('%a'), 'total': total})
    return ventas

def get_top_bebidas():
    resultados = db.session.query(
        VentaBebida.bebida_nombre,
        func.sum(VentaBebida.cantidad).label('cantidad')
    ).group_by(VentaBebida.bebida_nombre).order_by(func.sum(VentaBebida.cantidad).desc()).limit(5).all()
    return [{'nombre': r[0], 'cantidad': r[1]} for r in resultados]

# ====================== CONTEXTO GLOBAL ======================

@app.context_processor
def inject_config():
    return {
        'config': Configuracion
    }

# ====================== RUTAS PRINCIPALES ======================

@app.route('/')
def index():
    if not current_user.is_authenticated:
        return redirect(url_for('login'))
    
    # Estadísticas
    total_alumnos = Alumno.query.filter_by(activo=True).count()
    total_personalizados = Personalizado.query.filter_by(activo=True).count()
    alumnos_deuda = Alumno.query.filter_by(estado_cuota='deuda').count()
    personalizados_deuda = Personalizado.query.filter_by(activo=True).count()  # Simplificado
    
    # Ventas de bebidas hoy
    ventas_hoy = VentaBebida.query.filter(func.date(VentaBebida.fecha) == date.today()).count()
    monto_ventas_hoy = db.session.query(func.sum(VentaBebida.monto)).filter(func.date(VentaBebida.fecha) == date.today()).scalar() or 0
    
    # Próximos vencimientos
    hoy = date.today()
    vencimientos_proximos = Alumno.query.filter(
        Alumno.fecha_vencimiento <= hoy + timedelta(days=7),
        Alumno.fecha_vencimiento > hoy,
        Alumno.activo == True
    ).count()
    
    # Últimas ventas
    ultimas_ventas = VentaBebida.query.order_by(VentaBebida.fecha.desc()).limit(5).all()
    
    # Bebidas con stock bajo
    stock_bajo = Bebida.query.filter(Bebida.stock <= 10).all()
    
    ventas_semanales = get_ventas_bebidas_semanales()
    top_bebidas = get_top_bebidas()
    
    stats = {
        'total_alumnos': total_alumnos,
        'total_personalizados': total_personalizados,
        'alumnos_deuda': alumnos_deuda,
        'personalizados_deuda': personalizados_deuda,
        'ventas_hoy': ventas_hoy,
        'monto_ventas_hoy': monto_ventas_hoy,
        'vencimientos_proximos': vencimientos_proximos,
        'ultimas_ventas': ultimas_ventas,
        'stock_bajo': stock_bajo,
    }
    
    bebidas = Bebida.query.filter(Bebida.stock > 0).order_by(Bebida.categoria, Bebida.nombre).all()
    alumnos = Alumno.query.filter_by(activo=True).order_by(Alumno.nombre).all()
    personalizados = Personalizado.query.filter_by(activo=True).order_by(Personalizado.nombre).all()
    
    return render_template('dashboard.html', 
                          stats=stats,
                          bebidas=bebidas,
                          alumnos=alumnos,
                          personalizados=personalizados,
                          ventas_semanales=ventas_semanales,
                          top_bebidas=top_bebidas,
                          now=datetime.now())

# ====================== AUTENTICACIÓN ======================

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        
        if user and check_password_hash(user.password, password):
            login_user(user)
            flash(f'Bienvenido {user.username}', 'success')
            return redirect(url_for('index'))
        else:
            flash('Usuario o contraseña incorrectos', 'error')
    
    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    flash('Sesión cerrada', 'info')
    return redirect(url_for('login'))

# ====================== ALUMNOS ======================

@app.route('/alumnos')
@login_required
def alumnos():
    alumnos_lista = Alumno.query.order_by(Alumno.fecha_inscripcion.desc()).all()
    return render_template('alumnos.html', alumnos=alumnos_lista)

@app.route('/alumnos/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_alumno():
    if request.method == 'POST':
        try:
            valor_cuota = float(request.form.get('valor_cuota', Configuracion.get('cuota_normal', 15000)))
            nuevo = Alumno(
                nombre=request.form['nombre'],
                dni=request.form['dni'],
                telefono=request.form.get('telefono', ''),
                email=request.form.get('email', ''),
                tipo='normal',
                valor_cuota=valor_cuota,
                activo=True,
                estado_cuota='al_dia'
            )
            nuevo.fecha_vencimiento = calcular_vencimiento(datetime.utcnow())
            db.session.add(nuevo)
            db.session.commit()
            flash(f'Alumno {nuevo.nombre} agregado', 'success')
            return redirect(url_for('alumnos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('nuevo_alumno.html')

@app.route('/alumnos/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_alumno(id):
    alumno = Alumno.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            alumno.nombre = request.form['nombre']
            alumno.dni = request.form['dni']
            alumno.telefono = request.form.get('telefono', '')
            alumno.email = request.form.get('email', '')
            alumno.valor_cuota = float(request.form.get('valor_cuota', alumno.valor_cuota))
            alumno.activo = 'activo' in request.form
            db.session.commit()
            flash('Alumno actualizado', 'success')
            return redirect(url_for('alumnos'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('editar_alumno.html', alumno=alumno)

@app.route('/alumnos/eliminar/<int:id>')
@login_required
def eliminar_alumno(id):
    alumno = Alumno.query.get_or_404(id)
    nombre = alumno.nombre
    db.session.delete(alumno)
    db.session.commit()
    flash(f'Alumno {nombre} eliminado', 'success')
    return redirect(url_for('alumnos'))

# ====================== PAGOS DE ALUMNOS ======================

@app.route('/alumnos/<int:id>/pagar', methods=['GET', 'POST'])
@login_required
def pagar_alumno(id):
    alumno = Alumno.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            monto = float(request.form.get('monto', alumno.valor_cuota))
            metodo = request.form.get('metodo_pago', 'efectivo')
            comprobante = request.form.get('comprobante', '')
            
            # Registrar pago
            pago = Pago(
                alumno_id=alumno.id,
                monto=monto,
                periodo_mes=date.today().month,
                periodo_anio=date.today().year,
                metodo_pago=metodo,
                comprobante=comprobante
            )
            db.session.add(pago)
            
            # Actualizar vencimiento
            if alumno.fecha_vencimiento:
                nueva_fecha = alumno.fecha_vencimiento + relativedelta(days=30)
            else:
                nueva_fecha = calcular_vencimiento(datetime.utcnow())
            
            alumno.fecha_vencimiento = nueva_fecha
            alumno.estado_cuota = 'al_dia'
            
            db.session.commit()
            flash(f'Pago registrado. Próximo vencimiento: {nueva_fecha.strftime("%d/%m/%Y")}', 'success')
            return redirect(url_for('alumnos'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('pagar_alumno.html', alumno=alumno)

@app.route('/alumnos/pagos/<int:id>/historial')
@login_required
def historial_pagos_alumno(id):
    alumno = Alumno.query.get_or_404(id)
    pagos = Pago.query.filter_by(alumno_id=id).order_by(Pago.fecha_pago.desc()).all()
    return render_template('historial_pagos_alumno.html', alumno=alumno, pagos=pagos)

@app.route('/alumnos/deudores')
@login_required
def alumnos_deudores():
    deudores = Alumno.query.filter(
        (Alumno.estado_cuota == 'deuda') | (Alumno.fecha_vencimiento < date.today())
    ).order_by(Alumno.fecha_vencimiento).all()
    return render_template('alumnos_deudores.html', alumnos=deudores)

# ====================== PERSONALIZADOS ======================

@app.route('/personalizados')
@login_required
def personalizados():
    personalizados_lista = Personalizado.query.order_by(Personalizado.fecha_inscripcion.desc()).all()
    return render_template('personalizados.html', personalizados=personalizados_lista)

@app.route('/personalizados/nuevo', methods=['GET', 'POST'])
@login_required
def nuevo_personalizado():
    if request.method == 'POST':
        try:
            nuevo = Personalizado(
                nombre=request.form['nombre'],
                dni=request.form['dni'],
                telefono=request.form.get('telefono', ''),
                email=request.form.get('email', ''),
                entrenador=request.form.get('entrenador', ''),
                valor_mensual=float(request.form.get('valor_mensual', Configuracion.get('cuota_personalizado', 30000))),
                activo=True
            )
            nuevo.fecha_vencimiento = calcular_vencimiento(datetime.utcnow())
            db.session.add(nuevo)
            db.session.commit()
            flash(f'Personalizado {nuevo.nombre} agregado', 'success')
            return redirect(url_for('personalizados'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('nuevo_personalizado.html')

@app.route('/personalizados/editar/<int:id>', methods=['GET', 'POST'])
@login_required
def editar_personalizado(id):
    personalizado = Personalizado.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            personalizado.nombre = request.form['nombre']
            personalizado.dni = request.form['dni']
            personalizado.telefono = request.form.get('telefono', '')
            personalizado.email = request.form.get('email', '')
            personalizado.entrenador = request.form.get('entrenador', '')
            personalizado.valor_mensual = float(request.form.get('valor_mensual', personalizado.valor_mensual))
            personalizado.activo = 'activo' in request.form
            db.session.commit()
            flash('Personalizado actualizado', 'success')
            return redirect(url_for('personalizados'))
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('editar_personalizado.html', personalizado=personalizado)

@app.route('/personalizados/eliminar/<int:id>')
@login_required
def eliminar_personalizado(id):
    personalizado = Personalizado.query.get_or_404(id)
    nombre = personalizado.nombre
    db.session.delete(personalizado)
    db.session.commit()
    flash(f'Personalizado {nombre} eliminado', 'success')
    return redirect(url_for('personalizados'))

@app.route('/personalizados/<int:id>/pagar', methods=['GET', 'POST'])
@login_required
def pagar_personalizado(id):
    personalizado = Personalizado.query.get_or_404(id)
    
    if request.method == 'POST':
        try:
            monto = float(request.form.get('monto', personalizado.valor_mensual))
            metodo = request.form.get('metodo_pago', 'efectivo')
            comprobante = request.form.get('comprobante', '')
            
            pago = PagoPersonalizado(
                personalizado_id=personalizado.id,
                monto=monto,
                periodo_mes=date.today().month,
                periodo_anio=date.today().year,
                metodo_pago=metodo,
                comprobante=comprobante
            )
            db.session.add(pago)
            
            if personalizado.fecha_vencimiento:
                nueva_fecha = personalizado.fecha_vencimiento + relativedelta(days=30)
            else:
                nueva_fecha = calcular_vencimiento(datetime.utcnow())
            
            personalizado.fecha_vencimiento = nueva_fecha
            
            db.session.commit()
            flash(f'Pago registrado. Próximo vencimiento: {nueva_fecha.strftime("%d/%m/%Y")}', 'success')
            return redirect(url_for('personalizados'))
            
        except Exception as e:
            db.session.rollback()
            flash(f'Error: {str(e)}', 'error')
    
    return render_template('pagar_personalizado.html', personalizado=personalizado)

# ====================== BEBIDAS ======================

@app.route('/bebidas')
@login_required
def bebidas():
    bebidas_lista = Bebida.query.order_by(Bebida.categoria, Bebida.nombre).all()
    categorias = ['agua', 'gatorade', 'isotonico', 'proteina']
    return render_template('bebidas.html', bebidas=bebidas_lista, categorias=categorias)

@app.route('/bebidas/nuevo', methods=['POST'])
@login_required
def nueva_bebida():
    if current_user.role != 'admin':
        flash('Solo administradores', 'error')
        return redirect(url_for('bebidas'))
    
    try:
        nueva = Bebida(
            nombre=request.form['nombre'],
            categoria=request.form.get('categoria', 'agua'),
            precio=float(request.form['precio']),
            stock=int(request.form.get('stock', 0)),
            tamanio=request.form.get('tamanio', '')
        )
        db.session.add(nueva)
        db.session.commit()
        flash('Bebida agregada', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('bebidas'))

@app.route('/bebidas/editar/<int:id>', methods=['POST'])
@login_required
def editar_bebida(id):
    if current_user.role != 'admin':
        flash('Solo administradores', 'error')
        return redirect(url_for('bebidas'))
    
    bebida = Bebida.query.get_or_404(id)
    try:
        bebida.nombre = request.form['nombre']
        bebida.precio = float(request.form['precio'])
        bebida.stock = int(request.form.get('stock', 0))
        bebida.tamanio = request.form.get('tamanio', '')
        db.session.commit()
        flash('Bebida actualizada', 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('bebidas'))

@app.route('/bebidas/eliminar/<int:id>')
@login_required
def eliminar_bebida(id):
    if current_user.role != 'admin':
        flash('Solo administradores', 'error')
        return redirect(url_for('bebidas'))
    
    bebida = Bebida.query.get_or_404(id)
    db.session.delete(bebida)
    db.session.commit()
    flash('Bebida eliminada', 'success')
    return redirect(url_for('bebidas'))

# ====================== VENTAS ======================

@app.route('/venta-bebida', methods=['POST'])
@login_required
def registrar_venta_bebida():
    try:
        bebida_id = request.form.get('bebida_id')
        cantidad = int(request.form.get('cantidad', 1))
        alumno_id = request.form.get('alumno_id')
        
        bebida = Bebida.query.get(bebida_id)
        if not bebida:
            flash('Bebida no encontrada', 'error')
            return redirect(url_for('index'))
        
        if bebida.stock < cantidad:
            flash(f'Stock insuficiente. Solo hay {bebida.stock} unidades', 'error')
            return redirect(url_for('index'))
        
        monto = bebida.precio * cantidad
        
        venta = VentaBebida(
            bebida_id=bebida.id,
            bebida_nombre=bebida.nombre,
            cantidad=cantidad,
            monto=monto,
            alumno_id=alumno_id if alumno_id else None,
            usuario_id=current_user.id
        )
        
        bebida.stock -= cantidad
        db.session.add(venta)
        db.session.commit()
        
        alumno_nombre = Alumno.query.get(alumno_id).nombre if alumno_id else 'Sin alumno'
        flash(f'Venta registrada: {bebida.nombre} x{cantidad} - ${monto} - {alumno_nombre}', 'success')
    except Exception as e:
        db.session.rollback()
        flash(f'Error: {str(e)}', 'error')
    
    return redirect(url_for('index'))

@app.route('/ventas/bebidas')
@login_required
def ventas_bebidas():
    ventas = VentaBebida.query.order_by(VentaBebida.fecha.desc()).limit(100).all()
    return render_template('ventas_bebidas.html', ventas=ventas)

# ====================== REPORTES ======================

@app.route('/reportes')
@login_required
def reportes():
    hoy = date.today()
    
    # Ventas por día
    ventas_dias = []
    for i in range(29, -1, -1):
        dia = hoy - timedelta(days=i)
        total = db.session.query(func.sum(VentaBebida.monto)).filter(func.date(VentaBebida.fecha) == dia).scalar() or 0
        ventas_dias.append({'fecha': dia.strftime('%d/%m'), 'total': total})
    
    # Ventas por categoría de bebida
    ventas_categoria = db.session.query(
        Bebida.categoria,
        func.sum(VentaBebida.monto).label('total')
    ).join(VentaBebida, VentaBebida.bebida_id == Bebida.id).group_by(Bebida.categoria).order_by(func.sum(VentaBebida.monto).desc()).all()
    
    # Top bebidas
    top_bebidas = db.session.query(
        VentaBebida.bebida_nombre,
        func.sum(VentaBebida.cantidad).label('total_cantidad'),
        func.sum(VentaBebida.monto).label('total_monto')
    ).group_by(VentaBebida.bebida_nombre).order_by(func.sum(VentaBebida.monto).desc()).limit(10).all()
    
    # Cobranza mensual
    cobranza_mensual = db.session.query(
        func.sum(Pago.monto).label('total_alumnos'),
        func.sum(PagoPersonalizado.monto).label('total_personalizados')
    ).first()
    
    # Alumnos por estado de cuota
    alumnos_estado = db.session.query(
        Alumno.estado_cuota,
        func.count(Alumno.id).label('total')
    ).group_by(Alumno.estado_cuota).all()
    
    # Ingresos mensuales
    ingresos_meses = []
    for i in range(5, -1, -1):
        mes = hoy.replace(day=1) - timedelta(days=i*30)
        mes_inicio = mes.replace(day=1)
        if mes.month == 12:
            mes_fin = mes.replace(day=31)
        else:
            mes_fin = mes.replace(month=mes.month+1, day=1) - timedelta(days=1)
        
        ventas_total = db.session.query(func.sum(VentaBebida.monto)).filter(
            VentaBebida.fecha >= mes_inicio,
            VentaBebida.fecha <= mes_fin
        ).scalar() or 0
        
        cuotas_alumnos = db.session.query(func.sum(Pago.monto)).filter(
            Pago.fecha_pago >= mes_inicio,
            Pago.fecha_pago <= mes_fin
        ).scalar() or 0
        
        cuotas_personalizados = db.session.query(func.sum(PagoPersonalizado.monto)).filter(
            PagoPersonalizado.fecha_pago >= mes_inicio,
            PagoPersonalizado.fecha_pago <= mes_fin
        ).scalar() or 0
        
        nombres_meses = ['Ene', 'Feb', 'Mar', 'Abr', 'May', 'Jun', 'Jul', 'Ago', 'Sep', 'Oct', 'Nov', 'Dic']
        ingresos_meses.append({
            'mes': nombres_meses[mes.month-1],
            'ventas': ventas_total,
            'cuotas': cuotas_alumnos + cuotas_personalizados,
            'total': ventas_total + cuotas_alumnos + cuotas_personalizados
        })
    
    return render_template('reportes.html', 
                          ventas_dias=ventas_dias,
                          ventas_categoria=ventas_categoria,
                          top_bebidas=top_bebidas,
                          cobranza_mensual=cobranza_mensual,
                          alumnos_estado=alumnos_estado,
                          ingresos_meses=ingresos_meses)

@app.route('/reportes/exportar')
@login_required
def exportar_reportes():
    if current_user.role != 'admin':
        flash('Solo administradores', 'error')
        return redirect(url_for('index'))
    
    ventas = VentaBebida.query.order_by(VentaBebida.fecha.desc()).limit(500).all()
    alumnos = Alumno.query.all()
    personalizados = Personalizado.query.all()
    pagos_alumnos = Pago.query.all()
    pagos_personalizados = PagoPersonalizado.query.all()
    
    df_ventas = pd.DataFrame([{
        'Fecha': v.fecha.strftime('%d/%m/%Y %H:%M'),
        'Producto': v.bebida_nombre,
        'Cantidad': v.cantidad,
        'Monto': v.monto,
        'Alumno': v.alumno.nombre if v.alumno else 'Sin alumno',
        'Vendedor': v.usuario.username if v.usuario else '-'
    } for v in ventas])
    
    df_alumnos = pd.DataFrame([{
        'Nombre': a.nombre,
        'DNI': a.dni,
        'Teléfono': a.telefono,
        'Email': a.email,
        'Cuota Mensual': a.valor_cuota,
        'Estado': a.estado_cuota,
        'Vencimiento': a.fecha_vencimiento.strftime('%d/%m/%Y') if a.fecha_vencimiento else '-'
    } for a in alumnos])
    
    df_personalizados = pd.DataFrame([{
        'Nombre': p.nombre,
        'DNI': p.dni,
        'Entrenador': p.entrenador,
        'Cuota Mensual': p.valor_mensual,
        'Vencimiento': p.fecha_vencimiento.strftime('%d/%m/%Y') if p.fecha_vencimiento else '-'
    } for p in personalizados])
    
    output = BytesIO()
    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        df_ventas.to_excel(writer, sheet_name='Ventas', index=False)
        df_alumnos.to_excel(writer, sheet_name='Alumnos', index=False)
        df_personalizados.to_excel(writer, sheet_name='Personalizados', index=False)
    
    output.seek(0)
    return send_file(output, download_name=f'reporte_boxfit_{date.today()}.xlsx', as_attachment=True)

# ====================== CONFIGURACIÓN ======================

@app.route('/configuracion', methods=['GET', 'POST'])
@login_required
def configuracion():
    if current_user.role != 'admin':
        flash('Solo administradores', 'error')
        return redirect(url_for('index'))
    
    if request.method == 'POST':
        Configuracion.set('cuota_normal', request.form.get('cuota_normal', '15000'))
        Configuracion.set('cuota_personalizado', request.form.get('cuota_personalizado', '30000'))
        Configuracion.set('nombre_gimnasio', request.form.get('nombre_gimnasio', 'BoxFit Gym'))
        Configuracion.set('logo', request.form.get('logo', '🥊'))
        flash('Configuración guardada', 'success')
        return redirect(url_for('configuracion'))
    
    config = {
        'cuota_normal': Configuracion.get('cuota_normal', '15000'),
        'cuota_personalizado': Configuracion.get('cuota_personalizado', '30000'),
        'nombre_gimnasio': Configuracion.get('nombre_gimnasio', 'BoxFit Gym'),
        'logo': Configuracion.get('logo', '🥊')
    }
    
    return render_template('configuracion.html', config=config)

# ====================== INICIALIZACIÓN ======================

@app.cli.command("init-db")
def init_db():
    db.create_all()
    
    if not User.query.filter_by(username='admin').first():
        admin = User(username='admin', password=generate_password_hash('admin123'), role='admin')
        db.session.add(admin)
        db.session.commit()
        print(">>> Usuario admin creado: admin / admin123")
    
    if Bebida.query.count() == 0:
        bebidas = [
            Bebida(nombre='Agua Mineral', categoria='agua', precio=800, stock=100, tamanio='500ml'),
            Bebida(nombre='Agua con Gas', categoria='agua', precio=900, stock=80, tamanio='500ml'),
            Bebida(nombre='Gatorade Naranja', categoria='gatorade', precio=1500, stock=50, tamanio='500ml'),
            Bebida(nombre='Gatorade Limón', categoria='gatorade', precio=1500, stock=50, tamanio='500ml'),
            Bebida(nombre='Gatorade Frutilla', categoria='gatorade', precio=1500, stock=50, tamanio='500ml'),
            Bebida(nombre='Isotónico Powerade', categoria='isotonico', precio=1400, stock=40, tamanio='500ml'),
            Bebida(nombre='Proteína Whey', categoria='proteina', precio=2500, stock=30, tamanio='1 scoop'),
            Bebida(nombre='Batido Proteico', categoria='proteina', precio=3000, stock=25, tamanio='500ml'),
        ]
        for b in bebidas:
            db.session.add(b)
        db.session.commit()
        print(">>> Bebidas creadas")
    
    print(">>> Base de datos inicializada")

if __name__ == '__main__':
    with app.app_context():
        db.create_all()
        if not User.query.filter_by(username='admin').first():
            admin = User(username='admin', password=generate_password_hash('admin123'), role='admin')
            db.session.add(admin)
            db.session.commit()
    
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)