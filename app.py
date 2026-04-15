import streamlit as st
import requests
import pywincalc
import pandas as pd
import json
import plotly.graph_objects as go
import numpy as np
from igsdb_interaction import url_single_product, headers

# --- Page Setup ---
st.set_page_config(page_title="IGU Design Studio", layout="wide")

# --- Initialize Session State ---
if 'envelope_data' not in st.session_state:
    st.session_state.envelope_data = None
if 'pane_details' not in st.session_state:
    st.session_state.pane_details = None

# --- Data Fetching ---

@st.cache_data(ttl=3600)
def get_igsdb_summary():
    """Fetches the primary glazing product list from IGSDB."""
    url = "https://igsdb.lbl.gov/api/v1/products?type=glazing"
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to fetch IGSDB summary: {e}")
        return None

@st.cache_data(ttl=3600)
def get_detailed_product_data(product_id):
    """Fetches full spectral data for a selected IGSDB product."""
    url = url_single_product.format(id=product_id)
    try:
        response = requests.get(url, headers=headers, timeout=20)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        st.error(f"Failed to fetch detailed data for ID {product_id}: {e}")
        return None

def calculate_u(pane_details, total_w_inch, gas_mix_list):
    """Calculates U-factor for a specific width and gas mixture."""
    try:
        solid_layers = [pywincalc.parse_json(json.dumps(d)) for d in pane_details]
        # Sum thickness from metadata or default to 3mm
        glass_t_mm = sum([d.get('thickness', 3.0) for d in pane_details])
        glass_t_inch = glass_t_mm / 25.4
        
        # Calculate total gap in meters
        total_gap_m = (total_w_inch - glass_t_inch) * 0.0254
        if total_gap_m <= 0.0001: return None
        
        # Divide total gap space equally between panes
        individual_gap_m = total_gap_m / (len(pane_details) - 1)
        
        # Create gas mixture and gaps
        gas_obj = pywincalc.create_gas(gas_mix_list)
        gaps = [pywincalc.Layers.gap(thickness=individual_gap_m, gas=gas_obj) for _ in range(len(pane_details) - 1)]
        
        # Thermal simulation using NFRC winter defaults
        bsdf = pywincalc.BSDFHemisphere.create(pywincalc.BSDFBasisType.SMALL)
        system = pywincalc.GlazingSystem(solid_layers=solid_layers, gap_layers=gaps, bsdf_hemisphere=bsdf)
        
        return system.u() * 0.17611 # Metric to IP conversion
    except:
        return None

