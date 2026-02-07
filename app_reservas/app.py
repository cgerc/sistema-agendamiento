import datetime
import os
from flask import Flask, request, render_template_string, redirect
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
import sqlite3

app = Flask(__name__)

# Configuraciones
SCOPES = ['https://www.googleapis.com/auth/calendar']
CALENDARIOS = {
    'Antonio Bellet': 'tu_calendario_id_antonio@group.calendar.google.com',  # Reemplaza con IDs reales
    'Las Urbinas': 'tu_calendario_id_urbinas@group.calendar.google.com'
}

# Función para obtener servicio de Google Calendar
def get_calendar_service():
    creds = None
    if os.path.exists('token.json'):
        creds = Credentials.from_authorized_user_file('token.json', SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file('credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.json', 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

# Función para obtener slots disponibles (usa freebusy)
def get_available_slots(sede, fecha):
    service = get_calendar_service()
    time_min = datetime.datetime.combine(fecha, datetime.time.min).isoformat() + 'Z'
    time_max = datetime.datetime.combine(fecha, datetime.time.max).isoformat() + 'Z'
    body = {
        "timeMin": time_min,
        "timeMax": time_max,
        "items": [{"id": CALENDARIOS[sede]}]
    }
    try:
        result = service.freebusy().query(body=body).execute()
        busy = result['calendars'][CALENDARIOS[sede]].get('busy', [])
        # Calcular slots libres (asumiendo slots de 1 hora desde 9:00 a 18:00)
        slots_libres = []
        hora_inicio = datetime.datetime.combine(fecha, datetime.time(9, 0))
        for i in range(9):  # 9 slots de 1 hora
            slot_start = hora_inicio + datetime.timedelta(hours=i)
            slot_end = slot_start + datetime.timedelta(hours=1)
            es_libre = True
            for b in busy:
                b_start = datetime.datetime.fromisoformat(b['start'][:-1])
                b_end = datetime.datetime.fromisoformat(b['end'][:-1])
                if not (slot_end <= b_start or slot_start >= b_end):
                    es_libre = False
                    break
            if es_libre:
                slots_libres.append(f"{slot_start.hour}:00 - {slot_end.hour}:00")
        return slots_libres
    except HttpError as e:
        return []

# Función para crear reserva (insertar evento)
def crear_reserva(sede, psicologo, fecha, hora_inicio, duracion=60):
    service = get_calendar_service()
    start_time = datetime.datetime.combine(fecha, datetime.time.fromisoformat(hora_inicio))
    end_time = start_time + datetime.timedelta(minutes=duracion)
    event = {
        'summary': f'Reserva de {psicologo}',
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'America/Santiago'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'America/Santiago'},
    }
    try:
        service.events().insert(calendarId=CALENDARIOS[sede], body=event).execute()
        # Registrar en DB
        conn = sqlite3.connect('reservas.db')
        c = conn.cursor()
        c.execute('INSERT INTO reservas (psicologo, sede, fecha, hora) VALUES (?, ?, ?, ?)',
                  (psicologo, sede, fecha.isoformat(), hora_inicio))
        conn.commit()
        conn.close()
        return True
    except HttpError:
        return False

# Inicializar DB (ejecuta una vez)
def init_db():
    conn = sqlite3.connect('reservas.db')
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS reservas 
                 (id INTEGER PRIMARY KEY, psicologo TEXT, sede TEXT, fecha TEXT, hora TEXT)''')
    c.execute('''CREATE TABLE IF NOT EXISTS pagos 
                 (id INTEGER PRIMARY KEY, psicologo TEXT, monto REAL, fecha TEXT, descripcion TEXT)''')
    conn.commit()
    conn.close()

init_db()

# Rutas web
@app.route('/')
def home():
    return render_template_string('''
        <h1>Reservas de Boxes de Psicología</h1>
        <form action="/disponibilidad" method="post">
            Sede: <select name="sede">
                <option>Antonio Bellet</option>
                <option>Las Urbinas</option>
            </select><br>
            Fecha: <input type="date" name="fecha"><br>
            <input type="submit" value="Ver Disponibilidad">
        </form>
        <a href="/registro">Registrar Pago</a> | <a href="/reporte">Ver Reporte</a>
    ''')

@app.route('/disponibilidad', methods=['POST'])
def disponibilidad():
    sede = request.form['sede']
    fecha_str = request.form['fecha']
    fecha = datetime.date.fromisoformat(fecha_str)
    slots = get_available_slots(sede, fecha)
    html = f'<h2>Disponibilidad en {sede} para {fecha_str}</h2><ul>'
    for slot in slots:
        html += f'<li>{slot} <a href="/reservar?sede={sede}&fecha={fecha_str}&hora={slot.split("-")[0].strip()}">Reservar</a></li>'
    html += '</ul><a href="/">Volver</a>'
    return render_template_string(html)

@app.route('/reservar')
def reservar():
    sede = request.args['sede']
    fecha = datetime.date.fromisoformat(request.args['fecha'])
    hora = request.args['hora']
    psicologo = 'EjemploPsicologo'  # Reemplaza con login real
    if crear_reserva(sede, psicologo, fecha, hora):
        return 'Reserva creada exitosamente. <a href="/">Volver</a>'
    else:
        return 'Error al crear reserva.'

@app.route('/registro', methods=['GET', 'POST'])
def registro_pago():
    if request.method == 'POST':
        psicologo = request.form['psicologo']
        monto = float(request.form['monto'])
        fecha = request.form['fecha']
        desc = request.form['desc']
        conn = sqlite3.connect('reservas.db')
        c = conn.cursor()
        c.execute('INSERT INTO pagos (psicologo, monto, fecha, descripcion) VALUES (?, ?, ?, ?)',
                  (psicologo, monto, fecha, desc))
        conn.commit()
        conn.close()
        return 'Pago registrado. <a href="/">Volver</a>'
    return render_template_string('''
        <h2>Registrar Pago</h2>
        <form method="post">
            Psicólogo: <input name="psicologo"><br>
            Monto: <input name="monto" type="number"><br>
            Fecha: <input name="fecha" type="date"><br>
            Descripción: <input name="desc"><br>
            <input type="submit">
        </form>
    ''')

@app.route('/reporte')
def reporte():
    conn = sqlite3.connect('reservas.db')
    c = conn.cursor()
    c.execute('SELECT * FROM reservas')
    reservas = c.fetchall()
    c.execute('SELECT * FROM pagos')
    pagos = c.fetchall()
    conn.close()
    html = '<h2>Reporte de Reservas</h2><table border="1"><tr><th>Psicólogo</th><th>Sede</th><th>Fecha</th><th>Hora</th></tr>'
    for r in reservas:
        html += f'<tr><td>{r[1]}</td><td>{r[2]}</td><td>{r[3]}</td><td>{r[4]}</td></tr>'
    html += '</table><h2>Reporte de Pagos</h2><table border="1"><tr><th>Psicólogo</th><th>Monto</th><th>Fecha</th><th>Descripción</th></tr>'
    for p in pagos:
        html += f'<tr><td>{p[1]}</td><td>{p[2]}</td><td>{p[3]}</td><td>{p[4]}</td></tr>'
    html += '</table><a href="/">Volver</a>'
    return render_template_string(html)

if __name__ == '__main__':
    app.run(debug=True)