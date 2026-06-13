import os
import sqlite3
from datetime import datetime
import time
import threading

# Configuración del sistema
CAPACIDAD_MAXIMA = 100
ALERTA_CAPACIDAD = 80

# === ESCALA DE JERARQUÍAS (RBAC) ===
ROLES = {
    'Superadmin': 100,
    'Admin': 80,
    'User': 20,
    'Guest': 10
}

# NOTA: Quité la línea que borraba la base de datos automáticamente al iniciar.
# De lo contrario, cada vez que abras el programa se borrarían los usuarios que registraste.
class SafePassControl:
    def __init__(self):
        self.aforo_actual = 0
        self.lock = threading.Lock()
        self.inicializar_db() 
        self.cargar_aforo_inicial()
    
    def inicializar_db(self):
        """Inicializa todas las tablas necesarias"""
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS usuarios (
                id_rfid TEXT PRIMARY KEY,
                nombre TEXT NOT NULL,
                departamento TEXT,
                estado TEXT DEFAULT 'Activo',
                rol TEXT DEFAULT 'User'
            )
        ''')
        
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
        
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS aforo (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp DATETIME,
                personas_dentro INTEGER,
                capacidad_maxima INTEGER,
                porcentaje REAL
            )
        ''')
        
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
        print(f" Aforo inicial: {self.aforo_actual}/{CAPACIDAD_MAXIMA} personas")
    
    def obtener_usuario(self, id_rfid):
        """Busca un usuario por su RFID y retorna sus datos"""
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        cursor.execute("SELECT nombre, departamento, estado, rol FROM usuarios WHERE id_rfid = ?", (id_rfid,))
        usuario = cursor.fetchone()
        conn.close()
        return usuario

    def registrar_usuario_en_db(self, id_rfid, nombre, departamento, rol):
        """Inserta un nuevo usuario de forma dinámica en la Base de Datos"""
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        try:
            cursor.execute('''
                INSERT INTO usuarios (id_rfid, nombre, departamento, estado, rol)
                VALUES (?, ?, ?, 'Activo', ?)
            ''', (id_rfid, nombre, departamento, rol))
            conn.commit()
            print(f" ¡Usuario '{nombre}' registrado con éxito en la base de datos!")
            return True
        except sqlite3.IntegrityError:
            print(f" Error: El código RFID '{id_rfid}' ya está asignado a otro usuario.")
            return False
        finally:
            conn.close()

    def tiene_permiso(self, rol_usuario, rol_requerido):
        peso_usuario = ROLES.get(rol_usuario, 0)
        peso_requerido = ROLES.get(rol_requerido, 100)
        return peso_usuario >= peso_requerido

    def validar_credencial(self, id_rfid, tipo_movimiento='ENTRADA'):
        usuario = self.obtener_usuario(id_rfid)
        
        ahora = datetime.now()
        fecha = ahora.strftime('%Y-%m-%d')
        hora = aunque_hora = ahora.strftime('%H:%M:%S')
        
        if not usuario:
            resultado = "DENEGADO: ID Desconocido"
            acceso = False
            nombre = "Desconocido"
            print(f" {hora} - ACCESO DENEGADO: ID {id_rfid} no registrado")
            
        elif usuario[2] != 'Activo':
            nombre = usuario[0]
            resultado = f"DENEGADO: Credencial Inactiva ({nombre})"
            acceso = False
            print(f" {hora} - ACCESO DENEGADO: {nombre} - Credencial inactiva")
            
        else:
            nombre = usuario[0]
            rol = usuario[3]
            
            if tipo_movimiento == 'ENTRADA':
                with self.lock:
                    if self.aforo_actual >= CAPACIDAD_MAXIMA and not self.tiene_permiso(rol, 'Admin'):
                        resultado = "DENEGADO: Aforo máximo alcanzado"
                        acceso = False
                        print(f"🚫 {hora} - ACCESO DENEGADO: {nombre} - Edificio lleno")
                    else:
                        self.aforo_actual += 1
                        resultado = f"PERMITIDO: {nombre} ({rol})"
                        acceso = True
                        print(f" {hora} - ACCESO CONCEDIDO: {nombre} [{rol}]")
                        print(f"  Aforo: {self.aforo_actual}/{CAPACIDAD_MAXIMA}")
                        self.verificar_alerta_capacidad()
            else: # SALIDA
                with self.lock:
                    if self.aforo_actual > 0:
                        self.aforo_actual -= 1
                        resultado = f"SALIDA: {nombre}"
                        acceso = True
                        print(f" {hora} - SALIDA: {nombre}")
                        print(f"  Aforo: {self.aforo_actual}/{CAPACIDAD_MAXIMA}")
                    else:
                        resultado = "ERROR: Aforo negativo"
                        acceso = True
                        print(f" {hora} - CORRECCIÓN: {nombre}")
        
        # Registrar en historial
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO historial (id_rfid, fecha, hora, tipo_movimiento, resultado, aforo_restante) 
            VALUES (?, ?, ?, ?, ?, ?)
        ''', (id_rfid, fecha, hora, tipo_movimiento, resultado, self.aforo_actual))
        
        # Registrar aforo
        cursor.execute('''
            INSERT INTO aforo (timestamp, personas_dentro, capacidad_maxima, porcentaje) 
            VALUES (?, ?, ?, ?)
        ''', (ahora, self.aforo_actual, CAPACIDAD_MAXIMA, (self.aforo_actual / CAPACIDAD_MAXIMA) * 100))
        
        conn.commit()
        conn.close()
        return acceso, resultado, nombre
    
    def verificar_alerta_capacidad(self):
        porcentaje = (self.aforo_actual / CAPACIDAD_MAXIMA) * 100
        if self.aforo_actual >= CAPACIDAD_MAXIMA:
            self.registrar_alerta('CRÍTICA', f'¡AFORO MÁXIMO! {self.aforo_actual}/{CAPACIDAD_MAXIMA}')
        elif porcentaje >= ALERTA_CAPACIDAD:
            self.registrar_alerta('ADVERTENCIA', f'Aforo al {porcentaje:.0f}% ({self.aforo_actual}/{CAPACIDAD_MAXIMA})')
    
    def registrar_alerta(self, tipo, mensaje):
        conn = sqlite3.connect('acceso_edificio.db')
        cursor = conn.cursor()
        cursor.execute('''
            INSERT INTO alertas (timestamp, tipo, mensaje, aforo_actual, leida)
            VALUES (?, ?, ?, ?, 0)
        ''', (datetime.now(), tipo, mensaje, self.aforo_actual))
        conn.commit()
        conn.close()
        print(f"\n ALERTA {tipo}: {mensaje}\n")
    
    def mostrar_dashboard(self):
        porcentaje = (self.aforo_actual / CAPACIDAD_MAXIMA) * 100
        print("\n" + "="*50)
        print(" DASHBOARD SAFE-PASS")
        print("="*50)
        print(f" Personas dentro: {self.aforo_actual}/{CAPACIDAD_MAXIMA}")
        print(f" Ocupación: {porcentaje:.1f}%")
        
        barra_len = 30
        lleno = int(barra_len * porcentaje / 100)
        barra = "█" * lleno + "-" * (barra_len - lleno)
        print(f"[{barra}]")
        print("="*50)

def menu_principal():
    print("\n" + "="*40)
    print(" SAFE-PASS CONTROL")
    print("="*40)
    print("1.  Registrar ENTRADA")
    print("2.  Registrar SALIDA")
    print("3.  Ver DASHBOARD")
    print("4.  REGISTRAR NUEVO USUARIO")
    print("5.  Salir")
    print("="*40)

def interfaz_consola():
    sistema = SafePassControl()
    
    while True:
        menu_principal()
        opcion = input("Seleccione opción: ")
        
        if opcion == '1':
            rfid = input("Pase la tarjeta RFID (Entrada): ").strip()
            if rfid:
                sistema.validar_credencial(rfid, 'ENTRADA')
            else:
                print(" Código inválido")
        
        elif opcion == '2':
            rfid = input("Pase la tarjeta RFID (Salida): ").strip()
            if rfid:
                sistema.validar_credencial(rfid, 'SALIDA')
            else:
                print(" Código inválido")
        
        elif opcion == '3':
            print("\n[Autenticación] Pase tarjeta de Administrador:")
            rfid_admin = input("RFID: ").strip()
            user_data = sistema.obtener_usuario(rfid_admin)
            
            if user_data and sistema.tiene_permiso(user_data[3], 'Admin'):
                sistema.mostrar_dashboard()
            else:
                print(" Acceso Denegado: Permisos insuficientes.")
        
        elif opcion == '4':
            print("\n" + "-"*30)
            print(" REGISTRO DE NUEVO USUARIO")
            print("-"*30)
            
            # 1. Validar que quien registra sea un Administrador o Superadmin
            print("Para registrar un usuario, primero autorice con una tarjeta Admin o Superadmin:")
            rfid_autoriza = input("RFID de Autorización: ").strip()
            autorizador = sistema.obtener_usuario(rfid_autoriza)
            
            if autorizador and sistema.tiene_permiso(autorizador[3], 'Admin'):
                print(f" Autenticado como: {autorizador[0]} ({autorizador[2]})")
                
                # 2. Solicitar los datos del nuevo usuario
                nuevo_rfid = input("\nIngrese Numero de ID: ").strip()
                nuevo_nombre = input("Ingrese Nombre completo: ").strip()
                nuevo_depto = input("Ingrese Dep o Carrera: ").strip()
                
                print("\nRoles disponibles: Superadmin, Admin, User, Guest")
                nuevo_rol = input("Asigne un rol: ").strip()
                
                # Validar que el rol ingresado exista
                if nuevo_rol not in ROLES:
                    print(" Rol inválido. Se asignará 'User' por defecto.")
                    nuevo_rol = 'User'
                
                if nuevo_rfid and nuevo_nombre:
                    sistema.registrar_usuario_en_db(nuevo_rfid, nuevo_nombre, nuevo_depto, nuevo_rol)
                else:
                    print(" Error: El RFID y el Nombre son obligatorios.")
            else:
                print(" Acceso Denegado: No tienes permisos para registrar usuarios.")
                
        elif opcion == '5':
            print("\n ¡Hasta luego!")
            break
        else:
            print(" Opción inválida")

# ============ EJECUCIÓN PRINCIPAL ============
if __name__ == "__main__":
    interfaz_consola()