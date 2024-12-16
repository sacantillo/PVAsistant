import streamlit as st
import folium, math, datetime
from streamlit_folium import st_folium
from folium import plugins
from shapely.geometry import Polygon
import pyproj
import networkx as nx
from shapely.ops import transform
from geopy.geocoders import Nominatim
import matplotlib.pyplot as plt
import matplotlib.image as mpimg
from matplotlib.offsetbox import OffsetImage, AnnotationBbox
import googlemaps
from pynasapower.get_data import query_power
from pynasapower.geometry import point, bbox
import pandas as pd

def inicializar():
    if "map" not in st.session_state:
        st.session_state.map = folium.Map(location=[4.5709, -74.2973], zoom_start=6, no_tiles=True, control_scale=True, dragging=False, zoom_control=False)
        folium.TileLayer(tiles = 'https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}',attr = 'Google',name = 'Google Satellite',
        overlay = True,control = True).add_to(st.session_state.map)
    if "lat" not in st.session_state:
        st.session_state.lat = None
    if "lon" not in st.session_state:
        st.session_state.lon = None
    if "consumos_df" not in st.session_state:
        st.session_state.consumos_df = pd.DataFrame(columns=["Consumo (kWh-mes)", "Tarifa ($COP/kWh)"])

def carga_paneles():
    paneles = {
        "JAM72D40 - 590/LB": {"Pmax":590, "Vmp": 43.4, "Imp":13.59, "Voc":52,
                              "Isc":14.35, "Area":None, "Altura":2.333, "Base":1.134,
                              "Ancho":0.03, "Degradacion":0.004,"Peso":32.5 },
    }
    for panel in paneles.values():
        panel["Area"] = panel["Altura"] * panel["Base"]
    return paneles

def carga_inversores():
    inversores = {
        "S5-GC60K-LV": {"VmaxMPP":1000, "VminMPP": 180, "Vnom":450, "PmaxWp":60000,
                        "Pmax_kWp":60, "Vstart": 195, "NinMPPT":450, "Peso":89,
                        "ImaxMPPT": 256, "ImaxCC":320, "Poutmax":60000, "FPot":0.99,
                        "Freq":60, "Inomout": 157.5, "Ioutmax":157.5, "VnomAC":220}
    }
    return inversores

def geocode_address(address):
    gmaps = googlemaps.Client(key=st.secrets["API_KEY"])
    location = gmaps.geocode(address)
    return (location[0]['geometry']['location']['lat'], location[0]['geometry']['location']['lng']) if location else (None, None)

def setup_map(lat, lon, address):
    if lat and lon:
        st.session_state.map = folium.Map(location=[lat, lon], zoom_start=17, control_scale=True)
        folium.Marker([lat, lon], popup=address).add_to(st.session_state.map)
        folium.TileLayer(
            tiles='https://mt1.google.com/vt/lyrs=s&x={x}&y={y}&z={z}', attr='Google', name='Google Satellite'
        ).add_to(st.session_state.map)
        plugins.Draw(draw_options={'polygon': True}).add_to(st.session_state.map)
    else:
        st.warning("No se pudo encontrar la ubicación")


def calculate_area(polygon_coords):
    poly = Polygon(polygon_coords)

    #Usamos EPSG:4326 (coordenadas geográficas) a UTM basado en la ubicación del polígono
    wgs84 = pyproj.CRS("EPSG:4326")
    utm = pyproj.CRS("EPSG:3857")  #Proyección métrica para el cálculo de área
    project = pyproj.Transformer.from_crs(wgs84, utm, always_xy=True).transform

    #Transformar el polígono a coordenadas UTM
    poly_utm = transform(project, poly)

    return poly_utm.area


def HSP(lat, lon):
    if not lat or not lon:
        return 0, 0, 0
    gpoint = point(lon, lat, "EPSG:4326")
    data = query_power(gpoint, datetime.date(2023, 1, 1), datetime.date(2023, 12, 31), True, "", "re", [], "daily", "point", "csv")
    HSP_stats = data.groupby("MO")['ALLSKY_SFC_SW_DWN'].describe()[['min', 'mean', 'max']].mean()
    return HSP_stats['min'], HSP_stats['mean'], HSP_stats['max']

