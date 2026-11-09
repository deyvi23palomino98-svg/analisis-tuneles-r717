"""Panel de análisis de túneles R717. Datos cargados en la sesión, no en GitHub."""
import re
from io import BytesIO
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

st.set_page_config(page_title="Túneles R717", page_icon="❄️", layout="wide")
st.title("❄️ Análisis frigorífico · Túneles R717")
st.caption("Uva de mesa | ICM 100 / ICAD 1200 | Succión húmeda común")
st.info("Carga tus Excel aquí. No los subas al repositorio público de GitHub. "
        "Esta primera versión analiza archivos durante la sesión; no almacena un historial permanente.")

with st.sidebar:
    st.header("Parámetros")
    seteo = st.number_input("Seteo de AMB (°C)", value=0.2, step=0.1, format="%.1f")
    limite = st.number_input("Límite mínimo AMB (°C)", value=-0.2, step=0.1, format="%.1f")
    umbral_pausa = st.number_input("Considerar pausa si faltan al menos (min)", min_value=1, value=1)
    antes = st.slider("Minutos antes de un arranque", 5, 60, 15)
    despues = st.slider("Minutos después de un arranque", 10, 120, 30)
    st.caption("Los huecos se interpretan como posibles cambios de flujo, sujetos a confirmación operacional.")

files = st.file_uploader("Selecciona los Excel de uno o varios túneles", type="xlsx", accept_multiple_files=True)

CAMPOS = ["fecha", "pallets", "icad", "setp", "psuc", "pbom", "amb", "amb2"]


def read_tunnel(f):
    """La hoja 'Series' usada en los Excel proporcionados tiene 8 columnas."""
    raw = pd.read_excel(f, sheet_name="Series", engine="openpyxl")
    if raw.shape[1] < 8:
        raise ValueError("Se esperaban 8 columnas (Fecha, pallets, ICAD, SETP, P.SUC, P.BOM, AMB, AMB2).")
    d = raw.iloc[:, :8].copy()
    d.columns = CAMPOS
    # Algunos exportadores entregan fechas como texto dd/mm/aaaa.
    d["fecha"] = pd.to_datetime(d["fecha"], dayfirst=True, errors="coerce")
    for c in CAMPOS[1:]:
        d[c] = pd.to_numeric(d[c].astype(str).str.replace(",", ".", regex=False), errors="coerce")
    d = d.dropna(subset=["fecha", "amb"]).sort_values("fecha")
    d = d.drop_duplicates("fecha", keep="last")
    if d.empty:
        raise ValueError("El archivo no tiene lecturas de fecha y AMB interpretables.")
    match = re.search(r"(?:^|[-_ ])T\s*0?(\d{1,2})(?:[-_ .]|$)", f.name, flags=re.I)
    if not match:
        match = re.search(r"TUNEL\s*0?(\d{1,2})", f.name, flags=re.I)
    tunel = f"T{int(match.group(1)):02d}" if match else f.name.rsplit('.', 1)[0]
    d["tunel"] = tunel
    d["archivo"] = f.name
    return d


def pause_events(d, threshold):
    dif = d["fecha"].diff().dt.total_seconds().div(60)
    gaps = []
    for ix in range(1, len(d)):
        elapsed = dif.iloc[ix]
        if pd.notna(elapsed) and elapsed > threshold:
            faltantes = max(0, int(round(elapsed)) - 1)
            if faltantes >= threshold:
                gaps.append({"Túnel": d["tunel"].iloc[0],
                             "Última lectura": d["fecha"].iloc[ix - 1],
                             "Reanudación": d["fecha"].iloc[ix],
                             "Min sin lectura": faltantes})
    return gaps


