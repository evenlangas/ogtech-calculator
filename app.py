# -*- coding: utf-8 -*-
"""
O2 TCO Calculator – OGP vs OGP+ (flåte / oppdrett)
--------------------------------------------------
Kjør lokalt:
  pip install -r requirements.txt
  streamlit run o2_tco_ogp_ogpplus_app.py

Deploy (Streamlit Community Cloud):
  - Legg denne filen + requirements.txt i et GitHub-repo
  - Sett "Main file path" til: o2_tco_ogp_ogpplus_app.py

NB:
- Dette er en beslutningsstøtte, ikke en tilbuds-/garanti-beregning.
- Tallene for spesifikk energibruk (kWh/kg O2) er lagt inn iht. brukerforutsetning:
    OGP  = 0,90 kWh/kg
    OGP+ = 0,39 kWh/kg
- CAPEX-verdier er forhåndsutfylt med prisgrunnlag fra vedlagte filer (kan overstyres i appen).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Dict, List, Tuple

import numpy as np
import pandas as pd
import streamlit as st


# -----------------------------
# Hjelpefunksjoner
# -----------------------------
def ceil_div(a: float, b: float) -> int:
    return int(math.ceil(a / b)) if b > 0 else 0


def fmt_nok(x: float) -> str:
    # Norsk format (mellomrom som tusenskiller)
    try:
        return f"{x:,.0f} NOK".replace(",", " ")
    except Exception:
        return f"{x} NOK"


def fmt_num(x: float, decimals: int = 0) -> str:
    try:
        s = f"{x:,.{decimals}f}"
        return s.replace(",", " ").replace(".", ",")
    except Exception:
        return str(x)


def npv_of_annuity(annual_cost: float, years: int, discount_rate: float) -> float:
    """NPV av konstant årlig kostnad med diskonteringsrente."""
    if years <= 0:
        return 0.0
    r = discount_rate
    if r <= 0:
        return annual_cost * years
    # Nåverdi av annuitet
    return annual_cost * (1 - (1 + r) ** (-years)) / r


@dataclass
class ModuleOption:
    name: str
    capacity_kgph: float
    capex_nok: float


def best_combo_min_capex(demand_kgph: float, options: List[ModuleOption], oversize_limit_factor: float = 1.5) -> Tuple[Dict[str, int], float, float]:
    """
    Finn kombinasjon av moduler som:
      - møter demand_kgph (sum kapasitet >= demand)
      - minimerer CAPEX
    Brute force innenfor en rimelig søkegrense.

    oversize_limit_factor: hvor mye over behov vi tillater i søket (for å holde søket lite og realistisk).
    """
    if demand_kgph <= 0:
        return {}, 0.0, 0.0
    if not options:
        return {}, 0.0, 0.0

    # Sorter etter kapasitet (størst først) for mer stabil oppførsel
    opts = sorted(options, key=lambda o: o.capacity_kgph, reverse=True)

    max_capacity = max(o.capacity_kgph for o in opts)
    # Maks antall av største modul for å nå (demand * oversize_limit_factor)
    cap_target = demand_kgph * oversize_limit_factor
    max_n_big = ceil_div(cap_target, max_capacity) + 1  # litt buffer

    best = None  # (capex, capacity, counts dict)

    # For små lister (5-6 moduler) kan vi brute-force ved å sette en øvre grense per modul
    # Øvre grense per modul: basert på minste kapasitet
    min_capacity = min(o.capacity_kgph for o in opts)
    max_total_units = ceil_div(cap_target, min_capacity) + 2

    # Lag grenser per modul (konservativt)
    bounds = []
    for o in opts:
        b = min(max_total_units, ceil_div(cap_target, o.capacity_kgph) + 2)
        bounds.append(b)

    # Rekursiv bruteforce
    counts = [0] * len(opts)

    def rec(i: int, cap_sum: float, capex_sum: float):
        nonlocal best
        # Pruning: hvis capex allerede dårligere enn best, stopp
        if best is not None and capex_sum >= best[0]:
            return

        if i == len(opts):
            if cap_sum >= demand_kgph and cap_sum <= cap_target:
                if (best is None) or (capex_sum < best[0]) or (capex_sum == best[0] and cap_sum < best[1]):
                    best = (capex_sum, cap_sum, counts.copy())
            return

        # Hvis vi allerede har nok kapasitet, kan vi sette resten til 0
        if cap_sum >= demand_kgph:
            # Vi ønsker minst CAPEX => sett resten til 0
            # Men sjekk oversize-grense
            if cap_sum <= cap_target:
                if (best is None) or (capex_sum < best[0]) or (capex_sum == best[0] and cap_sum < best[1]):
                    best = (capex_sum, cap_sum, counts.copy())
            return

        # Pruning: maks mulig kapasitet hvis vi fyller resten med maks, eller min?
        # Her holder vi det enkelt.

        for n in range(bounds[i] + 1):
            counts[i] = n
            rec(
                i + 1,
                cap_sum + n * opts[i].capacity_kgph,
                capex_sum + n * opts[i].capex_nok,
            )
        counts[i] = 0

    rec(0, 0.0, 0.0)

    if best is None:
        # Hvis vi ikke fant innen cap_target, øk target og gjør en enkel greedy: største først
        cap_sum = 0.0
        capex_sum = 0.0
        result = {o.name: 0 for o in opts}
        for o in opts:
            if cap_sum >= demand_kgph:
                break
            n = ceil_div(demand_kgph - cap_sum, o.capacity_kgph)
            result[o.name] += n
            cap_sum += n * o.capacity_kgph
            capex_sum += n * o.capex_nok
        return {k: v for k, v in result.items() if v > 0}, cap_sum, capex_sum

    capex_sum, cap_sum, counts_vec = best
    result = {opts[i].name: int(counts_vec[i]) for i in range(len(opts)) if counts_vec[i] > 0}
    return result, cap_sum, capex_sum


def build_cashflow_table(years: int, capex: float, annual_opex: float, discount_rate: float) -> pd.DataFrame:
    rows = []
    for y in range(0, years + 1):
        if y == 0:
            cost = capex
        else:
            cost = annual_opex
        disc = (1 + discount_rate) ** (-y) if discount_rate > 0 else 1.0
        rows.append(
            {
                "År": y,
                "Kostnad (NOK)": cost,
                "Diskonteringsfaktor": disc,
                "Nåverdi (NOK)": cost * disc,
            }
        )
    df = pd.DataFrame(rows)
    df["Akk. nåverdi (NOK)"] = df["Nåverdi (NOK)"].cumsum()
    df["Akk. kostnad (NOK)"] = df["Kostnad (NOK)"].cumsum()
    return df


# -----------------------------
# Standarddata (kan overstyres i app)
# -----------------------------
DEFAULTS = {
    "spec_kwh_per_kg_ogp": 0.90,
    "spec_kwh_per_kg_ogpplus": 0.39,  # bruker skrev OGV+; her kalt OGP+ i UI
    "demand_min": 500,
    "demand_max": 1200,
    "demand_default": 800,
    "hours_per_year_default": 8000,
    "years_default": 10,
    "discount_default": 0.08,
    "maint_pct_default": 0.03,
    "power_price_default": 1.20,   # NOK/kWh
    "diesel_price_default": 22.0,  # NOK/l
    "genset_l_per_kwh_default": 0.27,  # l/kWh
    "fleet_default": 1,
}

# OGP – basert på tilbud 5447162 (komplett anlegg: 6 008 475 NOK for 2×OGP150)
# Vi lager et "per modul"-grunnlag for enkel skalering.
OGP_O2_CAPACITY_PER_MODULE = 200.0  # kg/h (antatt ~OGP150 @ 93% ~200 kg/h)
OGP_CAPEX_GENERATOR_PER_MODULE = 2_194_350.0
OGP_CAPEX_BOP_PER_MODULE = 809_887.5  # (Total 6 008 475 - 2×2 194 350) / 2
OGP_CAPEX_COMPLETE_PER_MODULE = OGP_CAPEX_GENERATOR_PER_MODULE + OGP_CAPEX_BOP_PER_MODULE

# OGP+ – basert på "Ramme under arbeid.xlsx" (Pris komplett anlegg i EUR, konvertert til NOK).
# I appen kan brukeren endre både EUR/NOK og priser.
OGPPLUS_DEFAULT_EUR_NOK = 11.69
OGPPLUS_OPTIONS_EUR = [
    ("OGP+ 80", 105.0, 385_490.0),
    ("OGP+ 105", 138.0, 411_250.0),
    ("OGP+ 160", 210.0, 548_798.0),
    ("OGP+ 270", 355.0, 838_112.0),
    ("OGP+ 400", 525.0, 1_050_000.0),
]


# -----------------------------
# App
# -----------------------------
st.set_page_config(page_title="O2 TCO – OGP vs OGP+", layout="wide")

st.title("O2 TCO-kalkulator – OGP vs OGP+")
st.caption(
    "Beslutningsstøtte for oppdrett (typisk behov 500–1200 kg/h). "
    "Sammenligner CAPEX og OPEX for landstrøm og dieseldrift."
)

with st.sidebar:
    st.header("Inndata")

    fleet_n = st.number_input("Antall anlegg / lokasjoner i flåten", min_value=1, max_value=50, value=DEFAULTS["fleet_default"], step=1)

    demand = st.slider(
        "Oksygenbehov (kg/h) per lokasjon",
        min_value=DEFAULTS["demand_min"],
        max_value=DEFAULTS["demand_max"],
        value=DEFAULTS["demand_default"],
        step=10,
    )

    hours_per_year = st.number_input(
        "Driftstimer per år (h/år)",
        min_value=0,
        max_value=8760,
        value=DEFAULTS["hours_per_year_default"],
        step=100,
        help="Bruk f.eks. 8000 for høy utnyttelse, eller 8760 for kontinuerlig drift.",
    )

    years = st.slider("Analysehorisont (år)", min_value=1, max_value=20, value=DEFAULTS["years_default"])
    discount_rate = st.number_input("Diskonteringsrente (%)", min_value=0.0, max_value=20.0, value=DEFAULTS["discount_default"] * 100, step=0.5) / 100.0

    st.divider()
    st.subheader("Energipriser")
    power_price = st.number_input("Landstrøm (NOK/kWh)", min_value=0.0, value=DEFAULTS["power_price_default"], step=0.05)

    diesel_price = st.number_input("Diesel (NOK/liter)", min_value=0.0, value=DEFAULTS["diesel_price_default"], step=0.5)
    genset_l_per_kwh = st.number_input("Genset forbruk (liter/kWh)", min_value=0.05, max_value=1.0, value=DEFAULTS["genset_l_per_kwh_default"], step=0.01)

    st.divider()
    st.subheader("Teknologiantagelser")
    spec_ogp = st.number_input("OGP spesifikk energibruk (kWh/kg O₂)", min_value=0.0, value=DEFAULTS["spec_kwh_per_kg_ogp"], step=0.01)
    spec_ogpplus = st.number_input("OGP+ spesifikk energibruk (kWh/kg O₂)", min_value=0.0, value=DEFAULTS["spec_kwh_per_kg_ogpplus"], step=0.01)

    maint_pct = st.number_input("Årlig vedlikehold (% av CAPEX)", min_value=0.0, max_value=20.0, value=DEFAULTS["maint_pct_default"] * 100, step=0.5) / 100.0

    st.divider()
    st.subheader("CAPEX – OGP")
    ogp_capacity = st.number_input("Kapasitet pr OGP-modul (kg/h)", min_value=10.0, value=OGP_O2_CAPACITY_PER_MODULE, step=10.0)

    ogp_capex_generator = st.number_input("OGP: CAPEX generator pr modul (NOK)", min_value=0.0, value=OGP_CAPEX_GENERATOR_PER_MODULE, step=50_000.0)
    ogp_capex_bop = st.number_input("OGP: CAPEX støtteutstyr pr modul (NOK)", min_value=0.0, value=OGP_CAPEX_BOP_PER_MODULE, step=50_000.0)

    st.divider()
    st.subheader("CAPEX – OGP+ (modulbibliotek)")
    eur_nok = st.number_input("EUR/NOK for OGP+ prisgrunnlag", min_value=0.0, value=OGPPLUS_DEFAULT_EUR_NOK, step=0.05)

    # Redigerbar tabell for OGP+ moduler
    ogpplus_df = pd.DataFrame(
        [{
            "Modul": name,
            "Kapasitet (kg/h)": cap,
            "Pris (EUR)": eur,
        } for (name, cap, eur) in OGPPLUS_OPTIONS_EUR]
    )
    ogpplus_df["Pris (NOK)"] = ogpplus_df["Pris (EUR)"] * eur_nok

    st.caption("Her kan du justere kapasitet og CAPEX pr modul for OGP+.")
    ogpplus_df_edit = st.data_editor(
        ogpplus_df[["Modul", "Kapasitet (kg/h)", "Pris (NOK)"]],
        hide_index=True,
        use_container_width=True,
        column_config={
            "Kapasitet (kg/h)": st.column_config.NumberColumn(min_value=10.0, step=1.0),
            "Pris (NOK)": st.column_config.NumberColumn(min_value=0.0, step=50_000.0, format="%.0f"),
        },
    )

# -----------------------------
# Beregninger
# -----------------------------
hours_per_year = float(hours_per_year)
demand = float(demand)
fleet_n = int(fleet_n)

annual_o2_kg_per_site = demand * hours_per_year
annual_o2_kg_fleet = annual_o2_kg_per_site * fleet_n

# Energi
annual_kwh_ogp_site = annual_o2_kg_per_site * spec_ogp
annual_kwh_ogpplus_site = annual_o2_kg_per_site * spec_ogpplus

diesel_cost_per_kwh = diesel_price * genset_l_per_kwh

annual_energy_cost_ogp_land_site = annual_kwh_ogp_site * power_price
annual_energy_cost_ogp_diesel_site = annual_kwh_ogp_site * diesel_cost_per_kwh

annual_energy_cost_ogpplus_land_site = annual_kwh_ogpplus_site * power_price
annual_energy_cost_ogpplus_diesel_site = annual_kwh_ogpplus_site * diesel_cost_per_kwh

# OGP CAPEX (moduler)
ogp_modules_needed = ceil_div(demand, ogp_capacity)
ogp_installed_capacity = ogp_modules_needed * ogp_capacity
ogp_capex_per_module_complete = ogp_capex_generator + ogp_capex_bop
ogp_capex_site = ogp_modules_needed * ogp_capex_per_module_complete

# OGP+ CAPEX (optimal kombinasjon)
ogpplus_options = []
for _, row in ogpplus_df_edit.iterrows():
    name = str(row["Modul"])
    cap = float(row["Kapasitet (kg/h)"])
    price = float(row["Pris (NOK)"])
    if cap > 0 and price >= 0:
        ogpplus_options.append(ModuleOption(name=name, capacity_kgph=cap, capex_nok=price))

ogpplus_counts, ogpplus_installed_capacity, ogpplus_capex_site = best_combo_min_capex(demand, ogpplus_options, oversize_limit_factor=1.6)

# Vedlikehold
annual_maint_ogp_site = ogp_capex_site * maint_pct
annual_maint_ogpplus_site = ogpplus_capex_site * maint_pct

# Total OPEX per scenario
annual_opex_ogp_land_site = annual_energy_cost_ogp_land_site + annual_maint_ogp_site
annual_opex_ogp_diesel_site = annual_energy_cost_ogp_diesel_site + annual_maint_ogp_site

annual_opex_ogpplus_land_site = annual_energy_cost_ogpplus_land_site + annual_maint_ogpplus_site
annual_opex_ogpplus_diesel_site = annual_energy_cost_ogpplus_diesel_site + annual_maint_ogpplus_site

# Skaler til flåte
ogp_capex_fleet = ogp_capex_site * fleet_n
ogpplus_capex_fleet = ogpplus_capex_site * fleet_n

annual_opex_ogp_land_fleet = annual_opex_ogp_land_site * fleet_n
annual_opex_ogp_diesel_fleet = annual_opex_ogp_diesel_site * fleet_n
annual_opex_ogpplus_land_fleet = annual_opex_ogpplus_land_site * fleet_n
annual_opex_ogpplus_diesel_fleet = annual_opex_ogpplus_diesel_site * fleet_n

# NPV
npv_ogp_land = ogp_capex_fleet + npv_of_annuity(annual_opex_ogp_land_fleet, years, discount_rate)
npv_ogp_diesel = ogp_capex_fleet + npv_of_annuity(annual_opex_ogp_diesel_fleet, years, discount_rate)

npv_ogpplus_land = ogpplus_capex_fleet + npv_of_annuity(annual_opex_ogpplus_land_fleet, years, discount_rate)
npv_ogpplus_diesel = ogpplus_capex_fleet + npv_of_annuity(annual_opex_ogpplus_diesel_fleet, years, discount_rate)

# Payback (diesel som default scenario)
delta_capex = ogpplus_capex_fleet - ogp_capex_fleet
delta_annual_opex_diesel = annual_opex_ogp_diesel_fleet - annual_opex_ogpplus_diesel_fleet  # positiv => OGP+ sparer penger årlig
payback_years = None
if delta_capex > 0 and delta_annual_opex_diesel > 0:
    payback_years = delta_capex / delta_annual_opex_diesel

# -----------------------------
# UI – resultater
# -----------------------------
col1, col2 = st.columns([1, 1], gap="large")

with col1:
    st.subheader("Dimensjonering per lokasjon")
    st.write("**Inndata:**", f"{fmt_num(demand,0)} kg/h, {fmt_num(hours_per_year,0)} h/år")

    dim_rows = [
        {
            "Teknologi": "OGP",
            "Moduler": ogp_modules_needed,
            "Installert kapasitet (kg/h)": ogp_installed_capacity,
            "CAPEX per lokasjon (NOK)": ogp_capex_site,
        },
        {
            "Teknologi": "OGP+",
            "Moduler": ", ".join([f"{k}×{v}" for k, v in ogpplus_counts.items()]) if ogpplus_counts else "—",
            "Installert kapasitet (kg/h)": ogpplus_installed_capacity,
            "CAPEX per lokasjon (NOK)": ogpplus_capex_site,
        },
    ]
    dim_df = pd.DataFrame(dim_rows)
    st.dataframe(
        dim_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Installert kapasitet (kg/h)": st.column_config.NumberColumn(format="%.0f"),
            "CAPEX per lokasjon (NOK)": st.column_config.NumberColumn(format="%.0f"),
        },
    )

    st.subheader("Energibehov per lokasjon")
    power_ogp_kw = demand * spec_ogp
    power_ogpplus_kw = demand * spec_ogpplus

    energy_df = pd.DataFrame(
        [
            {"Teknologi": "OGP", "Snitt effekt (kW)": power_ogp_kw, "Årlig energi (kWh)": annual_kwh_ogp_site},
            {"Teknologi": "OGP+", "Snitt effekt (kW)": power_ogpplus_kw, "Årlig energi (kWh)": annual_kwh_ogpplus_site},
        ]
    )
    st.dataframe(
        energy_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Snitt effekt (kW)": st.column_config.NumberColumn(format="%.1f"),
            "Årlig energi (kWh)": st.column_config.NumberColumn(format="%.0f"),
        },
    )

with col2:
    st.subheader("Kostnader – flåte (sum)")
    st.write("**Flåtestørrelse:**", f"{fleet_n} lokasjon(er)")

    summary_rows = [
        {
            "Teknologi": "OGP",
            "CAPEX (NOK)": ogp_capex_fleet,
            "Årlig OPEX (land) (NOK/år)": annual_opex_ogp_land_fleet,
            "Årlig OPEX (diesel) (NOK/år)": annual_opex_ogp_diesel_fleet,
            "NPV land (NOK)": npv_ogp_land,
            "NPV diesel (NOK)": npv_ogp_diesel,
        },
        {
            "Teknologi": "OGP+",
            "CAPEX (NOK)": ogpplus_capex_fleet,
            "Årlig OPEX (land) (NOK/år)": annual_opex_ogpplus_land_fleet,
            "Årlig OPEX (diesel) (NOK/år)": annual_opex_ogpplus_diesel_fleet,
            "NPV land (NOK)": npv_ogpplus_land,
            "NPV diesel (NOK)": npv_ogpplus_diesel,
        },
    ]
    summary_df = pd.DataFrame(summary_rows)
    st.dataframe(
        summary_df,
        use_container_width=True,
        hide_index=True,
        column_config={c: st.column_config.NumberColumn(format="%.0f") for c in summary_df.columns if c != "Teknologi"},
    )

    st.subheader("Diesel-scenario (mest sannsynlig)")
    if payback_years is None:
        st.info(
            "Payback er ikke beregnet (enten er OGP+ ikke dyrere i CAPEX, "
            "eller så gir ikke OGP+ lavere årlig OPEX i diesel-scenarioet med dine inndata)."
        )
    else:
        st.success(f"Estimert **payback** for OGP+ vs OGP (diesel): **{fmt_num(payback_years, 1)} år**")

    st.caption(
        "Dieselkost pr kWh er beregnet som: dieselpris × liter/kWh. "
        f"Nå: {fmt_num(diesel_cost_per_kwh,2)} NOK/kWh."
    )

st.divider()
st.subheader("Kumulativ kostnad over tid")

tab1, tab2 = st.tabs(["Diesel", "Landstrøm"])

with tab1:
    df_ogp = build_cashflow_table(years, ogp_capex_fleet, annual_opex_ogp_diesel_fleet, discount_rate)
    df_ogpplus = build_cashflow_table(years, ogpplus_capex_fleet, annual_opex_ogpplus_diesel_fleet, discount_rate)

    chart_df = pd.DataFrame({
        "År": df_ogp["År"],
        "OGP akk. kost (NOK)": df_ogp["Akk. kostnad (NOK)"],
        "OGP+ akk. kost (NOK)": df_ogpplus["Akk. kostnad (NOK)"],
    }).set_index("År")
    st.line_chart(chart_df, use_container_width=True)

    chart_df_npv = pd.DataFrame({
        "År": df_ogp["År"],
        "OGP akk. nåverdi (NOK)": df_ogp["Akk. nåverdi (NOK)"],
        "OGP+ akk. nåverdi (NOK)": df_ogpplus["Akk. nåverdi (NOK)"],
    }).set_index("År")
    st.line_chart(chart_df_npv, use_container_width=True)

    with st.expander("Se cashflow-tabeller (diesel)"):
        st.write("**OGP**")
        st.dataframe(df_ogp, use_container_width=True, hide_index=True)
        st.write("**OGP+**")
        st.dataframe(df_ogpplus, use_container_width=True, hide_index=True)

with tab2:
    df_ogp = build_cashflow_table(years, ogp_capex_fleet, annual_opex_ogp_land_fleet, discount_rate)
    df_ogpplus = build_cashflow_table(years, ogpplus_capex_fleet, annual_opex_ogpplus_land_fleet, discount_rate)

    chart_df = pd.DataFrame({
        "År": df_ogp["År"],
        "OGP akk. kost (NOK)": df_ogp["Akk. kostnad (NOK)"],
        "OGP+ akk. kost (NOK)": df_ogpplus["Akk. kostnad (NOK)"],
    }).set_index("År")
    st.line_chart(chart_df, use_container_width=True)

    chart_df_npv = pd.DataFrame({
        "År": df_ogp["År"],
        "OGP akk. nåverdi (NOK)": df_ogp["Akk. nåverdi (NOK)"],
        "OGP+ akk. nåverdi (NOK)": df_ogpplus["Akk. nåverdi (NOK)"],
    }).set_index("År")
    st.line_chart(chart_df_npv, use_container_width=True)

    with st.expander("Se cashflow-tabeller (landstrøm)"):
        st.write("**OGP**")
        st.dataframe(df_ogp, use_container_width=True, hide_index=True)
        st.write("**OGP+**")
        st.dataframe(df_ogpplus, use_container_width=True, hide_index=True)

st.divider()
st.subheader("Eksport")

export = {
    "fleet_n": fleet_n,
    "demand_kgph_per_site": demand,
    "hours_per_year": hours_per_year,
    "years": years,
    "discount_rate": discount_rate,
    "power_price_nok_per_kwh": power_price,
    "diesel_price_nok_per_l": diesel_price,
    "genset_l_per_kwh": genset_l_per_kwh,
    "diesel_cost_per_kwh": diesel_cost_per_kwh,
    "spec_kwh_per_kg_ogp": spec_ogp,
    "spec_kwh_per_kg_ogpplus": spec_ogpplus,
    "ogp_modules_needed_per_site": ogp_modules_needed,
    "ogp_capex_per_site": ogp_capex_site,
    "ogpplus_combo_per_site": ogpplus_counts,
    "ogpplus_capex_per_site": ogpplus_capex_site,
    "npv_ogp_diesel_fleet": npv_ogp_diesel,
    "npv_ogpplus_diesel_fleet": npv_ogpplus_diesel,
    "npv_ogp_land_fleet": npv_ogp_land,
    "npv_ogpplus_land_fleet": npv_ogpplus_land,
}

export_df = pd.DataFrame([export])
csv = export_df.to_csv(index=False).encode("utf-8")

st.download_button(
    "Last ned nøkkelresultater (CSV)",
    data=csv,
    file_name="o2_tco_resultater.csv",
    mime="text/csv",
)

st.caption(
    "Tips: Hvis du ønsker å reflektere mer realistisk dimensjonering (f.eks. redundans N+1, delvis last/virkningsgrad, "
    "felles buffer-/tankstørrelse, eller eskalering på drivstoff), kan vi legge det inn som egne brytere."
)