def main():
    st.title("🛡️ IGU Performance Design Studio")
    st.markdown("Precision modeling of multi-pane systems with dynamic performance mapping.")
    
    with st.spinner("Connecting to IGSDB..."):
        data = get_igsdb_summary()

    if not data: return
    items = data if isinstance(data, list) else data.get('results', [])
    df = pd.DataFrame(items)
    mfr_col, name_col, id_col = "manufacturer_name", "product_name", "product_id"
    df[name_col] = df[name_col].fillna(df.get('name', "Unknown"))
    df = df.dropna(subset=[mfr_col, name_col, id_col])

    # --- Sidebar Configuration ---
    st.sidebar.header("1. Construction")
    num_panes = st.sidebar.radio("Number of Panes", [2, 3], index=0)
    
    selected_panes_info = []
    mfr_list = sorted(df[mfr_col].unique())
    for i in range(num_panes):
        m_sel = st.sidebar.selectbox(f"Mfr {i+1}", mfr_list, key=f"mfr_{i}")
        p_sel = st.sidebar.selectbox(f"Product {i+1}", sorted(df[df[mfr_col] == m_sel][name_col].unique()), key=f"name_{i}")
        pid = df[(df[mfr_col] == m_sel) & (df[name_col] == p_sel)][id_col].iloc[0]
        selected_panes_info.append({"name": p_sel, "id": pid})

    st.sidebar.divider()
    st.sidebar.header("2. Gas Comparison")
    mix_choice = st.sidebar.selectbox("Base vs. Upgrade", ["Air / Argon", "Argon / Krypton"])
    
    if st.sidebar.button("🚀 Run Base Simulation", use_container_width=True):
        with st.spinner("Establishing performance boundaries..."):
            st.session_state.pane_details = [get_detailed_product_data(p['id']) for p in selected_panes_info]
            
            # Calculate fixed glass thickness
            glass_t_mm = sum([d.get('thickness', 3.0) for d in st.session_state.pane_details])
            glass_w = glass_t_mm / 25.4
            
            # Width sweep for plotting
            widths = np.linspace(glass_w + 0.1, 1.5, 30).tolist()
            
            # Map gas types
            if mix_choice == "Air / Argon":
                b_type, u_type = pywincalc.PredefinedGasType.AIR, pywincalc.PredefinedGasType.ARGON
            else:
                b_type, u_type = pywincalc.PredefinedGasType.ARGON, pywincalc.PredefinedGasType.KRYPTON

            # Calculate 0% and 100% boundary lines
            u_0 = [calculate_u(st.session_state.pane_details, w, [[1.0, b_type]]) for w in widths]
            u_100 = [calculate_u(st.session_state.pane_details, w, [[1.0, u_type]]) for w in widths]
            
            # Store everything in session state
            st.session_state.envelope_data = {
                "widths": widths,
                "u_0": u_0, 
                "u_100": u_100,
                "mix": mix_choice,
                "glass_t": glass_w
            }

    # --- Display Area ---
    if st.session_state.envelope_data and "glass_t" in st.session_state.envelope_data:
        ed = st.session_state.envelope_data
        
        # Derive gas types and names for reactive logic
        if ed["mix"] == "Air / Argon":
            base_type, upgrade_type = pywincalc.PredefinedGasType.AIR, pywincalc.PredefinedGasType.ARGON
            base_name, upgrade_name = "Air", "Argon"
        else:
            base_type, upgrade_type = pywincalc.PredefinedGasType.ARGON, pywincalc.PredefinedGasType.KRYPTON
            base_name, upgrade_name = "Argon", "Krypton"

        st.divider()
        st.subheader("🎯 Design Point Specifications")
        
        # Target Inputs (Request #1)
        col_in1, col_in2 = st.columns(2)
        with col_in1:
            target_w = st.number_input("Target Total IGU Width (in)", 
                                     min_value=float(ed["glass_t"] + 0.01), 
                                     max_value=3.0, value=1.0, step=0.0625)
        with col_in2:
            target_conc_pct = st.number_input(f"Target % {upgrade_name} Concentration", 0, 100, 90)
            target_conc = target_conc_pct / 100.0

        # Calculate Individual Gap Width (Request #2)
        num_gaps = len(st.session_state.pane_details) - 1
        individual_gap_in = (target_w - ed["glass_t"]) / num_gaps

        with st.spinner("Calculating target metrics..."):
            current_mix = [[target_conc, upgrade_type], [1.0 - target_conc, base_type]]
            
            # Calculate live trace for the line
            u_live = [calculate_u(st.session_state.pane_details, w, current_mix) for w in ed["widths"]]
            # Calculate exact target point
            target_u = calculate_u(st.session_state.pane_details, target_w, current_mix)

            # --- Plotly Visualization ---
            fig = go.Figure()

            # Base Boundary (0%)
            fig.add_trace(go.Scatter(x=ed["widths"], y=ed["u_0"], mode='lines', name=f"100% {base_name}", line=dict(color='rgba(255, 0, 0, 0.4)', width=1.5)))

            # Upgrade Boundary (100%)
            fig.add_trace(go.Scatter(x=ed["widths"], y=ed["u_100"], mode='lines', name=f"100% {upgrade_name}", fill='tonexty', fillcolor='rgba(0, 200, 100, 0.1)', line=dict(color='rgba(0, 150, 70, 0.4)', width=1.5)))

            # Reactive Live Trace (Slider-driven)
            fig.add_trace(go.Scatter(x=ed["widths"], y=u_live, mode='lines', name=f"{target_conc_pct}% {upgrade_name} Trace", line=dict(color='black', width=3)))

            # Target Point Marker (Request #1)
            if target_u:
                fig.add_trace(go.Scatter(
                    x=[target_w], y=[target_u],
                    mode='markers', name="Design Target",
                    marker=dict(color='orange', size=12, symbol='diamond', line=dict(width=2, color='DarkSlateGrey')),
                    hovertemplate='<b>Design Point</b><br>Width: %{x}"<br>U-Factor: %{y:.4f}'
                ))

            # Dynamic Y-Axis Scaling (Request #3)
            # Filter None values and find min/max for perfect framing
            all_u = [v for v in (ed["u_0"] + ed["u_100"] + u_live + ([target_u] if target_u else [])) if v is not None]
            if all_u:
                y_min, y_max = min(all_u), max(all_u)
                y_pad = (y_max - y_min) * 0.15
                fig.update_layout(yaxis=dict(range=[y_min - y_pad, y_max + y_pad]))

            fig.update_layout(
                title=f"IGU Performance Envelope ({num_panes}-Pane)",
                xaxis_title="Total IGU Width (inches)",
                yaxis_title="U-Factor (Btu/h·ft²·°F)",
                template="plotly_white",
                hovermode="x unified",
                height=550
            )
            st.plotly_chart(fig, use_container_width=True)

        # Result Metrics (Request #2)
        st.subheader("📊 Simulation Data")
        res1, res2, res3 = st.columns(3)
        res1.metric("Calculated U-Factor", f"{target_u:.4f}" if target_u else "N/A")
        res2.metric("Individual Gap Width", f"{individual_gap_in:.4f}\"")
        res3.metric("Glass Stack Thickness", f"{ed['glass_t']:.3f}\"")
        
        st.info(f"Target Construction: **{target_w}\"** total width with **{individual_gap_in:.4f}\"** individual gaps and **{target_conc_pct}% {upgrade_name}** fill.")

    elif st.session_state.envelope_data and "glass_t" not in st.session_state.envelope_data:
        st.warning("🔄 Session data is outdated. Please click 'Run Base Simulation' again to update the model.")

if __name__ == "__main__":
    main()