def metrics(d, limit, target, threshold):
    d = d.sort_values("fecha")
    inicio, fin = d["fecha"].iloc[0], d["fecha"].iloc[-1]
    idx = d.index[d["amb"] <= target]
    primera = d.loc[idx[0], "fecha"] if len(idx) else pd.NaT
    # Lecturas inferiores al límite: no equivale a duración exacta con registro discontinuo.
    bajo = (d["amb"] < limit)
    pauses = pause_events(d.reset_index(drop=True), threshold)
    return {"Túnel": d["tunel"].iloc[0],
            "Inicio": inicio, "Última lectura": fin,
            "Pallets": d["pallets"].dropna().iloc[0] if d["pallets"].notna().any() else None,
            "Primer seteo": primera,
            "Min hasta seteo": round((primera - inicio).total_seconds() / 60, 1) if pd.notna(primera) else None,
            "AMB mínima °C": d["amb"].min(), "Lecturas bajo límite": int(bajo.sum()),
            "Pausas detectadas": len(pauses),
            "Min sin registro": sum(e["Min sin lectura"] for e in pauses),
            "Duración transcurrida min": round((fin - inicio).total_seconds() / 60, 1)}

if not files:
    st.write("**Para comenzar:** adjunta los Excel de los túneles 01, 02 y 03. "
             "El sistema mostrará las curvas y los cálculos automáticamente.")
    st.stop()

frames, errors = [], []
for f in files:
    try:
        frames.append(read_tunnel(f))
    except Exception as e:
        errors.append(f"{f.name}: {e}")
for msg in errors:
    st.error(msg)
if not frames:
    st.stop()

data = pd.concat(frames, ignore_index=True)
summary = pd.DataFrame([metrics(d, limite, seteo, umbral_pausa) for _, d in data.groupby(["tunel", "archivo"])])
pauses = pd.DataFrame(sum((pause_events(d.reset_index(drop=True), umbral_pausa)
                           for _, d in data.groupby(["tunel", "archivo"])), []))

st.subheader("Resumen de enfriamiento")
c1, c2, c3, c4 = st.columns(4)
c1.metric("Archivos cargados", len(frames))
c2.metric("Túneles identificados", data["tunel"].nunique())
c3.metric("Ciclos que alcanzaron el seteo", int(summary["Primer seteo"].notna().sum()))
c4.metric("Pausas con huecos de tiempo", len(pauses))
st.dataframe(summary, hide_index=True, use_container_width=True)

st.subheader("Curvas sincronizadas por hora")
metricas = {"Temperatura AMB (°C)": "amb", "Sensor AMB2 (°C)": "amb2",
            "Presión succión (bar)": "psuc", "Presión bomba (bar)": "pbom",
            "Apertura ICAD (valor exportado)": "icad"}
seleccion = st.selectbox("Variable", list(metricas))
fig = px.line(data, x="fecha", y=metricas[seleccion], color="tunel",
              labels={"fecha": "Fecha y hora", "tunel": "Túnel", metricas[seleccion]: seleccion},
              hover_data=["pallets"])
if metricas[seleccion] == "amb":
    fig.add_hline(y=seteo, line_dash="dash", annotation_text="Seteo")
    fig.add_hline(y=limite, line_dash="dot", annotation_text="Mínimo permitido")
fig.update_layout(hovermode="x unified", height=460)
st.plotly_chart(fig, use_container_width=True)

st.subheader("Detalle de un túnel")
t = st.selectbox("Selecciona túnel", sorted(data["tunel"].unique()))
dt = data[data["tunel"] == t].sort_values("fecha")
fig2 = go.Figure()
for key, name in [("amb", "AMB"), ("amb2", "AMB2")]:
    fig2.add_trace(go.Scatter(x=dt["fecha"], y=dt[key], name=name, mode="lines"))
fig2.add_hline(y=seteo, line_dash="dash", annotation_text="Seteo")
fig2.add_hline(y=limite, line_dash="dot", annotation_text="Límite")
fig2.update_layout(title=f"{t}: temperatura ambiente", xaxis_title="Fecha y hora", yaxis_title="°C")
st.plotly_chart(fig2, use_container_width=True)

