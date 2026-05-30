import os
import sqlite3
from datetime import datetime
import time
import threading

# Configuración del sistema
CAPACIDAD_MAXIMA = 100
ALERTA_CAPACIDAD = 80

# Eliminar base de datos antigua si existe
if os.path.exists('acceso_edificio.db'):
    os.remove('acceso_edificio.db')
    print("🗑️ Base de datos antigua eliminada")

class SafePassControl:
    def __init__(self):
        self.aforo_actual = 0
        self.lock = threading.Lock()
        self.inicializar_db() # Esto CREA las tablas
        self.cargar_aforo_inicial()
    
    def inicializar_db(self):
        """Inicializa todas las tablas necesarias"""
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        
        # Tabla de Usuarios
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id_rfid TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                departamento TEXT,
                estado TEXT DEFAULT 'Activo'
            )
        ''')
        
        # Tabla de Historial
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS historial (
                id_log INTEGER PRIMARY KEY AUTOINCREMENT,
                id_rfid TEXT,
                fecha DATE,
                hora TIME,
                tipo_movimiento TEXT,
                resultado TEXT,
                aforo_restante INTEGER
            )
        ''')
        
        # Tabla de Aforo
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS aforo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                personas_dentro INTEGER,
                capacidad_maxima INTEGER,
                porcentaje REAL
            )
        ''')
        
        # Tabla de Alertas
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS alertas (
                id_alerta INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                tipo TEXT,
                mensaje TEXT,
                aforo_actual INTEGER,
                leida BOOLEAN DEFAULT 0
            )
        ''')
        
        conn.commit()
        conn.close()
        print("✅ Base de datos y tablas creadas correctamente")
    
    def cargar_aforo_inicial(self):
        """Carga el aforo actual desde el último registro"""
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        cursor.execute("SELECT personas_dentro FROM aforo ORDER BY timestamp DESC LIMIT 1")
        ultimo = cursor.fetchone()
        if ultimo:
            self.aforo_actual = ultimo[0]
        else:
            self.aforo_actual = 0
        conn.close()
        print(f"📊 Aforo inicial: {self.aforo_actual}/{CAPACIDAD_MAXIMA} personas")
    
    def validar_credencial(self, id_rfid, tipo_movimiento='ENTRADA'):
        """Valida credencial y controla acceso"""
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        
        cursor.execute("SELECT nombre, departamento, estado FROM usuarios WHERE id_rfid = ?", (id_rfid,))
        usuario = cursor.fetchone()
        
        ahora = datetime.now()
        fecha = ahora.strftime('%Y-%m-%d')
        hora = ahora.strftime('%H:%M:%S')
        
        if not usuario:
            resultado = f"DENEGADO: ID Desconocido"
            acceso = False
            nombre = "Desconocido"
            print(f"❌ {hora} - ACCESO DENEGADO: ID {id_rfid} no registrado")
            
        elif usuario[2] != 'Activo':
            nombre = usuario[0]
            resultado = f"DENEGADO: Credencial Inactiva ({nombre})"
            acceso = False
            print(f"❌ {hora} - ACCESO DENEGADO: {nombre} - Credencial inactiva")
            
        else:
            nombre = usuario[0]
            depto = usuario[1]
            
            if tipo_movimiento == 'ENTRADA':
                with self.lock:
                    if self.aforo_actual >= CAPACIDAD_MAXIMA:
                        resultado = f"DENEGADO: Aforo máximo alcanzado"
                        acceso = False
                        print(f"🚫 {hora} - ACCESO DENEGADO: {nombre} - Edificio lleno")
                    else:
                        self.aforo_actual += 1
                        resultado = f"PERMITIDO: {nombre}"
                        acceso = True
                        print(f"✅ {hora} - ACCESO CONCEDIDO: {nombre}")
                        print(f" 📊 Aforo: {self.aforo_actual}/{CAPACIDAD_MAXIMA}")
                        self.verificar_alerta_capacidad()
            else: # SALIDA
                with self.lock:
                    if self.aforo_actual > 0:
                        self.aforo_actual -= 1
                        resultado = f"SALIDA: {nombre}"
                        acceso = True
                        print(f"🚪 {hora} - SALIDA: {nombre}")
                        print(f" 📊 Aforo: {self.aforo_actual}/{CAPACIDAD_MAXIMA}")
                    else:
                        resultado = f"ERROR: Aforo negativo"
                        acceso = True
                        print(f"⚠️ {hora} - CORRECCIÓN: {nombre}")
        
        # Registrar en historial
        cursor.execute('''
            INSERT INTO historial (id_rfid, fecha, hora, tipo_movimiento, resultado, aforo_restante) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (id_rfid, fecha, hora, tipo_movimiento, resultado, self.aforo_actual))
        
        # Registrar aforo
        cursor.execute('''
            INSERT INTO aforo (timestamp, personas_dentro, capacidad_maxima, porcentaje) 
            VALUES (?, ?, ?, ?)
        ''', (ahora, self.aforo_actual, CAPACIDAD_MAXIMA, 
              (self.aforo_actual / CAPACIDAD_MAXIMA) * 100))
        
        conn.commit()
        conn.close()
        return acceso, resultado, nombre
    
    def verificar_alerta_capacidad(self):
        """Verifica y genera alertas de capacidad"""
        porcentaje = (self.aforo_actual / CAPACIDAD_MAXIMA) * 100
        
        if self.aforo_actual >= CAPACIDAD_MAXIMA:
            self.registrar_alerta('CRÍTICA', f'¡AFORO MÁXIMO! {self.aforo_actual}/{CAPACIDAD_MAXIMA}')
        elif porcentaje >= ALERTA_CAPACIDAD:
            self.registrar_alerta('ADVERTENCIA', f'Aforo al {porcentaje:.0f}% ({self.aforo_actual}/{CAPACIDAD_MAXIMA})')
    
    def registrar_alerta(self, tipo, mensaje):
        """Registra alerta en BD"""
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO alertas (timestamp, tipo, mensaje, aforo_actual, leida)
            VALUES (?, ?, ?, ?, 0)
        ''', (datetime.now(), tipo, mensaje, self.aforo_actual))
        conn.commit()
        conn.close()
        print(f"\n🔔 ALERTA {tipo}: {mensaje}\n")
    
    def mostrar_dashboard(self):
        """Muestra dashboard de aforo"""
        porcentaje = (self.aforo_actual / CAPACIDAD_MAXIMA) * 100
        
        print("\n" + "="*50)
        print("📊 DASHBOARD SAFE-PASS")
        print("="*50)
        print(f"👥 Personas dentro: {self.aforo_actual}/{CAPACIDAD_MAXIMA}")
        print(f"📈 Ocupación: {porcentaje:.1f}%")
        
        # Barra visual
        barra_len = 30
        lleno = int(barra_len * porcentaje / 100)
        barra = "█" * lleno + "░" * (barra_len - lleno)
        print(f"[{barra}]")
        
        # Estado
        if self.aforo_actual >= CAPACIDAD_MAXIMA:
            print("🔴 EDIFICIO COMPLETO - ACCESO DENEGADO")
        elif porcentaje >= ALERTA_CAPACIDAD:
            print("🟡 ALERTA - Capacidad cercana al límite")
        elif self.aforo_actual > 0:
            print("🟢 OPERACIÓN NORMAL")
        else:
            print("⚪ EDIFICIO VACÍO")
        print("="*50)