def consumo_diario(data):
    prom = data["Consumo (kWh-mes)"].mean()/30 if not data.empty else 0
    return prom

def costo_Energia(data):
    total = (data["Consumo (kWh-mes)"] * data['Tarifa ($COP/kWh)']).sum() if not data.empty else 0
    return total

def generar_diagrama(num_inversores, carriles_por_inversor, paneles_por_carril):
    G = nx.DiGraph()

    pos = {}
    x_offset = -7  #Desplazamiento horizontal para inversores
    y_offset = 0  #Desplazamiento vertical

    fig, ax = plt.subplots(figsize=(15, 10))

    for inv in range(1, num_inversores + 1):
        #Posición central del inversor
        y_inversor_centro = y_offset - (carriles_por_inversor + 1) * 1.5 / 2
        inv_node = f"Inversor {inv}"
        G.add_node(inv_node)
        pos[inv_node] = (x_offset, y_inversor_centro)  #Colocamos el inversor en el centro

        #Añadir ícono del inversor
        ab_inversor = AnnotationBbox(OffsetImage(mpimg.imread('images/inversor.png'), zoom=0.4), pos[inv_node], frameon=False)
        ax.add_artist(ab_inversor)

        #Añadir carriles y paneles
        for carril in range(1, carriles_por_inversor + 1):
            carril_node = f"Inversor {inv} - Carril {carril}"
            G.add_node(carril_node)
            pos[carril_node] = (x_offset + 1, y_offset - carril * 1.5)  #Carriles a la derecha del inversor
            G.add_edge(inv_node, carril_node)

            #Dibujar líneas con ángulos rectos: primero horizontal y luego vertical
            x_inversor, y_inversor = pos[inv_node]
            x_carril, y_carril = pos[carril_node]
            ax.plot([x_inversor, x_carril], [y_inversor, y_inversor], color="gray", linewidth=1)  #Línea horizontal
            ax.plot([x_carril, x_carril], [y_inversor, y_carril], color="gray", linewidth=1)  #Línea vertical

            #Conexión en serie de los paneles
            last_panel_node = carril_node
            for panel in range(1, paneles_por_carril + 1):
                panel_node = f"Inversor {inv} - Carril {carril} - Panel {panel}"
                G.add_node(panel_node)
                pos[panel_node] = (
                    pos[carril_node][0] + panel * 1,  #Espaciar paneles horizontalmente
                    pos[carril_node][1],  #Mantener la misma altura
                )
                G.add_edge(last_panel_node, panel_node)  #Conexión al último nodo (en serie)
                last_panel_node = panel_node

                #Añadir ícono del panel
                ab_panel = AnnotationBbox(OffsetImage(mpimg.imread('images/panel.png'), zoom=0.25), pos[panel_node], frameon=False)
                ax.add_artist(ab_panel)

            #Conectar todos los paneles de un mismo carril
            for i in range(1, paneles_por_carril):
                panel_1_node = f"Inversor {inv} - Carril {carril} - Panel {i}"
                panel_2_node = f"Inversor {inv} - Carril {carril} - Panel {i+1}"
                G.add_edge(panel_1_node, panel_2_node)

                #Dibujar la línea de conexión entre los paneles
                x_panel_1, y_panel_1 = pos[panel_1_node]
                x_panel_2, y_panel_2 = pos[panel_2_node]
                ax.plot([x_panel_1, x_panel_2], [y_panel_1, y_panel_2], color="gray", linewidth=1)

            #Conectar el primer panel del carril con la línea que llega del inversor
            primer_panel_node = f"Inversor {inv} - Carril {carril} - Panel 1"
            G.add_edge(carril_node, primer_panel_node)  #Conexión entre el carril y el primer panel
            x_carril, y_carril = pos[carril_node]
            x_panel, y_panel = pos[primer_panel_node]
            ax.plot([x_carril, x_panel], [y_carril, y_panel], color="gray", linewidth=1)

        y_offset -= 2*carriles_por_inversor  #Ajuste de espacio vertical para el siguiente inversor

    nx.draw_networkx_nodes(G, pos, node_size=0, node_color="skyblue", ax=ax)
    nx.draw_networkx_edges(G, pos, edgelist=[], width=0)  #Eliminar las líneas automáticas
    ax.axis("off")
    return fig