st.subheader("Posibles cambios de flujo (huecos entre lecturas)")
if pauses.empty:
    st.write("No se detectaron pausas con el umbral establecido.")
else:
    st.dataframe(pauses, hide_index=True, use_container_width=True)
    st.caption("Sin una señal de estado ON/OFF, un hueco también podría ser una pérdida de datos. "
               "Valida las pausas contra el sombreado rojo del archivo original o SCADA.")

st.subheader("Interacción entre túneles durante nuevos arranques")
st.caption("Se toma la primera lectura como hora aproximada de arranque. "
           "Las variaciones observadas son asociaciones temporales, NO pruebas de causalidad.")
arranques = data.groupby(["tunel", "archivo"], as_index=False)["fecha"].min().sort_values("fecha")
if len(arranques) < 2:
    st.write("Carga al menos dos túneles para examinar interacciones.")
else:
    opts = [f"{r.tunel} | {r.fecha:%d/%m/%Y %H:%M} | {r.archivo}" for r in arranques.itertuples(index=False)]
    event_ix = st.selectbox("Evento de arranque a analizar", range(len(opts)), format_func=lambda i: opts[i])
    event = arranques.iloc[event_ix]
    start = event["fecha"] - pd.Timedelta(minutes=antes)
    end = event["fecha"] + pd.Timedelta(minutes=despues)
    sub = data[(data["fecha"] >= start) & (data["fecha"] <= end) & (data["tunel"] != event["tunel"])].copy()
    if sub.empty:
        st.warning("No se encontraron lecturas de otros túneles en esta ventana.")
    else:
        tab1, tab2, tab3 = st.tabs(["AMB", "Presión de succión", "ICAD"])
        for tab, key, label in [(tab1, "amb", "AMB (°C)"), (tab2, "psuc", "P.SUC (bar)"), (tab3, "icad", "ICAD (exportado)")]:
            with tab:
                chart = px.line(sub, x="fecha", y=key, color="tunel", title=label)
                chart.add_vline(x=event["fecha"].timestamp() * 1000, line_dash="dash",
                                annotation_text=f"Inicio {event['tunel']}")
                st.plotly_chart(chart, use_container_width=True)
        rows = []
        for tunnel, v in sub.groupby("tunel"):
            before = v[(v["fecha"] < event["fecha"])].sort_values("fecha")
            after = v[(v["fecha"] >= event["fecha"])].sort_values("fecha")
            if before.empty or after.empty:
                continue
            r = {"Túnel afectado": tunnel}
            for col, name, unit in [("amb", "AMB", "°C"), ("psuc", "P.SUC", "bar"), ("icad", "ICAD", "unid.")]:
                r[f"Δ {name} inmediato ({unit})"] = round(after.iloc[0][col] - before.iloc[-1][col], 2)
                r[f"Δ {name} máximo posterior ({unit})"] = round(after[col].max() - before.iloc[-1][col], 2)
            rows.append(r)
        if rows:
            st.dataframe(pd.DataFrame(rows), hide_index=True, use_container_width=True)
            st.caption("Comparación descriptiva respecto a la última lectura previa. "
                       "Revisar cambios de compresores, defrost y operación antes de atribuir causas.")

st.subheader("Exportar resultados")
output = BytesIO()
with pd.ExcelWriter(output, engine="openpyxl") as writer:
    summary.to_excel(writer, index=False, sheet_name="Resumen")
    if not pauses.empty:
        pauses.to_excel(writer, index=False, sheet_name="Pausas")
st.download_button("⬇️ Descargar resumen en Excel", output.getvalue(),
                   file_name="resumen_tuneles_r717.xlsx",
                   mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
st.caption("Versión inicial: los minutos fuera de rango se reportan como cantidad de lecturas; "
           "el cálculo riguroso de duraciones por episodio y la lectura de colores del Excel "
           "se incorporarán en la siguiente versión.")
