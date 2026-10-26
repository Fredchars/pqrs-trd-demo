# Demostración PQRS · TRD y archivo físico

**Demostración con datos ficticios · Powered by ATm Consulting**

Aplicación de ejemplo (Streamlit) para mostrar la gestión de PQRS, las tablas de retención documental (TRD),
los expedientes electrónicos y el archivo físico (cajas, rótulos QR y préstamos). No contiene información real.

## Ejecutar

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
PQRS_BACKEND=sqlite streamlit run app/Inicio.py
```

La primera vez se siembran datos ficticios en una base SQLite local. En *Administración › pestaña «Tareas y demo» › Reiniciar demo* se vuelve al estado inicial.
Los datos son temporales: si la aplicación se reinicia, vuelven al estado inicial.

## Publicar en Streamlit Community Cloud

Archivo principal: `app/Inicio.py`. En *Advanced settings › Secrets* basta con:

```toml
PQRS_BACKEND = "sqlite"
APP_URL = "https://<su-direccion>.streamlit.app"
```

## Acceso a la demo

La pantalla *Ingresar* muestra botones para entrar con un clic con cada rol (archivista, supervisor, abogado, auditor, administrador…).
Todos los usuarios son ficticios (`@pqrs.example.com`).

**Proteger la demo publicada (opcional):** por defecto cualquiera que tenga el enlace puede entrar con los botones
(pensado para presentarla a un cliente). Para pedir una clave antes de mostrarlos, agregue en *Secrets* de Streamlit Cloud
`PQRS_DEMO_CLAVE = "una-clave-que-usted-elija"` y reinicie la app. No escriba esa clave en el repositorio.

## Pruebas

```bash
pip install -r requirements-dev.txt
python -m pytest -q
```

> Sin firma digital certificada, preservación digital a largo plazo, certificación archivística ni OCR.
> Ejecutar una disposición solo registra la decisión. El cumplimiento archivístico lo valida el archivista.
