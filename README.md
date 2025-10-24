
# O₂ TCO-kalkulator (Streamlit)

Et enkelt webverktøy uten Excel. Kjør lokalt:

```bash
python -m venv .venv
# (Windows) .venv\Scripts\activate
# (Mac/Linux) source .venv/bin/activate
pip install -r requirements.txt
streamlit run app.py
```

- Standarddata ligger i `models.csv` (ekstrahert fra O2_line_selector_v2.xlsx).
- Du kan også laste opp egen CSV med samme kolonner:
  `Model, Series, Tech, Capacity_kg_per_h, SpecificEnergy_kWh_per_kg, CAPEX_NOK`

**Funksjoner**

- Behov: *Lik per linje* (kg/h per linje × antall linjer) eller *Forskjellig per linje* (linjevise behov).
- Kraftkilde: Landstrøm eller Diesel strøm (egen pris + opsjonelt genset‑CAPEX).
- Service: egne satser for PSA og VSA (standard 0,65 % og 1,50 %).
- Resultater: beste totalt, nest beste kun OxyGen, ROI vs alternativ, full tabell og CSV‑eksport.
