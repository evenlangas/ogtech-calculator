
import streamlit as st
import pandas as pd
import numpy as np

st.set_page_config(page_title="O₂ TCO-kalkulator", layout="wide")

NM3_TO_KG = 1.429

@st.cache_data
def load_default_models():
    df = pd.read_csv("models.csv")
    return df

def detect_series(name:str) -> str:
    s = str(name)
    if "OxyGen" in s:
        return "OxyGen"
    if "VSA" in s:
        return "VSA"
    return "Other"

st.title("O₂ TCO-kalkulator (uten Excel)")

with st.sidebar:
    st.header("Data-kilde")
    use_default = st.radio("Velg datakilde", ["Innebygd (models.csv)", "Last opp CSV"], index=0, help="CSV-filen må ha kolonner: Model, Series, Tech, Capacity_kg_per_h, SpecificEnergy_kWh_per_kg, CAPEX_NOK")
    if use_default == "Innebygd (models.csv)":
        models = load_default_models()
    else:
        up = st.file_uploader("Last opp modell-CSV", type=["csv"])
        if up is not None:
            models = pd.read_csv(up)
        else:
            st.stop()

    st.header("Økonomi & drift")
    util_pct = st.number_input("Utnyttelse (% av året)", min_value=0.0, max_value=100.0, value=80.0, step=1.0)
    hours = 8760 * (util_pct/100)
    power_src = st.selectbox("Kraftkilde", ["Landstrøm", "Diesel strøm"])
    price_grid = st.number_input("Elpris – Landstrøm (NOK/kWh)", min_value=0.0, value=1.20, step=0.05)
    price_diesel = st.number_input("Elpris – Diesel strøm (NOK/kWh)", min_value=0.0, value=2.50, step=0.05)
    elec_price = price_grid if power_src=="Landstrøm" else price_diesel

    lifetime = st.number_input("Levetid (år)", min_value=1, value=10, step=1)
    wacc_pct = st.number_input("WACC / kalkulasjonsrente (%)", min_value=0.0, value=8.0, step=0.5)
    r = wacc_pct/100.0
    crf = (r*(1+r)**lifetime)/(((1+r)**lifetime)-1) if r>0 else 1.0/lifetime
    genset_capex = st.number_input("Diesel genset CAPEX (NOK) – valgfritt", min_value=0.0, value=0.0, step=10000.0)

    st.header("Service-satser")
    psa_service = st.number_input("PSA service % av CAPEX", min_value=0.0, value=0.0065, step=0.0005, format="%.4f")
    vsa_service = st.number_input("VSA service % av CAPEX", min_value=0.0, value=0.0150, step=0.0005, format="%.4f")

st.subheader("Behov")

demand_method = st.radio("Metode for behov", ["Lik per linje", "Forskjellig per linje"], horizontal=True)
if demand_method == "Lik per linje":
    max_per_line = st.number_input("Max oksygenbehov per linje (kg/h)", min_value=0.0, value=100.0, step=10.0)
    n_lines = st.number_input("Antall produksjonslinjer", min_value=1, value=1, step=1)
    total_kgph = max_per_line * n_lines
    per_line = None
else:
    st.caption("Fyll inn kg/h per linje. Tomme rader ignoreres.")
    n_default = 5
    template = pd.DataFrame({"Linje": list(range(1, n_default+1)), "Behov_kg_per_h": [np.nan]*n_default})
    edited = st.data_editor(template, num_rows="dynamic", use_container_width=True, key="per_line_editor")
    per_line = edited["Behov_kg_per_h"].dropna()
    total_kgph = float(per_line.sum()) if not per_line.empty else 0.0

st.info(f"**Totalbehov:** {total_kgph:,.2f} kg/h  •  **Årstimer:** {hours:,.0f}  •  **Elpris:** {elec_price:.2f} NOK/kWh  •  **CRF:** {crf:.4f}")

# Sanity check for models
required_cols = {"Model","Series","Tech","Capacity_kg_per_h","SpecificEnergy_kWh_per_kg","CAPEX_NOK"}
if not required_cols.issubset(set(models.columns)):
    st.error(f"Mangler kolonner i data: {sorted(list(required_cols - set(models.columns)))}")
    st.stop()

# Calculation
annual_kg = total_kgph * hours

def service_rate_for(row):
    tech = str(row["Tech"]).upper()
    if "PSA" in tech:
        return psa_service
    if "VSA" in tech:
        return vsa_service
    return psa_service