def app():
    st.set_page_config(page_title="PV Consulter", layout="wide")
    st.title("Información Instalación SSFV")
    inicializar()

    with st.container(border=True):
        st.markdown('<h3 style="font-size: 16px;">Ubicación:</h3>', unsafe_allow_html=True)
        ca, cb = st.columns([3, 1])
        with ca:
            address = st.text_input("Dirección:",label_visibility="collapsed")
        with cb:
            buscar = st.button("Buscar", use_container_width=True)
        alerta = st.empty()

    if buscar:
        if address.strip():
            lat, lon = geocode_address(address)
            st.session_state.lat, st.session_state.lon = lat, lon
            setup_map(lat, lon, address)
        else:
            alerta.warning("El campo no puede estar vacío. Por favor escribe una ubicación")

    _, HorasPico,_ = HSP(st.session_state.lat,st.session_state.lon)
    HorasPico = round(HorasPico,1)

    with st.container(border=True):
         ca, cb = st.columns(2)
         inyeccion = ca.slider('Inyección a la red (%)', 0, 100, 100)/100
         consumoHSP = cb.slider('Consumo en HSP (%)', 0, 100, 100)/100
         c1, c2 = st.columns([1, 3])
         with c2:
            st_data = st_folium(st.session_state.map, width=800, height=400)
            if st_data:
                all_drawings = st_data.get("all_drawings", [])
                if all_drawings:
                    #Extraer las coordenadas del primer dibujo
                    geometry = all_drawings[0].get("geometry", {})
                    if geometry.get("type") == "Polygon":
                        coords = geometry.get("coordinates", [])[0] #Primer anillo del polígono

                        #Verificar si hay al menos 3 puntos
                        if len(coords) >= 3:
                            #Calcular el área
                            area_m2 = calculate_area(coords)
                            st.success(f"Área: {area_m2:.2f} m².")
                        else:
                            st.warning("El polígono debe tener al menos 3 puntos.")
                    else:
                        st.warning("Por favor, dibuja un polígono.")
         with c1:
            #st.metric("HSP (max):", round(max,1))
            st.metric("Horas Solares Pico (HSP)",HorasPico)
            #st.metric("HSP (min):", round(min,1))

    st.sidebar.markdown(
    """
    <style>
        [data-testid="stSidebar"] > div:first-child {
            display: flex;
            justify-content: flex-start;
            align-items: flex-start;
            flex-direction: column;
        }
        
        [data-testid="stSidebar"] img {
            margin-top: -80px;  /* Ajustar según el espacio requerido */
            margin-left: 0px;
        }
    </style>
    """, unsafe_allow_html=True
    )

    st.sidebar.image("images/cotel-logotipo.png",caption="",use_column_width=True)
    consumo = st.sidebar.number_input("Consumo (kWh-mes)",key='consumo_input', min_value=0, step=1)
    tarifa = st.sidebar.number_input("Tarifa ($COP/kWh)",key='precio_input', min_value=0.00,step=0.01)

    if st.sidebar.button("Agregar Consumo",use_container_width=True):
      try:
        if consumo > 0 and tarifa > 0:
          st.session_state.consumos_df = pd.concat([st.session_state.consumos_df,
                                                    pd.DataFrame([[consumo,tarifa]], columns=["Consumo (kWh-mes)", "Tarifa ($COP/kWh)"])],
                                                    ignore_index=True)
          st.sidebar.success("Consumo agregado correctamente.")
        else:
          st.sidebar.warning("Por favor, ingrese valores válidos para el consumo y la tarifa.")
      except ValueError:
        st.sidebar.warning("Por favor, ingresa un valor numérico válido.")

    st.sidebar.write("Histórico de Consumos")
    st.sidebar.dataframe(st.session_state.consumos_df,use_container_width=True)
    if not st.session_state.consumos_df.empty:
      st.sidebar.metric(label="**Consumo Promedio (kWh-mes)**", value=f"{round(consumo_diario(st.session_state.consumos_df) * 30, 0):,.0f}")
      st.sidebar.metric(label="**Costo Total Energía ($ COP)**", value=f"{round(costo_Energia(st.session_state.consumos_df)):,}")

    else:
      st.sidebar.metric(label="**Consumo Promedio (kWh-mes):**", value="0.0")
      st.sidebar.metric(label="**Costo Total Energía ($ COP):**", value="0.0")

    if not st.session_state.consumos_df.empty:
      cons_prom = consumo_diario(st.session_state.consumos_df)
      if HorasPico > 0:
        pot_pico = round(consumoHSP*cons_prom*inyeccion/HorasPico,1)
      else:
        pot_pico = 0

      with c1:
        st.metric("Consumo diario (kWh-día)", round(cons_prom,1))
        st.metric("Consumo perfil de carga (kWh)",round(cons_prom*consumoHSP,1))
        st.metric("Potencia pico a instalar (kWp)",pot_pico)

      with st.container(border=True):
        paneles = carga_paneles()
        panel_selec = st.selectbox("Seleccione un panel", list(paneles.keys()))
        panel_data = paneles[panel_selec]
        cw, cx, cy, cz = st.columns(4)
        paneles_f1 = round(1000*pot_pico/panel_data['Pmax'],1)
        cx.metric("Paneles a instalar", paneles_f1)
        gen_mensual = round(panel_data['Pmax']*HorasPico*paneles_f1*30/1e6,1)
        cy.metric("Generación (MWh-mes)",gen_mensual, str(round(-0.112378*gen_mensual,2))+" Ton CO₂/MWh",delta_color="inverse")
        st.markdown('<h5 style="font-size: 14px;">Área disponible (m<sup style=font-size:.8em;>2 </sup>) :</h5>', unsafe_allow_html=True)

        cc, cd = st.columns([3, 1])
        with cc:
          area = st.text_input("",label_visibility="collapsed")
        with cd:
          calc_PSFV = st.button("Calcular", use_container_width=True)

        c5, c6, c7, c8 = st.columns(4)
        if calc_PSFV:
            cant_pan_teo = float(area)/panel_data['Area']
            c5.metric("Cantidad de Paneles max", round(cant_pan_teo,2))
            inclinacion = round(3.7 + (0.69 * st.session_state.lat + 4),0)
            c6.metric("Inclinación Optima (°)",inclinacion)
            alt_pi = -math.sin(inclinacion)*panel_data['Altura']*180/math.pi
            c7.metric("Altura Panel Inclinado", round(alt_pi,2))
            dist_pan = 0.21/(math.atan(61 - st.session_state.lat))
            c8.metric("Distancia entre paneles (m):",round(dist_pan,2))
            area_capt = cant_pan_teo*panel_data['Area']
            f_forma = (panel_data['Vmp']*panel_data['Imp'])/(panel_data['Voc']*panel_data['Isc'])
            c6.metric("Factor de Forma", round(f_forma,2))
            Pmax_pan = panel_data['Vmp']*panel_data['Imp']
            c7.metric("Potencia Max/panel", round(Pmax_pan,2))

      with st.container(border=True):
        inversores = carga_inversores()
        inversor_selec = st.selectbox("Seleccione un inversor", list(inversores.keys()))
        set_inv = inversores[inversor_selec]
        c9, c10, c11 = st.columns(3)
        cant_inversores = c9.number_input("Cantidad de inversores", value=1, placeholder="",key='c_inv', step=1, min_value=1)
        pan_str = c10.number_input("Paneles por string", value=1, placeholder="", step=1, min_value=1)
        str_inv = c11.number_input("Strings por inversor", value=1, placeholder="", step=1, min_value=1)
        pan_inv = pan_str*str_inv
        c9.metric("Paneles por inversor", pan_inv)
        pot_inv = pan_inv*panel_data['Pmax']/1000
        c10.metric("Potencia por inversor", round(pot_inv,1))
        iAC_max = set_inv['Poutmax']/(set_inv['VnomAC']*math.sqrt(3))
        c11.metric("Corriente Máxima AC (A)", round(iAC_max,2))
        carga_inv = round(pot_inv/set_inv["Pmax_kWp"]*100,1)
        progress1 = c9.empty()
        color = "#4caf50" if carga_inv <= 100 else "#ff4d4d"
        progress_bar1 = f"""
        <div style="width: 100%; text-align: left; margin-bottom: 10px;">
          <strong style="font-size: 14px;">Carga por inversor:</strong>
        </div>
        <div style="width: 95%; background-color: #e0e0e0; border-radius: 10px; height: 40px; position: relative;">
            <div style="width: {min(carga_inv, 100)}%; background-color: {color}; height: 100%; border-radius: 10px;">
            </div>
            <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: white; font-weight: bold;">
                {carga_inv}%
            </div>
        </div>
        <br>
        """
        progress1.markdown(progress_bar1, unsafe_allow_html=True)

        progress2 = c10.empty()
        lim_Vdc = round(panel_data['Voc']*pan_str,1)
        color2 = "#4caf50" if lim_Vdc <= set_inv['VmaxMPP'] else "#ff4d4d"
        progress_bar2 = f"""
        <div style="width: 100%; text-align: left; margin-bottom: 10px;">
          <strong style="font-size: 14px;">Límite de tensión DC Max:</strong>
        </div>
        <div style="width: 95%; background-color: #e0e0e0; border-radius: 10px; height: 40px; position: relative;">
            <div style="width: {min(100*lim_Vdc/set_inv['VmaxMPP'],100)}%; background-color: {color2}; height: 100%; border-radius: 10px;">
            </div>
            <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: white; font-weight: bold;">
                {lim_Vdc}
            </div>
        </div>
        <br>
        """
        progress2.markdown(progress_bar2, unsafe_allow_html=True)

        progress3 = c11.empty()
        lim_Idc = round(panel_data['Imp']*str_inv,2)
        color3 = "#4caf50" if lim_Idc <= set_inv['ImaxMPPT'] else "#ff4d4d"
        progress_bar3 = f"""
        <div style="width: 100%; text-align: left; margin-bottom: 10px;">
          <strong style="font-size: 14px;">Limite de Corriente DC Max: </strong>
        </div>
        <div style="width: 95%; background-color: #e0e0e0; border-radius: 10px; height: 40px; position: relative;">
            <div style="width: {min(100*lim_Idc/set_inv['ImaxMPPT'],100)}%; background-color: {color3}; height: 100%; border-radius: 10px;">
            </div>
            <div style="position: absolute; top: 50%; left: 50%; transform: translate(-50%, -50%); color: white; font-weight: bold;">
                {lim_Idc}
            </div>
        </div>
        <br>
        """
        progress3.markdown(progress_bar3, unsafe_allow_html=True)

      with st.container(border=True):
        c12, c13, c14, c15 = st.columns(4)
        pane_total = pan_inv * cant_inversores
        c12.metric("Cantidad de paneles total", round(pane_total,1))
        area_real = pane_total * panel_data['Area']
        c13.metric("Área de Captación real (m²)", round(area_real,2))
        pot_SFV = pane_total * panel_data['Pmax']/1000
        c14.metric("Potencia SFV (kW)", round(pot_SFV,1))
        energy_tot = pot_SFV * HorasPico * 30
        c15.metric("Energía generada (kWh-mes)", round(energy_tot,0), str(round(100*energy_tot/(cons_prom*30),2))+" % Ahorro")
        fig = generar_diagrama(cant_inversores, str_inv, pan_str)
        st.pyplot(fig)

    else:
      cons_prom = 0

if __name__ == "__main__":
    app()