def agregar_usuarios_prueba():
    """Agrega usuarios de demostración (después de crear tablas)"""
    conn = sqlite3.connect('acceso_edificio.db')
    cursor = conn.cursor()
    
    usuarios = [
        ('RFID001', 'Carlos Auditor', 'Finanzas', 'Activo'),
        ('RFID002', 'María López', 'IT', 'Activo'),
        ('RFID003', 'Juan Pérez', 'Ventas', 'Activo'),
        ('RFID004', 'Ana García', 'Recursos Humanos', 'Activo'),
        ('RFID005', 'Pedro Sánchez', 'Mantenimiento', 'Inactivo'),
        ('RFID099', 'Invitado Especial', 'Visitas', 'Activo'),
    ]
    
    try:
        cursor.executemany("INSERT OR IGNORE INTO usuarios (id_rfid, nombre, departamento, estado) VALUES (?, ?, ?, ?)", usuarios)
        conn.commit()
        print("✅ Usuarios de prueba cargados")
    except sqlite3.OperationalError as e:
        print(f"❌ Error al cargar usuarios: {e}")
    finally:
        conn.close()

def menu_principal():
    """Menú interactivo principal"""
    print("\n" + "="*40)
    print("🚪 SAFE-PASS CONTROL")
    print("="*40)
    print("1. 📥 Registrar ENTRADA")
    print("2. 📤 Registrar SALIDA")
    print("3. 📊 Ver DASHBOARD")
    print("4. 🚪 Salir")
    print("="*40)

def interfaz_consola():
    """Interfaz por consola"""
    sistema = SafePassControl() # Esto crea las tablas
    
    while True:
        menu_principal()
        opcion = input("Seleccione opción: ")
        
        if opcion == '1':
            rfid = input("Ingrese código RFID: ").strip()
            if rfid:
                sistema.validar_credencial(rfid, 'ENTRADA')
            else:
                print("❌ Código inválido")
        
        elif opcion == '2':
            rfid = input("Ingrese código RFID: ").strip()
            if rfid:
                sistema.validar_credencial(rfid, 'SALIDA')
            else:
                print("❌ Código inválido")
        
        elif opcion == '3':
            sistema.mostrar_dashboard()
        
        elif opcion == '4':
            print("\n👋 ¡Hasta luego!")
            break
        
        else:
            print("❌ Opción inválida")

# ============ EJECUCIÓN PRINCIPAL ============
if __name__ == "__main__":
    print("\n🚪 SAFE-PASS CONTROL v1.0")
    print("Sistema de seguridad de acceso con control de aforo\n")
    
    # Crear sistema y agregar usuarios
    print("Inicializando sistema...")
    sistema_temp = SafePassControl() # Crea las tablas
    agregar_usuarios_prueba() # Agrega usuarios
    
    # Iniciar interfaz
    interfaz_consola()