def compute_table(df_models):
    rows = []
    for _, m in df_models.iterrows():
        cap_kgph = float(m["Capacity_kg_per_h"])
        if cap_kgph <= 0 or total_kgph <= 0 or annual_kg <= 0:
            continue
        units = int(np.ceil(total_kgph / cap_kgph))
        capex_total = units * float(m["CAPEX_NOK"])
        s_rate = service_rate_for(m)
        annual_service = capex_total * s_rate
        spec_e = float(m["SpecificEnergy_kWh_per_kg"])
        energy_kwh = annual_kg * spec_e
        energy_cost = energy_kwh * elec_price
        annualized_capex = (capex_total + (genset_capex if power_src=="Diesel strøm" else 0.0)) * crf
        opex_annual = annual_service + energy_cost
        totex_annual = annualized_capex + opex_annual
        cost_per_kg = totex_annual / annual_kg
        rows.append({
            "Model": m["Model"],
            "Series": m["Series"],
            "Tech": m["Tech"],
            "Units": units,
            "Unit cap (kg/h)": cap_kgph,
            "CAPEX total (NOK)": capex_total,
            "Service rate": s_rate,
            "Service/yr (NOK)": annual_service,
            "Specific energy (kWh/kg)": spec_e,
            "Energy/yr (kWh)": energy_kwh,
            "Energy cost/yr (NOK)": energy_cost,
            "Annualized CAPEX (NOK/yr)": annualized_capex,
            "OPEX/yr (NOK)": opex_annual,
            "TOTEX/yr (NOK)": totex_annual,
            "Cost (NOK/kg)": cost_per_kg,
        })
    res = pd.DataFrame(rows)
    if res.empty:
        return res, None, None, None
    res = res.sort_values("Cost (NOK/kg)", ascending=True).reset_index(drop=True)
    best = res.iloc[0]
    oxy = res[res["Series"]=="OxyGen"]
    best_oxy = oxy.iloc[0] if not oxy.empty else None
    return res, best, best_oxy, annual_kg

table, best, best_oxy, annual_kg = compute_table(models)

if table is None or table.empty:
    st.warning("Ingen beregninger – sjekk at data inneholder gyldige kapasiteter og at totalbehov > 0.")
    st.stop()

col1, col2, col3, col4 = st.columns(4)
col1.metric("Beste totalt – modell", best["Model"])
col2.metric("NOK/kg (beste)", f"{best['Cost (NOK/kg)']:.4f}")
col3.metric("CAPEX (beste)", f"{best['CAPEX total (NOK)']:,.0f}")
col4.metric("OPEX/år (beste)", f"{best['OPEX/yr (NOK)']:,.0f}")

if best_oxy is not None:
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Kun OxyGen – modell", best_oxy["Model"])
    col2.metric("NOK/kg (OxyGen)", f"{best_oxy['Cost (NOK/kg)']:.4f}")
    col3.metric("CAPEX (OxyGen)", f"{best_oxy['CAPEX total (NOK)']:,.0f}")
    col4.metric("OPEX/år (OxyGen)", f"{best_oxy['OPEX/yr (NOK)']:,.0f}")

    # ROI vs high CAPEX
    cap_b = float(best["CAPEX total (NOK)"])
    cap_o = float(best_oxy["CAPEX total (NOK)"])
    opex_b = float(best["OPEX/yr (NOK)"])
    opex_o = float(best_oxy["OPEX/yr (NOK)"])
    high_capex_is_best = cap_b >= cap_o
    delta_capex = abs(cap_b - cap_o)
    opex_save = (opex_o - opex_b) if high_capex_is_best else (opex_b - opex_o)
    roi = (opex_save / delta_capex) if delta_capex>0 else None
    payback = (delta_capex / opex_save) if opex_save>0 else None
    st.subheader("ROI vs alternativ")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("ΔCAPEX (NOK)", f"{delta_capex:,.0f}")
    c2.metric("Årlig OPEX-besparelse", f"{opex_save:,.0f}")
    c3.metric("ROI", f"{roi:.2%}" if roi is not None else "-")
    c4.metric("Nedbetaling (år)", f"{payback:.2f}" if payback is not None else "-")

st.subheader("Alle alternativer (sortert på NOK/kg)")
show_cols = [
    "Model","Series","Tech","Units",
    "Unit cap (kg/h)","Specific energy (kWh/kg)",
    "CAPEX total (NOK)","Service/yr (NOK)","Energy cost/yr (NOK)",
    "Annualized CAPEX (NOK/yr)","OPEX/yr (NOK)","TOTEX/yr (NOK)","Cost (NOK/kg)"
]
st.dataframe(table[show_cols], use_container_width=True)

# Downloads
st.subheader("Eksport")
csv = table.to_csv(index=False).encode("utf-8")
st.download_button("Last ned resultat-tabell (CSV)", data=csv, file_name="o2_tco_resultater.csv", mime="text/csv")
